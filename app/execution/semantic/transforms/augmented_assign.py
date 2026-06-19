from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from ._apply_helpers import parse_or_none as _parse_or_none
from ._apply_helpers import run_rewrite_transformer as _run_rewrite_transformer

# Binary operators that have a corresponding in-place (augmented) form.
_AUG_OPS: tuple[type[ast.operator], ...] = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.BitAnd,
    ast.BitOr,
    ast.BitXor,
    ast.RShift,
    ast.LShift,
)


def _candidate_target(node: ast.Assign) -> ast.Name | None:
    """The bare-Name target of a syntactically-eligible ``x = x <op> rhs``.

    Encodes the structural conditions (one bare-Name target whose id matches the
    LEFT operand of an augmentable BinOp); the *aliasing* guard is applied
    separately in :func:`_alias_unsafe_names`. Returns the target ``Name`` node
    when the shape matches, else ``None``.
    """
    if len(node.targets) != 1:
        return None
    target = node.targets[0]
    if not isinstance(target, ast.Name):
        return None
    value = node.value
    if not isinstance(value, ast.BinOp):
        return None
    if not isinstance(value.op, _AUG_OPS):
        return None
    left = value.left
    if not isinstance(left, ast.Name):
        return None
    if left.id != target.id:
        return None
    return target


def _rewrite_node(node: ast.Assign) -> ast.AugAssign | None:
    """Return an AugAssign for `x = x <op> rhs`, else None.

    Safety conditions (deliberately strict):
      * Exactly one target.
      * Target AND the binop's LEFT operand are both bare ``Name`` nodes with
        the same identifier. We refuse attribute/subscript targets such as
        ``obj.x = obj.x + 1`` because ``obj.x += 1`` would evaluate ``obj``
        only once for the AugAssign whereas the original evaluates it twice;
        if ``obj`` is a property / has side effects, semantics differ.
      * The repeated name must be on the LEFT of the binop. ``x = a + x`` is
        NOT rewritten: for non-commutative ops (``-``, ``/``, ``**`` ...) the
        result differs, and even for ``+`` an overloaded type dispatches
        ``__add__``/``__radd__`` differently from ``__iadd__``.

    The ALIASING guard (an even subtler hazard) is enforced by the caller via
    :func:`_alias_unsafe_names`: ``x = x + [1]`` rebinds ``x`` to a *new* object
    while ``x += [1]`` mutates the existing object *in place*, so for a mutable
    ``x`` that is aliased by another live reference (``b = x``, a parameter the
    caller still holds, a value stashed in a container, ...) the two forms
    diverge. This function only proves the *structural* shape; the alias check
    decides whether the rewrite is behaviour-preserving.
    """
    target = _candidate_target(node)
    if target is None:
        return None
    value = node.value
    assert isinstance(value, ast.BinOp)  # guaranteed by _candidate_target
    new_target = ast.Name(id=target.id, ctx=ast.Store())
    return ast.AugAssign(target=new_target, op=value.op, value=value.right)


