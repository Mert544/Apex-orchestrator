"""Transform impact: ImpactDelta properties, whole-module parse-error omission,
and summarize ordering / empty / non-improved behaviour.

Complements the existing branch suites by pinning the public dataclass
properties and the summary string corners directly. Stdlib-only, pure, and
deterministic: every input is an explicit literal, so a source pair always
yields the same deltas in the same fixed metric order.
"""

from __future__ import annotations

from app.engine.transform_impact import ImpactDelta, measure_impact, summarize


def _by_metric(deltas):
    return {d.metric: d for d in deltas}


# --- ImpactDelta properties -----------------------------------------------------

def test_impactdelta_improved_and_changed_when_dropped():
    d = ImpactDelta(metric="cyclomatic", before=18, after=16)
    assert d.delta == -2
    assert d.improved is True
    assert d.changed is True


def test_impactdelta_regression_is_changed_but_not_improved():
    d = ImpactDelta(metric="lines", before=10, after=14)
    assert d.delta == 4
    assert d.improved is False
    assert d.changed is True


def test_impactdelta_unchanged_metric():
    d = ImpactDelta(metric="cognitive", before=5, after=5)
    assert d.delta == 0
    assert d.improved is False
    assert d.changed is False


# --- whole-module metrics omit a side that won't parse --------------------------

def test_unparseable_before_omits_ast_metrics_keeps_lines():
    # max nesting / cyclomatic / cognitive all need a parse; only line count
    # survives when one side is broken (each metric None-guard at line 188-189).
    broken = "def f(:\n    return 1\n"
    good = "def f():\n    if True:\n        return 1\n    return 0\n"
    metrics = {d.metric for d in measure_impact(broken, good)}
    assert metrics == {"lines"}


def test_unparseable_after_omits_ast_metrics_keeps_lines():
    good = "def f():\n    if True:\n        return 1\n    return 0\n"
    broken = "def f(:\n    return 1\n"
    metrics = {d.metric for d in measure_impact(good, broken)}
    assert metrics == {"lines"}


def test_both_parse_yields_all_four_metrics_in_fixed_order():
    before = (
        "def f(x):\n"
        "    if x:\n"
        "        if x > 0:\n"
        "            return x\n"
        "    return 0\n"
    )
    after = (
        "def f(x):\n"
        "    if x > 0:\n"
        "        return x\n"
        "    return 0\n"
    )
    deltas = measure_impact(before, after)
    assert [d.metric for d in deltas] == [
        "max nesting", "cyclomatic", "cognitive", "lines",
    ]


# --- function scoping: missing function on a side -> no deltas -------------------

def test_function_absent_on_one_side_yields_no_deltas():
    before = "def present(x):\n    return x\n"
    after = "def present(x):\n    return x + 1\n"
    # 'missing' exists on neither side -> _scope_function None -> [].
    assert measure_impact(before, after, function="missing") == []


# --- summarize ------------------------------------------------------------------

def test_summarize_lists_only_improved_in_fixed_order():
    deltas = [
        ImpactDelta(metric="lines", before=20, after=18),       # improved
        ImpactDelta(metric="max nesting", before=4, after=3),   # improved
        ImpactDelta(metric="cyclomatic", before=10, after=12),  # regressed
        ImpactDelta(metric="cognitive", before=8, after=5),     # improved
    ]
    # Fixed order is (max nesting, cyclomatic, cognitive, lines); the regressed
    # cyclomatic is dropped, the rest appear in that order.
    assert summarize(deltas) == (
        "max nesting 4→3, cognitive 8→5, lines 20→18"
    )


def test_summarize_empty_when_nothing_improved():
    deltas = [
        ImpactDelta(metric="lines", before=5, after=5),       # unchanged
        ImpactDelta(metric="cyclomatic", before=3, after=7),  # regressed
    ]
    assert summarize(deltas) == ""


def test_summarize_empty_list_is_empty_string():
    assert summarize([]) == ""


def test_summarize_unknown_metric_sorts_last():
    # A metric not in _METRIC_ORDER falls to the end (order.get default).
    deltas = [
        ImpactDelta(metric="zzz-custom", before=9, after=1),
        ImpactDelta(metric="max nesting", before=4, after=3),
    ]
    assert summarize(deltas) == "max nesting 4→3, zzz-custom 9→1"
