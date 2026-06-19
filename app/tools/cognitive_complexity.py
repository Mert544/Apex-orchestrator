"""Cognitive complexity — how hard a function is for a HUMAN to understand.

Clean-room, stdlib implementation of the published Cognitive Complexity
method (Campbell, SonarSource white paper; validated empirically in
arXiv:2007.12520). Where cyclomatic complexity counts *paths* — and rates a
flat 10-case dispatcher the same as a 4-level nested loop — cognitive
complexity charges for what actually taxes a reader:

  - **+1** for each break in the linear flow: ``if``/ternary, loops,
    ``except`` handlers, a boolean-operator sequence, recursion;
  - **+nesting** on top, for flow-breaks sitting inside other flow-breaks —
    depth is what hurts;
  - ``elif``/``else`` cost **+1 flat** (no nesting penalty: the reader is
    already oriented).

Used as the *narrated* measure alongside the existing branch-count metric
(which keeps driving thresholds, so scores stay stable): hotspot functions
and briefs now say how hard the code *reads*, not just how many paths it has.
Deterministic; same source → same number.
"""

from __future__ import annotations

import ast
from pathlib import Path

__all__ = [
    "cognitive_complexity",
    "function_cognitive_complexities",
    "function_cognitive_complexities_for_path",
]


def _bool_sequences(_node: ast.BoolOp) -> int:
    """Each boolean-operator *sequence* costs +1: ``a and b and c`` is one
    sequence; ``a and b or c`` nests BoolOps and costs one per node."""
    return 1


class _Scorer(ast.NodeVisitor):
    def __init__(self, func_name: str) -> None:
        self.func_name = func_name
        self.score = 0
        self.nesting = 0

    # -- helpers ---------------------------------------------------------
    def _flow_break(self, node: ast.AST, *, nested_parts: list[ast.AST]) -> None:
        self.score += 1 + self.nesting
        self.nesting += 1
        for part in nested_parts:
            self.visit(part)
        self.nesting -= 1

    def _visit_else(self, orelse: list[ast.stmt]) -> None:
        """``elif`` and ``else`` cost +1 flat, without a nesting increment."""
        if not orelse:
            return
        if len(orelse) == 1 and isinstance(orelse[0], ast.If):
            self.score += 1                       # elif: flat +1 …
            elif_node = orelse[0]
            self.nesting += 1                     # … but its BODY is nested
            self.visit(elif_node.test)
            for stmt in elif_node.body:
                self.visit(stmt)
            self.nesting -= 1
            self._visit_else(elif_node.orelse)
        else:
            self.score += 1                       # plain else: flat +1
            for stmt in orelse:
                self.visit(stmt)

    # -- flow breaks -----------------------------------------------------
    def visit_If(self, node: ast.If) -> None:
        self.score += 1 + self.nesting
        self.visit(node.test)
        self.nesting += 1
        for stmt in node.body:
            self.visit(stmt)
        self.nesting -= 1
        self._visit_else(node.orelse)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self._flow_break(node, nested_parts=[node.test, node.body, node.orelse])

    def visit_For(self, node: ast.For) -> None:
        self._flow_break(node, nested_parts=[*node.body])
        self._visit_else(node.orelse)

    visit_AsyncFor = visit_For

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        self._flow_break(node, nested_parts=[*node.body])
        self._visit_else(node.orelse)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self._flow_break(node, nested_parts=[*node.body])

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.score += _bool_sequences(node)
        for value in node.values:
            self.visit(value)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == self.func_name:
            self.score += 1                       # recursion taxes the reader
        self.generic_visit(node)

    # Nested function/class definitions add a nesting level for their bodies.
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.nesting += 1
        for stmt in node.body:
            self.visit(stmt)
        self.nesting -= 1

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.nesting += 1
        self.visit(node.body)
        self.nesting -= 1


def cognitive_complexity(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """The cognitive complexity of one function definition node."""
    scorer = _Scorer(fn.name)
    for stmt in fn.body:
        scorer.visit(stmt)
    return scorer.score


def function_cognitive_complexities(source: str) -> list[tuple[str, int, int]]:
    """``(qualified_name, lineno, cognitive)`` for every function in ``source``
    (methods qualified as ``Class.method``). Unparsable source yields []."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return []
    return _function_cognitive_complexities_tree(tree)


def function_cognitive_complexities_for_path(path: str | Path) -> list[tuple[str, int, int]]:
    """Path-based :func:`function_cognitive_complexities`, routed through the
    shared per-build parse cache so the file is read + parsed once across all
    analyzers. Byte-identical to the source-based call on a parseable file;
    unreadable/unparseable files yield ``[]``."""
    from app.tools.python_structure import parse_cached

    tree = parse_cached(path)
    if tree is None:
        return []
    return _function_cognitive_complexities_tree(tree)


def _function_cognitive_complexities_tree(tree: ast.Module) -> list[tuple[str, int, int]]:
    """Core walk shared by the source- and path-based entry points."""
    out: list[tuple[str, int, int]] = []

    def walk(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{node.name}"
                out.append((name, node.lineno, cognitive_complexity(node)))
                walk(node.body, f"{name}.")
            elif isinstance(node, ast.ClassDef):
                walk(node.body, f"{prefix}{node.name}.")

    walk(tree.body, "")
    return out