def _alias_unsafe_names(tree: ast.Module) -> set[str]:
    """Names that must NOT be rewritten because an alias of the target could
    observe an in-place mutation that the rebinding form never makes.

    ``x = x <op> y`` rebinds ``x`` to a fresh object; ``x += y`` invokes the
    in-place dunder (``__iadd__`` …) which, for a *mutable* ``x``, mutates the
    existing object. The two are observably different exactly when some OTHER
    live reference can read that object AFTER the in-place mutation. Statically
    we cannot know ``x``'s runtime type, so we refuse whenever such a reference
    could exist — but precisely enough to keep the common accumulator
    (``acc = acc + e`` in a loop, then ``return acc``) which is always safe: the
    only reads of ``acc`` are the rewrite's own left operand and a read strictly
    AFTER the last mutation, with no other live alias.

    A candidate name ``x`` is refused iff ANY of:

      * ``x`` is a parameter / ``*args`` / ``**kwargs`` — the caller holds an
        alias of the very object ``+=`` would mutate;
      * ``x`` is declared ``global`` / ``nonlocal`` — an outer scope holds it;
      * ``x`` is *read* (a ``Load`` that is NOT a candidate's own binop-left)
        either inside a loop/comprehension (the read can interleave with the
        repeated mutation — e.g. ``out.append(acc)`` each iteration snapshots a
        DIFFERENT object under rebinding but the SAME mutating object under
        ``+=``), or at a position that is not strictly after the last mutation
        of ``x`` (``b = x``/``g(x)`` BEFORE the ``+=`` creates an alias that then
        observes the mutation; a closure defined before the mutation likewise
        reads the cell later).

    A read strictly after the last mutation and outside any loop (``return acc``,
    ``print(acc)`` after the loop) cannot observe a transition — both forms hold
    the identical final object there — so it is allowed.

    Analysis is over the WHOLE module and keyed by NAME (over-refusing across
    unrelated same-named locals only loses coverage, never correctness).
    Deterministic: pure structural walk, no time/random.
    """
    # Candidate aug-assign targets: the latest mutation line per name, and the
    # binop-left Name node ids that are consumed by the rewrite (exempt reads).
    last_mut: dict[str, int] = {}
    binop_left_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            target = _candidate_target(node)
            if target is not None:
                last_mut[target.id] = max(last_mut.get(target.id, 0), node.lineno)
                assert isinstance(node.value, ast.BinOp)
                binop_left_ids.add(id(node.value.left))

    if not last_mut:
        return set()

    # Nodes whose ancestor chain includes a loop / comprehension: a read here can
    # interleave with the repeated in-place mutation.
    _loops = (ast.For, ast.AsyncFor, ast.While,
              ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
    in_loop_ids: set[int] = set()

    def _descend(node: ast.AST, inside: bool) -> None:
        for child in ast.iter_child_nodes(node):
            child_inside = inside or isinstance(node, _loops)
            if child_inside:
                in_loop_ids.add(id(child))
            _descend(child, child_inside)

    _descend(tree, False)

    unsafe: set[str] = set()

    # External-alias holders: parameters and global/nonlocal declarations.
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
                if arg.arg in last_mut:
                    unsafe.add(arg.arg)
            if args.vararg and args.vararg.arg in last_mut:
                unsafe.add(args.vararg.arg)
            if args.kwarg and args.kwarg.arg in last_mut:
                unsafe.add(args.kwarg.arg)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                if name in last_mut:
                    unsafe.add(name)

    # Reads that could observe an in-place mutation: a Load of a candidate name
    # that is not the rewrite's own binop-left, and is either inside a loop or
    # not strictly after that name's last mutation.
    for node in ast.walk(tree):
        if (isinstance(node, ast.Name)
                and node.id in last_mut
                and isinstance(node.ctx, ast.Load)
                and id(node) not in binop_left_ids
                and (id(node) in in_loop_ids or node.lineno <= last_mut[node.id])):
            unsafe.add(node.id)

    return unsafe


class _AugAssignTransformer(ast.NodeTransformer):
    def __init__(self, blocked: set[str]) -> None:
        self.changed = False
        self._blocked = blocked

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        target = _candidate_target(node)
        if target is None or target.id in self._blocked:
            return node
        rewritten = _rewrite_node(node)
        if rewritten is None:
            return node
        self.changed = True
        return ast.copy_location(rewritten, node)


def apply(rel_path: str, source: str) -> SemanticPatchResult | None:
    tree = _parse_or_none(source)
    if tree is None:
        return None

    blocked = _alias_unsafe_names(tree)
    transformer = _AugAssignTransformer(blocked)
    new_source = _run_rewrite_transformer(tree, transformer, source)
    if new_source is None:
        return None

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_source,
            "expected_old_content": source,
        }],
        transform_type="augmented_assign",
        rationale=[f"Rewrote `x = x <op> y` as augmented assignment in {rel_path}."],
    )
