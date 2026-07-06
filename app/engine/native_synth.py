"""Apex native intelligence (v0) — learn to finish code from the project's OWN
proven functions, with NO external LLM and NO token cost.

The deterministic ``stub_synthesis`` engine fills a stub from a FIXED template
space: it can only implement a stub whose correct body matches a pre-written
template. This module grows Apex's own small intelligence past that ceiling —
WITHOUT renting an external model — by MINING the project's existing functions as
a live library of candidate bodies, then proposing the ones whose shape fits an
unfinished stub. Every proposal is still gated the SAME way (``stub_synthesis``'s
never-fake-green verifier): a candidate lands ONLY if it makes the stub's OWN
pinned examples pass, else it is discarded. So the intelligence can *reach*
further than the fixed templates, but can never land anything unverified.

Invariants (the reason this stays inside the zero-token core):

* **No LLM, no network, no tokens** — the "knowledge" is the project's own AST.
* **Deterministic** — same project → same ranked candidates (sorted, no clock /
  random), so a landed body is reproducible and a diff is a real change.
* **Gated** — a candidate is only ever *proposed*; ``stub_synthesis`` disposes.
* **Honest attribution** — a body landed from a learned exemplar is labelled
  ``native-mind:<source>`` so it is never passed off as a hand-written template.
"""

from __future__ import annotations

import ast
import copy

__all__ = [
    "ReturnExemplar",
    "learn_return_exemplars",
    "adapt_expr_to_params",
    "mind_candidate_exprs",
    "canonical_shape",
]


def canonical_shape(params: tuple[str, ...], expr: str) -> str:
    """The arity-qualified IDENTITY of an idiom: ``expr`` with its params renamed to
    positional placeholders ``p0, p1, …`` PREFIXED by the arity (``2:p0 + p1``), so
    ``a + b`` (from ``add(a, b)``) and ``m + n`` (from ``plus(m, n)``) share one key
    while a same-prefix body of a DIFFERENT arity does NOT collide with it — a
    2-arg ``a + b`` (``2:p0 + p1``) and a 3-arg ``a + b`` that ignores its third
    param (``3:p0 + p1``) are distinct idioms, so their experience never
    cross-contaminates. The key the experience memory scores by; deterministic.

    Canonicalisation is POSITIONAL (via :func:`_positional_body`), NOT the
    name-aware stub-adaptation rule: an idiom whose params are literally spelled
    ``p0``/``p1`` (plausible in point/geometry code) is still keyed by argument
    POSITION — ``(p1, p0)`` returning ``p0 - p1`` is "second - first" and keys to
    ``2:p1 - p0`` — so it never collides with a genuine ``2:p0 - p1`` ("first -
    second"), which would silently corrupt the decay memory."""
    return f"{len(params)}:{_positional_body(params, expr)}"


class ReturnExemplar:
    """One proven ``return <expr>`` body mined from an existing function —
    a reusable candidate the native intelligence can adapt to a stub of the same
    arity. Immutable value; ordered by ``(name, expr)`` for determinism."""

    __slots__ = ("name", "params", "expr")

    def __init__(self, name: str, params: tuple[str, ...], expr: str) -> None:
        self.name = name
        self.params = params
        self.expr = expr

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, ReturnExemplar)
                and (self.name, self.params, self.expr)
                == (other.name, other.params, other.expr))

    def __hash__(self) -> int:
        return hash((self.name, self.params, self.expr))

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"ReturnExemplar({self.name!r}, {self.params!r}, {self.expr!r})"


def _positional_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    """The plain positional parameter names (``self``/``cls`` dropped), or an empty
    tuple when the function takes *args/**kwargs/keyword-only/defaults — the native
    candidates only reason about simple positional arguments, exactly like the
    fixed templates."""
    a = node.args
    if a.vararg or a.kwarg or a.kwonlyargs or a.defaults or a.posonlyargs:
        return ()
    names = [p.arg for p in a.args]
    if names and names[0] in ("self", "cls"):
        names = names[1:]
    return tuple(names)


def _strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    """``body`` without a leading docstring statement (a bare string ``Expr``),
    so the return-shape extractors below see only the executable statements."""
    if body and isinstance(body[0], ast.Expr) and isinstance(
            getattr(body[0], "value", None), ast.Constant) and isinstance(
            body[0].value.value, str):
        return body[1:]
    return body


