"""Transform impact: the quantified before->after proof behind a recommendation."""

from __future__ import annotations

from app.engine.transform_impact import ImpactDelta, measure_impact, summarize

# A deeply-nested function and its guard-clause-flattened equivalent.
_NESTED = (
    "def handle(req):\n"
    "    if req:\n"
    "        if req.user:\n"
    "            if req.user.active:\n"
    "                return req.user.name\n"
    "    return None\n"
)

_FLATTENED = (
    "def handle(req):\n"
    "    if not req:\n"
    "        return None\n"
    "    if not req.user:\n"
    "        return None\n"
    "    if not req.user.active:\n"
    "        return None\n"
    "    return req.user.name\n"
)


def _by_metric(deltas: list[ImpactDelta]) -> dict[str, ImpactDelta]:
    return {d.metric: d for d in deltas}


def test_guard_clause_flatten_reduces_nesting():
    deltas = measure_impact(_NESTED, _FLATTENED)
    by = _by_metric(deltas)
    assert "max nesting" in by
    nesting = by["max nesting"]
    assert nesting.before == 3
    assert nesting.after == 1
    assert nesting.improved is True
    assert nesting.delta == -2
    # The summary names the flattened nesting win.
    assert "max nesting 3→1" in summarize(deltas)


def test_impactdelta_helpers():
    d = ImpactDelta(metric="cyclomatic", before=18, after=16)
    assert d.delta == -2
    assert d.improved is True
    assert d.changed is True
    same = ImpactDelta(metric="lines", before=5, after=5)
    assert same.delta == 0
    assert same.improved is False
    assert same.changed is False
    worse = ImpactDelta(metric="lines", before=5, after=7)
    assert worse.improved is False
    assert worse.changed is True


def test_identical_sources_have_empty_summary():
    deltas = measure_impact(_NESTED, _NESTED)
    assert summarize(deltas) == ""
    assert all(not d.improved for d in deltas)
    assert all(not d.changed for d in deltas)


def test_parse_error_after_source_omits_ast_metrics():
    broken = "def handle(req):\n    if req\n        return 1\n"  # missing colon
    deltas = measure_impact(_NESTED, broken)
    metrics = {d.metric for d in deltas}
    # AST-derived metrics can't be computed on the broken side -> omitted.
    assert "max nesting" not in metrics
    assert "cyclomatic" not in metrics
    assert "cognitive" not in metrics
    # Line count is still measurable from raw text.
    assert "lines" in metrics


def test_parse_error_before_source_omits_ast_metrics():
    broken = "def handle(req:\n    return 1\n"
    deltas = measure_impact(broken, _FLATTENED)
    metrics = {d.metric for d in deltas}
    assert "max nesting" not in metrics
    assert "lines" in metrics


def test_function_scope_measures_only_that_function():
    before = (
        "def untouched():\n"
        "    for i in range(3):\n"
        "        for j in range(3):\n"
        "            print(i, j)\n"
        "\n"
    ) + _NESTED
    after = (
        "def untouched():\n"
        "    for i in range(3):\n"
        "        for j in range(3):\n"
        "            print(i, j)\n"
        "\n"
    ) + _FLATTENED
    deltas = measure_impact(before, after, function="handle")
    by = _by_metric(deltas)
    # Only `handle` is compared, so the deeply-nested `untouched` doesn't leak in.
    assert by["max nesting"].before == 3
    assert by["max nesting"].after == 1


def test_missing_named_function_yields_no_deltas():
    assert measure_impact(_NESTED, _FLATTENED, function="nope") == []


def test_cyclomatic_and_cognitive_drop_on_flatten():
    deltas = measure_impact(_NESTED, _FLATTENED)
    by = _by_metric(deltas)
    # Cognitive complexity charges for depth, so the flatten reduces it.
    assert by["cognitive"].improved is True
    summary = summarize(deltas)
    assert "cognitive" in summary


def test_only_improved_metrics_in_summary():
    # An after-source with MORE lines but flatter nesting: lines worsens (omitted),
    # nesting improves (shown).
    deltas = measure_impact(_NESTED, _FLATTENED)
    summary = summarize(deltas)
    by = _by_metric(deltas)
    assert by["lines"].improved is False  # flattened version is longer
    assert "lines" not in summary
    assert "max nesting" in summary


def test_summary_respects_fixed_metric_order():
    deltas = measure_impact(_NESTED, _FLATTENED)
    summary = summarize(deltas)
    # max nesting must precede cyclomatic/cognitive in the rendered string.
    if "cyclomatic" in summary:
        assert summary.index("max nesting") < summary.index("cyclomatic")


def test_deterministic_and_stable_ordering():
    a = measure_impact(_NESTED, _FLATTENED)
    b = measure_impact(_NESTED, _FLATTENED)
    assert a == b
    assert [d.metric for d in a] == ["max nesting", "cyclomatic", "cognitive", "lines"]
    assert summarize(a) == summarize(b)


def test_empty_deltas_summarize_to_empty_string():
    assert summarize([]) == ""
