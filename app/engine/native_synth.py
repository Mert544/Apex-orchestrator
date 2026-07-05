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

__all__ = [
    "ReturnExemplar",
    "learn_return_exemplars",
    "adapt_expr_to_params",
    "mind_candidate_exprs",
]


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


def _single_return_expr(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The source of the function's return expression when its body is exactly a
    (optional docstring then a) single ``return <expr>`` — the shape a learned
    candidate can reuse. ``None`` for anything else (multi-statement bodies, a
    bare ``return``, ``yield``, etc.)."""
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(
            getattr(body[0], "value", None), ast.Constant) and isinstance(
            body[0].value.value, str):
        body = body[1:]  # drop a leading docstring
    if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
        return None
    try:
        return ast.unparse(body[0].value)
    except Exception:
        return None


def learn_return_exemplars(sources: list[str]) -> list[ReturnExemplar]:
    """Mine every ``return <expr>`` body from ``sources`` (the project's own code)
    into a deterministic, de-duplicated, sorted library of candidate bodies.

    A function contributes an exemplar only when it has simple positional params
    and a single-return body AND the return expression references ONLY those
    params (a self-contained rule the native intelligence can safely transplant to
    another function of the same arity — no free names, no globals)."""
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
            expr = _single_return_expr(node)
            if expr is None:
                continue
            if not _expr_uses_only(expr, set(params)):
                continue
            seen.add(ReturnExemplar(node.name, params, expr))
    return sorted(seen, key=lambda e: (len(e.params), e.name, e.expr))


def _expr_uses_only(expr: str, allowed: set[str]) -> bool:
    """True when every NAME loaded in ``expr`` is in ``allowed`` (the params) — so
    the body is self-contained and safe to transplant. Attribute/method calls on a
    param (``x.upper()``) are fine; a bare free name (a global/other symbol) is not."""
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in allowed and node.id not in _SAFE_BUILTINS:
                return False
    return True


# Builtins a transplanted expression may reference (pure, always available) — kept
# tiny and side-effect-free on purpose; anything else disqualifies the exemplar.
_SAFE_BUILTINS: frozenset[str] = frozenset({
    "abs", "min", "max", "len", "sum", "sorted", "int", "str", "float", "bool",
    "list", "tuple", "dict", "set", "round", "any", "all", "range", "zip",
    "enumerate", "reversed", "True", "False", "None",
})


def adapt_expr_to_params(exemplar_params: tuple[str, ...], expr: str,
                         stub_params: tuple[str, ...]) -> str | None:
    """Re-point ``expr`` from ``exemplar_params`` onto ``stub_params`` positionally
    (``a+b`` learned from ``(a, b)`` becomes ``x+y`` for a stub ``(x, y)``), or
    ``None`` when the arities differ. Deterministic AST rewrite — a param Name is
    substituted only in a Load context, so nothing else in the expression moves."""
    if len(exemplar_params) != len(stub_params):
        return None
    mapping = dict(zip(exemplar_params, stub_params))
    if all(k == v for k, v in mapping.items()):
        return expr  # identical names — no rewrite needed
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


def mind_candidate_exprs(sources: list[str],
                         stub_params: tuple[str, ...]) -> list[tuple[str, str]]:
    """The native intelligence's ranked ``(label, return_expr)`` candidates for a
    stub of arity ``len(stub_params)``, learned from ``sources`` and adapted to the
    stub's own parameter names. Deterministic and de-duplicated; each label carries
    the honest provenance ``native-mind:<exemplar>`` so a landed body is never
    passed off as a hand-written template.

    These are *proposals only* — the caller runs each through
    ``stub_synthesis``'s never-fake-green gate and lands the first that verifies."""
    out: list[tuple[str, str]] = []
    emitted: set[str] = set()
    for ex in learn_return_exemplars(sources):
        if len(ex.params) != len(stub_params):
            continue
        adapted = adapt_expr_to_params(ex.params, ex.expr, stub_params)
        if adapted is None or adapted in emitted:
            continue
        emitted.add(adapted)
        out.append((f"native-mind:{ex.name}", adapted))
    return out