def _single_return_expr(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The source of the function's return expression when its body is exactly a
    (optional docstring then a) single ``return <expr>`` — the shape a learned
    candidate can reuse. ``None`` for anything else (multi-statement bodies, a
    bare ``return``, ``yield``, etc.)."""
    body = _strip_docstring(list(node.body))
    if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
        return None
    try:
        return ast.unparse(body[0].value)
    except Exception:
        return None


def _sole_return_value(stmts: list[ast.stmt]) -> ast.expr | None:
    """The returned expression when ``stmts`` is exactly one ``return <expr>``
    (never a bare ``return``), else ``None`` — the branch shape a guarded return
    is built from."""
    if (len(stmts) == 1 and isinstance(stmts[0], ast.Return)
            and stmts[0].value is not None):
        return stmts[0].value
    return None


def _guarded_return_expr(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The equivalent ternary source for a two-branch GUARDED-return body — the
    next-most-common finishable shape after a plain single return:

    * ``if T: return A`` then ``return B``  (a guard with a trailing fallthrough)
    * ``if T: return A`` ``else: return B`` (an if/else where both branches return)

    both collapse to ``A if T else B``, a single expression the native
    intelligence can transplant exactly like a plain return (positional param
    remap, same-arity, same never-fake-green gate). ``None`` for any richer body
    (elif chains, statements around the branch, a bare ``return`` in a branch)."""
    body = _strip_docstring(list(node.body))
    if not body or not isinstance(body[0], ast.If):
        return None
    guard = body[0]
    a = _sole_return_value(guard.body)
    if a is None:
        return None
    b = _guarded_fallthrough_value(guard, body)
    if b is None:
        return None
    try:
        return ast.unparse(ast.IfExp(test=guard.test, body=a, orelse=b))
    except Exception:
        return None


def _guarded_fallthrough_value(guard: ast.If, body: list[ast.stmt]) -> ast.expr | None:
    """The ``B`` (else value) of a guarded return: the trailing ``return B`` when
    the guard has no ``else`` (shape 1), or the sole ``return B`` in the guard's
    ``else`` when there is nothing after the ``if`` (shape 2). ``None`` for any
    other arrangement, so only the two clean two-branch shapes are learned."""
    if not guard.orelse and len(body) == 2:
        tail = body[1]
        if isinstance(tail, ast.Return) and tail.value is not None:
            return tail.value
        return None
    if guard.orelse and len(body) == 1:
        return _sole_return_value(guard.orelse)
    return None


def _elif_chain_terminal_orelse(guard: ast.If) -> list[ast.stmt]:
    """Walk down an elif chain starting at ``guard`` (an ``if`` whose ``orelse`` is
    a nested ``elif``) to the ``orelse`` of its LAST link — an iterative walk
    (bounded by the chain's own length), not recursion, so this stays a flat,
    low-complexity helper. The result is either ``[]`` (the chain ends with no
    final ``else``) or the final link's own ``orelse`` (``[Return(...)]`` for a
    genuine ``else``, or something richer that disqualifies the shape)."""
    node = guard
    while len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
        node = node.orelse[0]
    return node.orelse


def _elif_link_value(if_node: ast.If, tail: ast.expr | None) -> ast.expr | None:
    """The whole elif chain starting at ``if_node`` — ``if T: return A`` plus
    everything chained in its ``orelse`` — turned into a right-nested
    ``ast.IfExp``, using ``tail`` as the innermost value once the chain runs out
    of ``elif``/``else`` links. ``None`` when any branch along the chain is not a
    sole ``return <expr>`` (a bare return, a multi-statement branch, or an
    ``else`` with more than one statement).

    ITERATIVE, not recursive: it collects each ``(test, value)`` link walking the
    chain down, then folds them right around the innermost fallback. A
    deep/dispatch-table-sized chain (mined from ANY source file in the corpus)
    therefore can never overflow the stack here — the only remaining recursion is
    ``ast.unparse``'s own, which the caller already guards (fails closed)."""
    links: list[tuple[ast.expr, ast.expr]] = []
    node = if_node
    while True:
        value = _sole_return_value(node.body)
        if value is None:
            return None
        links.append((node.test, value))
        orelse = node.orelse
        if len(orelse) == 1 and isinstance(orelse[0], ast.If):
            node = orelse[0]
            continue
        if not orelse:
            fallback = tail
        elif len(orelse) == 1:
            fallback = _sole_return_value(orelse)
        else:
            fallback = None
        break
    if fallback is None:
        return None
    result: ast.expr = fallback
    for test, value in reversed(links):
        result = ast.IfExp(test=test, body=value, orelse=result)
    return result


def _elif_chain_tail(body: list[ast.stmt], guard: ast.If) -> tuple[ast.expr | None, bool]:
    """Resolve an elif chain's trailing fallthrough value and validate the body
    is a complete, clean shape — extracted so :func:`_elif_chain_return_expr`
    stays within the complexity budget.

    Returns ``(tail, ok)``. ``ok`` is ``False`` for any non-conforming body: a
    trailing statement that isn't a sole ``return`` (or extra statements around
    the chain), a chain with neither a final ``else`` nor a trailing
    fallthrough (incomplete), or a trailing ``return`` after a chain that ALREADY
    has a final ``else`` (dead code). ``tail`` is the trailing ``return C`` value
    when present, else ``None`` (the chain's own final ``else`` supplies the
    innermost value)."""
    tail = None
    if len(body) == 2:
        tail = _sole_return_value(body[1:])
        if tail is None:
            return None, False
    elif len(body) != 1:
        return None, False
    terminal = _elif_chain_terminal_orelse(guard)
    if tail is None and not terminal:
        return None, False  # no final else and no trailing fallthrough -> incomplete
    if tail is not None and terminal:
        return None, False  # chain already has a final else -> trailing return is dead
    return tail, True


def _elif_chain_return_expr(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The equivalent right-nested-ternary source for an ELIF-CHAIN return body —
    the next-most-common finishable shape after a plain return and a two-branch
    guard:

    * ``if T1: return A`` / ``elif T2: return B`` / ``else: return C``
    * ``if T1: return A`` / ``elif T2: return B`` / (trailing) ``return C``

    generalised to an arbitrary-length chain ``T1..Tn`` with a final
    ``else``/trailing fallthrough, where EVERY branch is a sole ``return <expr>``.
    Both collapse to ``A if T1 else (B if T2 else C)`` — built by right-nesting
    ``ast.IfExp`` (:func:`_elif_link_value`) and unparsing once, exactly like
    :func:`_guarded_return_expr` does for the 2-branch case. ``None`` for anything
    richer or non-conforming: a branch that isn't a sole return, a chain with no
    final else/fallthrough, a trailing statement after a chain that ALREADY has a
    final else (dead code — not this clean shape), statements around the chain,
    or a body with no ``elif`` link at all (a plain if/else is
    :func:`_guarded_return_expr`'s shape, not this one)."""
    body = _strip_docstring(list(node.body))
    if not body or not isinstance(body[0], ast.If):
        return None
    guard = body[0]
    if not (len(guard.orelse) == 1 and isinstance(guard.orelse[0], ast.If)):
        return None  # no elif link -> not this shape (plain if/else, if any)
    tail, ok = _elif_chain_tail(body, guard)
    if not ok:
        return None
    value = _elif_link_value(guard, tail)
    if value is None:
        return None
    try:
        return ast.unparse(value)
    except Exception:
        return None


def _plain_assign_name(stmt: ast.stmt) -> str | None:
    """The assigned NAME when ``stmt`` is a single-target, plain ``name = <expr>``
    assignment (an ``ast.Assign`` to a bare ``ast.Name``) — ``None`` for anything
    else: tuple/list-unpacking (``x, y = ...``) or attribute/subscript targets
    (``self.x = ...``, ``d[0] = ...``), an ``ast.AugAssign`` (``r += a``), or an
    ``ast.AnnAssign``. Any of those disqualifies the whole inlined-temps shape
    (the caller declines the body outright rather than partially inlining it)."""
    if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)):
        return stmt.targets[0].id
    return None


def _collect_temp_assignments(stmts: list[ast.stmt],
                              params: frozenset[str]) -> list[tuple[str, ast.expr]] | None:
    """The ordered ``(name, rhs)`` pairs of a run of SIMPLE, SINGLE-USE temp
    assignments — ``None`` when any statement is not a plain assignment
    (:func:`_plain_assign_name` — so an ``if``/``for``/``while``/``with``/``try``/
    ``raise``/bare expression/second ``return``/etc. among the assignments
    disqualifies the whole body), a name is assigned more than once (a
    RE-assigned temp is not a clean single-use shape), or a name collides with a
    PARAMETER (``a = a + 1`` mutates the parameter itself — too subtle a shape to
    safely inline, so the whole body is declined rather than guessed at)."""
    pairs: list[tuple[str, ast.expr]] = []
    assigned: set[str] = set()
    for stmt in stmts:
        name = _plain_assign_name(stmt)
        if name is None or name in assigned or name in params:
            return None
        assigned.add(name)
        pairs.append((name, stmt.value))
    return pairs


class _InlineTemp(ast.NodeTransformer):
    """Replace every LOADED reference to one temp name with its (already-folded)
    RHS expression, deep-copied per substitution site so no AST node is shared
    across more than one location in the resulting tree — a body that uses the
    same temp twice (``return r + r``) must get two INDEPENDENT copies of its
    RHS, not one node aliased into two places, for ``ast.unparse`` to render each
    occurrence correctly."""

    def __init__(self, name: str, replacement: ast.expr) -> None:
        self._name = name
        self._replacement = replacement

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if isinstance(node.ctx, ast.Load) and node.id == self._name:
            return copy.deepcopy(self._replacement)
        return node


def _fold_temp_assignments(ret_value: ast.expr,
                           assigns: list[tuple[str, ast.expr]]) -> ast.expr:
    """Inline ``assigns`` (ordered EARLIEST-first, as they appear in the source)
    into ``ret_value`` so the whole body becomes ONE self-contained expression.

    Folds in REVERSE assignment order: substituting the LAST-assigned temp
    FIRST means its own RHS (which may still reference an EARLIER temp) becomes
    part of the expression before that earlier temp's turn — so a chain
    (``x = a + 1; y = x * 2; return y``) resolves correctly to ``(a + 1) * 2``
    with no separate dependency-ordering step."""
    result = ret_value
    for name, rhs in reversed(assigns):
        result = _InlineTemp(name, rhs).visit(result)
    return result


def _method_call_count(tree: ast.AST) -> int:
    """The number of METHOD calls (``obj.meth(...)`` — an ``ast.Call`` whose func
    is an ``ast.Attribute``) in ``tree``. A bare-function call to a safe builtin
    (``len(a)``) has a ``Name`` func and does NOT count — it is pure. The
    inlined-temps shape uses this to refuse a fold that would DUPLICATE (``r =
    a.pop(); return r + r`` -> ``a.pop() + a.pop()``) or REORDER (``x = a.pop(); y
    = a.pop(); return y - x``) a possibly-mutating method call: the
    self-containment gate admits method calls on a param (``x.upper()``) but
    cannot prove them side-effect-free, and — unlike the three verbatim shapes —
    inlining is the step that introduces the extra evaluation, so more than one
    surviving method call means the collapsed body may not match its source."""
    return sum(1 for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute))


