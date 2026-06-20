from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from ._apply_helpers import parse_or_none as _parse_or_none
from ._apply_helpers import run_splice_rewrite as _run_splice_rewrite

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
    last_mut, binop_left_ids = _aug_candidates(tree)
    if not last_mut:
        return set()
    in_loop_ids = _loop_member_ids(tree)
    return (_external_alias_names(tree, last_mut)
            | _observing_read_names(tree, last_mut, binop_left_ids, in_loop_ids))


def _aug_candidates(tree: ast.Module) -> tuple[dict[str, int], set[int]]:
    """``(name -> latest aug-assign lineno, ids of binop-left Name nodes)``.

    The binop-left reads are consumed by the rewrite, so they are exempt from
    the alias-read check."""
    last_mut: dict[str, int] = {}
    binop_left_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            target = _candidate_target(node)
            if target is not None:
                last_mut[target.id] = max(last_mut.get(target.id, 0), node.lineno)
                assert isinstance(node.value, ast.BinOp)
                binop_left_ids.add(id(node.value.left))
    return last_mut, binop_left_ids


def _loop_member_ids(tree: ast.Module) -> set[int]:
    """Ids of nodes whose ancestor chain includes a loop / comprehension — a
    read there can interleave with the repeated in-place mutation."""
    loops = (ast.For, ast.AsyncFor, ast.While,
             ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
    ids: set[int] = set()

    def descend(node: ast.AST, inside: bool) -> None:
        for child in ast.iter_child_nodes(node):
            child_inside = inside or isinstance(node, loops)
            if child_inside:
                ids.add(id(child))
            descend(child, child_inside)

    descend(tree, False)
    return ids


def _external_alias_names(tree: ast.Module, names: dict[str, int]) -> set[str]:
    """Candidate names held by an external alias: a parameter / ``*args`` /
    ``**kwargs``, or a ``global`` / ``nonlocal`` declaration."""
    unsafe: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            params = (*args.posonlyargs, *args.args, *args.kwonlyargs)
            unsafe.update(a.arg for a in params if a.arg in names)
            for extra in (args.vararg, args.kwarg):
                if extra is not None and extra.arg in names:
                    unsafe.add(extra.arg)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            unsafe.update(n for n in node.names if n in names)
    return unsafe


def _observing_read_names(tree: ast.Module, last_mut: dict[str, int],
                          binop_left_ids: set[int],
                          in_loop_ids: set[int]) -> set[str]:
    """Candidate names read where the read could observe an in-place mutation: a
    ``Load`` that is not the rewrite's own binop-left and is either inside a loop
    or not strictly after that name's last mutation."""
    unsafe: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Name)
                and node.id in last_mut
                and isinstance(node.ctx, ast.Load)
                and id(node) not in binop_left_ids
                and (id(node) in in_loop_ids or node.lineno <= last_mut[node.id])):
            unsafe.add(node.id)
    return unsafe


class _AugAssignTransformer(ast.NodeTransformer):
    def __init__(self, blocked: set[str] | None = None) -> None:
        # ``blocked`` is the alias-unsafe name set computed by ``apply`` (the
        # public entry point always passes it); it defaults to empty only so the
        # transformer can be constructed standalone in unit tests of the shared
        # rewrite helper — the safety guard is never bypassed in real use.
        self.changed = False
        self._blocked = blocked or set()

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
    new_source = _run_splice_rewrite(tree, transformer, source)
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
