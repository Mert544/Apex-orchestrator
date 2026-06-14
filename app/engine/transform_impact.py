"""Quantify the concrete before->after improvement a transform would make.

The *proof of value* behind a recommendation: not "this flattens nesting" but
"max nesting 4->3, cyclomatic 18->16". Given the original and transformed source
of a module (or a single function), this computes the delta for a small fixed set
of grounded structural metrics, so a recommendation can carry a measured win.

Reuses the existing metric helpers — ``function_complexities`` (branch/cyclomatic
proxy) and ``function_cognitive_complexities`` — and computes max nesting depth
cheaply from the AST. Stdlib-only (``ast``), pure (no I/O), deterministic: same
source pair -> same deltas, in a stable order. No LLM.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from app.tools.cognitive_complexity import function_cognitive_complexities
from app.tools.code_metrics import function_complexities

__all__ = ["ImpactDelta", "measure_impact", "summarize"]

# Fixed metric order — drives the stable, sorted output and the summary string.
_METRIC_ORDER = ("max nesting", "cyclomatic", "cognitive", "lines")


@dataclass(frozen=True)
class ImpactDelta:
    """One metric's before->after pair for a transform.

    ``improved`` is True when the metric dropped (lower is better for every
    metric here: nesting, branch count, cognitive load, line count).
    """

    metric: str
    before: int
    after: int

    @property
    def delta(self) -> int:
        """Signed change (after - before); negative means the metric dropped."""
        return self.after - self.before

    @property
    def improved(self) -> bool:
        """True when the transform reduced this metric."""
        return self.after < self.before

    @property
    def changed(self) -> bool:
        """True when before and after differ at all."""
        return self.after != self.before


_NESTING_NODES = (
    ast.If, ast.For, ast.AsyncFor, ast.While,
    ast.With, ast.AsyncWith, ast.Try, ast.ExceptHandler,
)


def _max_nesting(node: ast.AST) -> int:
    """Deepest count of nested control-flow blocks under ``node``.

    Counts the bodies that indent code: ``if``/``for``/``while``/``with``/
    ``try`` and their handlers. Function and class defs do *not* count — this
    measures control-flow depth, so a function holding three nested ``if``s is
    depth 3 whether measured whole-module or scoped to that function. A flat
    function is depth 0; one ``if`` is depth 1, an ``if`` inside a ``for`` is
    depth 2, and so on.
    """

    def depth(n: ast.AST, current: int) -> int:
        best = current
        for child in ast.iter_child_nodes(n):
            step = current + 1 if isinstance(child, _NESTING_NODES) else current
            best = max(best, depth(child, step))
        return best

    return depth(node, 0)


def _line_count(source: str) -> int:
    """Non-blank source lines (blank lines are not a real cost)."""
    return sum(1 for line in source.splitlines() if line.strip())


def _parses(source: str) -> bool:
    try:
        ast.parse(source)
    except SyntaxError:
        return False
    return True


def _scope_function(source: str, function: str) -> str | None:
    """Re-render just one function's source so its metrics can be measured
    in isolation. Returns None when the function isn't present/parseable."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    def find(body: list[ast.stmt], prefix: str) -> ast.AST | None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{node.name}"
                if name == function:
                    return node
                hit = find(node.body, f"{name}.")
                if hit is not None:
                    return hit
            elif isinstance(node, ast.ClassDef):
                hit = find(node.body, f"{prefix}{node.name}.")
                if hit is not None:
                    return hit
        return None

    target = find(tree.body, "")
    if target is None:
        return None
    try:
        return ast.unparse(target)
    except (AttributeError, ValueError):
        return None


def _nesting_metric(source: str) -> int | None:
    """Max nesting for a source string, or None if it won't parse."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return _max_nesting(tree)


def _cyclomatic_metric(source: str) -> int | None:
    """Aggregate branch-node count (cyclomatic proxy) across all functions."""
    if not _parses(source):
        return None
    return sum(c for _name, _lineno, c in function_complexities(source))


def _cognitive_metric(source: str) -> int | None:
    """Aggregate cognitive complexity across all functions."""
    if not _parses(source):
        return None
    return sum(s for _name, _lineno, s in function_cognitive_complexities(source))


def measure_impact(
    before_source: str,
    after_source: str,
    *,
    function: str | None = None,
) -> list[ImpactDelta]:
    """Before->after deltas for a fixed set of grounded structural metrics.

    Compares ``before_source`` against ``after_source`` on max nesting depth,
    cyclomatic/branch complexity, cognitive complexity, and line count. When
    ``function`` is given, both sides are scoped to just that function (e.g.
    ``"Class.method"``); otherwise whole-module aggregates are used.

    A metric whose value can't be computed on either side (a parse error, or a
    named function missing) is omitted gracefully. Output is sorted by a fixed
    metric order, so it is deterministic.
    """
    before = before_source
    after = after_source
    if function is not None:
        before_scoped = _scope_function(before_source, function)
        after_scoped = _scope_function(after_source, function)
        if before_scoped is None or after_scoped is None:
            # Can't isolate the function on one side — nothing measurable.
            return []
        before, after = before_scoped, after_scoped

    measurements = {
        "max nesting": (_nesting_metric(before), _nesting_metric(after)),
        "cyclomatic": (_cyclomatic_metric(before), _cyclomatic_metric(after)),
        "cognitive": (_cognitive_metric(before), _cognitive_metric(after)),
        "lines": (_line_count(before), _line_count(after)),
    }

    deltas: list[ImpactDelta] = []
    for metric in _METRIC_ORDER:
        b, a = measurements[metric]
        if b is None or a is None:
            continue  # omit metrics that couldn't be computed on a side
        deltas.append(ImpactDelta(metric=metric, before=b, after=a))
    return deltas


def summarize(deltas: list[ImpactDelta]) -> str:
    """Render the improved metrics as ``"max nesting 4→3, cyclomatic 18→16"``.

    Only metrics that actually improved (dropped) are shown, in the fixed metric
    order. Returns the empty string when nothing improved.
    """
    order = {name: i for i, name in enumerate(_METRIC_ORDER)}
    improved = sorted(
        (d for d in deltas if d.improved),
        key=lambda d: order.get(d.metric, len(order)),
    )
    return ", ".join(f"{d.metric} {d.before}→{d.after}" for d in improved)