def _inlined_temps_return_expr(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The source of a single, self-contained expression for a body that is
    EXACTLY a run of zero-or-more simple, single-use temp assignments followed
    by one ``return <expr>`` — the FOURTH finishable shape, e.g.:

    * ``r = a + 1; return r``               -> ``a + 1``
    * ``s = a + b; return s * 2``           -> ``(a + b) * 2``
    * ``x = a + 1; y = x * 2; return y``    -> ``(a + 1) * 2``  (chained)

    Each temp is substituted into the return expression in order — earlier
    temps resolved into later ones first, via :func:`_fold_temp_assignments` —
    so the whole body collapses to ONE expression the native intelligence can
    transplant exactly like the other three shapes (same positional remap, same
    never-fake-green gate). ``None`` for anything richer or non-conforming: a
    non-assign/return statement anywhere in the body (``if``/``for``/``while``/
    ``with``/``try``/``raise``/a bare expression statement/a bare ``return``/more
    than one ``return``/``yield``), a re-assigned temp, an augmented or
    destructuring/attribute/subscript assignment, a temp name that collides with a
    parameter (see :func:`_collect_temp_assignments`), OR a fold that would leave
    more than one method call (see :func:`_method_call_count`) — inlining a
    possibly-mutating ``a.pop()`` twice, or reordering two of them, would make the
    collapsed body diverge from the source it was learned from."""
    body = _strip_docstring(list(node.body))
    if not body:
        return None
    ret_value = _sole_return_value(body[-1:])
    if ret_value is None:
        return None
    params = frozenset(_positional_params(node))
    assigns = _collect_temp_assignments(body[:-1], params)
    if assigns is None:
        return None
    folded = _fold_temp_assignments(ret_value, assigns)
    if _method_call_count(folded) > 1:
        return None  # inlining would duplicate/reorder a possibly-mutating call
    try:
        return ast.unparse(folded)
    except Exception:
        return None


def learn_return_exemplars(sources: list[str]) -> list[ReturnExemplar]:
    """Mine every ``return <expr>`` body from ``sources`` (the project's own code)
    into a deterministic, de-duplicated, sorted library of candidate bodies.

    A function contributes an exemplar only when it has simple positional params
    and a finishable body — a single ``return <expr>``, a two-branch guarded
    return (``if T: return A; return B`` -> ``A if T else B``), an elif-chain
    return (``if T1: return A; elif T2: return B; else: return C`` -> ``A if T1
    else (B if T2 else C)``), OR a run of single-use temp assignments ending in a
    ``return`` (``r = a + 1; return r`` -> ``a + 1``; chained temps fold in
    order) — AND the resulting expression references ONLY those params (a
    self-contained rule the native intelligence can safely transplant to another
    function of the same arity — no free names, no globals)."""
    seen: set[ReturnExemplar] = set()
    for source in sources:
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = _positional_params(node)
            if not params:
                continue
            expr = (_single_return_expr(node) or _guarded_return_expr(node)
                    or _elif_chain_return_expr(node)
                    or _inlined_temps_return_expr(node))
            if expr is None:
                continue
            if not _expr_uses_only(expr, set(params)):
                continue
            seen.add(ReturnExemplar(node.name, params, expr))
    # Sort on a TOTAL key: (arity, name, expr, params). ``params`` is the final
    # tiebreak so two functions sharing name+arity+expr but differing only in
    # parameter ORDER (``foo(a, b)`` vs ``foo(b, a)``) get a stable, hash-seed
    # independent rank — without it the tie fell to ``set`` iteration order
    # (PYTHONHASHSEED-randomised), making the downstream candidate order and thus
    # a landed body non-reproducible across runs.
    return sorted(seen, key=lambda e: (len(e.params), e.name, e.expr, e.params))


# Binding/scoping/suspension constructs a transplanted body must NOT contain: a
# walrus (``:=``) or a lambda/comprehension binds a name the plain Name-load check
# below does not see as "free", so an unclean body (``[a for _ in a]``,
# ``(z := a)``) could slip through; a ``yield``/``yield from``/``await`` turns the
# spliced function into a generator/coroutine (a different return protocol
# entirely — ``(yield a)`` parses in ``mode="eval"`` on some CPythons, so the
# Name-load scan alone would pass it). A transplantable body is a pure,
# binding-free, non-suspending expression, so any of these disqualifies it outright.
_BINDING_NODES: tuple[type[ast.AST], ...] = (
    ast.NamedExpr, ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp,
    ast.GeneratorExp, ast.Yield, ast.YieldFrom, ast.Await,
)


def _expr_uses_only(expr: str, allowed: set[str]) -> bool:
    """True when ``expr`` is a self-contained, binding-free expression whose every
    loaded NAME is in ``allowed`` (the params) or the safe-builtins allowlist — so
    it is safe to transplant. Attribute/method calls on a param (``x.upper()``) are
    fine; a bare free name (a global/other symbol), OR any binding construct
    (walrus, lambda, comprehension — which introduce names the Name-load scan
    cannot vet), disqualifies it."""
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, _BINDING_NODES):
            return False
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in allowed and node.id not in _SAFE_BUILTINS:
                return False
    return True


# Builtins a transplanted expression may reference — pure, side-effect-free, and
# (critically) each one MUST be present in ``stub_synthesis``'s in-process eval
# sandbox so a learned body evaluates identically on the cheap in-process scan
# (``_expr_matches_all``) and on the pytest apply. Admitting a builtin the sandbox
# lacks (``dict``/``any``/``all``/``range``/``zip``/``enumerate``/``reversed`` used
# to be here) makes the in-process scan raise ``NameError`` and UNDER-COUNT a body
# the pytest gate would actually land — a scan/apply inconsistency. This set is
# therefore kept a SUBSET of that sandbox (a test in tests/ pins the invariant).
# ``True``/``False``/``None`` parse as ``ast.Constant`` (never ``ast.Name``) in
# Py3, so they are constants the sandbox eval handles natively — kept for clarity.
_SAFE_BUILTINS: frozenset[str] = frozenset({
    "abs", "min", "max", "len", "sum", "sorted", "int", "str", "float", "bool",
    "list", "tuple", "set", "round", "hex", "oct", "bin", "chr", "ord",
    "bytes", "bytearray", "True", "False", "None",
})


def _param_mapping(exemplar_params: tuple[str, ...],
                   stub_params: tuple[str, ...]) -> dict[str, str] | None:
    """The exemplar-param -> stub-param NAME mapping :func:`adapt_expr_to_params`
    substitutes by. Deterministic, unambiguous, and never a guess:

    * ``len(exemplar_params) > len(stub_params)`` -> ``None`` (the exemplar needs
      more params than the stub has — cannot fit, full stop).
    * SAME arity, and every exemplar param name is present in ``stub_params`` (a
      set membership, names distinct) -> NAME-AWARE: each exemplar param maps to
      ITSELF (the stub's own same-named param) — correct even when the stub
      reuses the exemplar's exact names in a DIFFERENT order (a non-commutative
      idiom like ``a - b`` transplanted onto a stub ``(b, a)`` must stay
      ``a - b``, not become ``b - a``).
    * SAME arity, NOT every exemplar name present in the stub -> POSITIONAL
      (``zip`` in order) — byte-identical to the original, position-only rule.
    * exemplar arity < stub arity AND the exemplar's names are a DISTINCT SUBSET
      of the stub's names -> each exemplar param maps to itself, same as the
      name-aware case above (the exemplar's body only ever reads its own
      params, so the stub's extra params are simply left unused).
    * exemplar arity < stub arity with NO such subset relationship -> ``None``
      (no shared names to align by — refuse rather than guess which stub
      param each exemplar param means)."""
    if len(exemplar_params) > len(stub_params):
        return None
    stub_names = set(stub_params)
    if len(exemplar_params) == len(stub_params):
        if set(exemplar_params) <= stub_names:
            return {p: p for p in exemplar_params}
        return dict(zip(exemplar_params, stub_params))
    if set(exemplar_params) <= stub_names:
        return {p: p for p in exemplar_params}
    return None


def _rename_names(expr: str, mapping: dict[str, str]) -> str | None:
    """``expr`` with every LOADED ``Name`` substituted per ``mapping`` (old -> new
    name), unparsed — or ``None`` when ``expr`` doesn't parse as an expression. An
    identity mapping (every ``k == v``) returns ``expr`` verbatim; only
    Load-context Names move, so nothing else in the tree changes. The shared
    rewrite engine behind BOTH the name/positional stub adaptation
    (:func:`adapt_expr_to_params`) and the positional canonicalisation
    (:func:`_positional_body`)."""
    if all(k == v for k, v in mapping.items()):
        return expr
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError):
        return None

    class _Remap(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.Name:
            if isinstance(node.ctx, ast.Load) and node.id in mapping:
                return ast.copy_location(
                    ast.Name(id=mapping[node.id], ctx=ast.Load()), node)
            return node

    try:
        return ast.unparse(_Remap().visit(tree))
    except Exception:
        return None


def _positional_body(params: tuple[str, ...], expr: str) -> str:
    """``expr`` with each param renamed to its POSITIONAL placeholder ``p{i}`` (the
    param at index ``i`` -> ``p{i}``), ALWAYS by position — never the name-aware
    stub-adaptation rule. The canonicalisation primitive shared by
    :func:`canonical_shape` and the native-mind report, so an idiom whose params
    are literally spelled ``p0``/``p1`` is still keyed by ARGUMENT POSITION and
    two idioms computing different things can never collide on one key. Falls
    back to the raw ``expr`` only when it doesn't parse (never in practice for a
    learned exemplar)."""
    canon = tuple(f"p{i}" for i in range(len(params)))
    adapted = _rename_names(expr, dict(zip(params, canon)))
    return adapted if adapted is not None else expr


def adapt_expr_to_params(exemplar_params: tuple[str, ...], expr: str,
                         stub_params: tuple[str, ...]) -> str | None:
    """Re-point ``expr`` from ``exemplar_params`` onto ``stub_params`` — by NAME
    when the stub reuses the exemplar's own param names (same arity in a
    different order, or a distinct subset for a WIDER stub), else positionally
    (``a+b`` learned from ``(a, b)`` becomes ``x+y`` for a stub ``(x, y)``); see
    :func:`_param_mapping` for the exact rule table. ``None`` when the exemplar
    can't be placed at all (too many params, or no shared names to align a
    wider stub by). Deterministic AST rewrite — a param Name is substituted only
    in a Load context, so nothing else in the expression moves."""
    mapping = _param_mapping(exemplar_params, stub_params)
    if mapping is None:
        return None
    return _rename_names(expr, mapping)


def _body_calls_a_shadowed_builtin(expr: str, exemplar_params: tuple[str, ...],
                                   shadowed: set[str]) -> bool:
    """True when ``expr`` references a SAFE BUILTIN whose name is ALSO a stub param
    (in ``shadowed``) and is not itself an exemplar param — after the positional
    remap introduces that param, the name resolves to the param and shadows the
    builtin, producing a corrupt body (``len(a)`` onto a stub ``(len,)`` becomes
    ``len(len)``). Such a candidate is dropped rather than proposed: it would be
    gate-refused anyway, so this only avoids a wasted, misleading proposal."""
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError):
        return True  # unparseable — drop conservatively
    allowed = set(exemplar_params)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                and node.id in shadowed and node.id not in allowed):
            return True
    return False


def mind_candidate_exprs(sources: list[str],
                         stub_params: tuple[str, ...]) -> list[tuple[str, str]]:
    """The native intelligence's ranked ``(label, return_expr)`` candidates for a
    stub of arity ``len(stub_params)``, learned from ``sources`` and adapted to the
    stub's own parameter names. Deterministic and de-duplicated; each label carries
    the honest provenance ``native-mind:<exemplar>`` so a landed body is never
    passed off as a hand-written template.

    An exemplar of the SAME arity as the stub adapts by name or position (see
    :func:`_param_mapping`); one of a SMALLER arity also adapts when its own
    param names are a distinct subset of the stub's (a 2-arg idiom can finish a
    wider stub whose signature reuses those exact names) — anything
    :func:`adapt_expr_to_params` can't unambiguously place (a bigger exemplar, or
    a smaller one with no shared names) is skipped, never guessed at.

    Ranked by a learned PRIOR from the project's own code: a body shape exhibited
    by MORE of the project's functions (after adaptation to the stub params) is the
    dominant idiom here, so it is proposed FIRST — the native intelligence prefers
    the pattern the codebase itself uses most, then breaks ties by the stable
    exemplar order. This only reorders *proposals*; correctness is unchanged
    because the caller still runs each through ``stub_synthesis``'s never-fake-green
    gate and lands the first that verifies (a wrong-but-frequent shape is refused,
    a right-but-rare one still gets its turn)."""
    shadowed = set(stub_params) & _SAFE_BUILTINS
    frequency: dict[str, int] = {}
    first: dict[str, tuple[int, str]] = {}
    for index, ex in enumerate(learn_return_exemplars(sources)):
        if len(ex.params) > len(stub_params):
            continue
        if shadowed and _body_calls_a_shadowed_builtin(ex.expr, ex.params, shadowed):
            continue  # a stub param is named after a builtin the body uses
        adapted = adapt_expr_to_params(ex.params, ex.expr, stub_params)
        if adapted is None:
            continue
        frequency[adapted] = frequency.get(adapted, 0) + 1
        if adapted not in first:
            first[adapted] = (index, f"native-mind:{ex.name}")
    ranked = sorted(first, key=lambda expr: (-frequency[expr], first[expr][0]))
    return [(first[expr][1], expr) for expr in ranked]
