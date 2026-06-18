"""Mutation-hardening proof for ``app.engine.readiness_report``.

The companion suite ``test_readiness_report_eyml`` proves the end-to-end wiring
on a realistic messy tree, but its assertions are mostly *relational* (``> 0``,
partition identities) — a surviving arithmetic / comparison / constant mutant in
the report module could slip past them. This file pins the EXACT behaviour of
every public function and every pure helper so a flipped operator or a nudged
constant makes a concrete assertion fail:

  * the ``>= 0.6`` / ``>= 0.3`` verdict thresholds, exactly at the boundary and
    one tick below it (``fixer`` vs ``mixed`` vs ``linter`` framing);
  * the ``executable / total`` actionability arithmetic and its 4-dp rounding,
    including the ``total == 0`` early return that yields ``0.0`` (not a
    ZeroDivisionError);
  * the exact percentage rounding (``int(round(ratio * 100))``) in the rendered
    markdown, and the exact rendered substrings / ``(none)`` fallbacks;
  * the scope / findings section dict shapes for both a populated profile and
    the ``profile is None`` best-effort branch.

Deterministic: every input is a fixed literal or a tiny ``tmp_path`` tree — no
time, no randomness, no network, no PYTHONHASHSEED dependence (every emitted
mapping is ``sorted`` by the module).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.readiness_report import (
    _actionability_lines,
    _findings_lines,
    _findings_section,
    _scope_lines,
    _scope_section,
    _verdict,
    fix_actionability,
    readiness_summary,
    render_readiness_markdown,
)


# --- _verdict: the fixer-vs-linter thresholds, pinned at the boundaries -----

def test_verdict_at_and_above_auto_fixer_boundary() -> None:
    """``actionability >= 0.6`` reads as auto-fixer — boundary inclusive."""
    expected = "auto-fixer — most planned steps have a deterministic transform"
    assert _verdict(0.6) == expected
    assert _verdict(0.6000) == expected
    assert _verdict(1.0) == expected


def test_verdict_just_below_auto_fixer_boundary_is_mixed() -> None:
    """One tick below 0.6 falls to the mixed framing (>= comparison, not >)."""
    assert _verdict(0.5999) == \
        "mixed — a meaningful share auto-fixes, the rest is flag-only"


def test_verdict_at_and_above_mixed_boundary() -> None:
    """``0.3 <= actionability < 0.6`` reads as mixed — lower boundary inclusive."""
    expected = "mixed — a meaningful share auto-fixes, the rest is flag-only"
    assert _verdict(0.3) == expected
    assert _verdict(0.3000) == expected
    assert _verdict(0.5999) == expected


def test_verdict_just_below_mixed_boundary_is_linter() -> None:
    """Below 0.3 reads as mostly-linter — and 0.0 lands here too."""
    expected = "mostly linter — most findings are flagged for a human, not auto-fixed"
    assert _verdict(0.2999) == expected
    assert _verdict(0.0) == expected


# --- fix_actionability: the executable/total arithmetic & rounding ----------

def _py_project(tmp_path: Path) -> str:
    """A tiny pure-Python tree that yields a real, non-empty action plan."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "calc.py").write_text(
        "def classify(n):\n"
        "    if n > 0:\n"
        '        return "pos"\n'
        "    else:\n"
        '        return "neg"\n',
        encoding="utf-8",
    )
    return str(tmp_path)


def test_actionability_partition_and_ratio_are_exact(tmp_path: Path) -> None:
    """total = exec + flag, and actionability is exactly round(exec/total, 4)."""
    act = fix_actionability(_py_project(tmp_path))
    total = act["total_steps"]
    executable = act["executable_steps"]
    flag = act["flag_steps"]

    assert total == executable + flag
    assert flag == total - executable
    # The ratio is the executable fraction rounded to 4 dp — exact, not bounded.
    assert act["actionability"] == round(executable / total, 4)
    # Per-action Counters partition the totals exactly.
    assert sum(act["by_action_type"].values()) == total
    assert sum(act["executable_action_types"].values()) == executable
    assert sum(act["flag_action_types"].values()) == flag


def test_actionability_empty_root_yields_consistent_shape(tmp_path: Path) -> None:
    """An empty dir is best-effort: a valid, internally-consistent dict."""
    empty = tmp_path / "empty"
    empty.mkdir()
    act = fix_actionability(str(empty))

    assert act["total_steps"] == act["executable_steps"] + act["flag_steps"]
    assert 0.0 <= act["actionability"] <= 1.0
    if act["total_steps"] == 0:
        # The ``total == 0`` branch returns the literal 0.0, never divides.
        assert act["actionability"] == 0.0
        assert act["by_action_type"] == {}
        assert act["executable_action_types"] == {}
        assert act["flag_action_types"] == {}


def test_actionability_zero_division_guard_returns_float_zero(monkeypatch) -> None:
    """When the plan has no steps, actionability is exactly 0.0 (no crash)."""
    import app.engine.readiness_report as rr

    monkeypatch.setattr(rr, "_build_plan", lambda root: None)
    act = rr.fix_actionability("any-root")
    assert act["total_steps"] == 0
    assert act["executable_steps"] == 0
    assert act["flag_steps"] == 0
    assert act["actionability"] == 0.0
    assert act["by_action_type"] == {}


class _FakeStep:
    def __init__(self, action_type: str, executable: bool) -> None:
        self.action_type = action_type
        self.executable = executable


class _FakePlan:
    def __init__(self, steps: list[_FakeStep]) -> None:
        self.steps = steps


def test_actionability_counts_and_ratio_on_synthetic_plan(monkeypatch) -> None:
    """A hand-built plan pins exact bucket counts, ratio, and sorted Counters."""
    import app.engine.readiness_report as rr

    steps = [
        _FakeStep("redundant_else", True),
        _FakeStep("redundant_else", True),
        _FakeStep("augmented_assign", True),
        _FakeStep("design_task", False),
        _FakeStep("design_task", False),
    ]
    monkeypatch.setattr(rr, "_build_plan", lambda root: _FakePlan(steps))
    act = rr.fix_actionability("synthetic")

    assert act["total_steps"] == 5
    assert act["executable_steps"] == 3
    assert act["flag_steps"] == 2
    assert act["actionability"] == 0.6  # round(3/5, 4)
    # Sorted, exact per-action partitions.
    assert act["by_action_type"] == {
        "augmented_assign": 1, "design_task": 2, "redundant_else": 2}
    assert act["executable_action_types"] == {
        "augmented_assign": 1, "redundant_else": 2}
    assert act["flag_action_types"] == {"design_task": 2}


def test_actionability_unknown_action_type_label(monkeypatch) -> None:
    """A step with a falsy ``action_type`` is bucketed under ``<unknown>``."""
    import app.engine.readiness_report as rr

    monkeypatch.setattr(
        rr, "_build_plan",
        lambda root: _FakePlan([_FakeStep("", True), _FakeStep(None, False)]))
    act = rr.fix_actionability("synthetic")
    assert act["by_action_type"] == {"<unknown>": 2}
    assert act["executable_action_types"] == {"<unknown>": 1}
    assert act["flag_action_types"] == {"<unknown>": 1}


# --- _scope_section: populated vs None (best-effort) branch -----------------

class _FakeProfile:
    source_file_count = 10
    python_file_count = 4
    analyzed_ratio = 0.40004      # rounds to 0.4 at 4 dp
    out_of_scope_ratio = 0.59996  # rounds to 0.6 at 4 dp
    language_breakdown = {"Go": 2, "JavaScript": 1}
    security_finding_modules = ["mod_b", "mod_a"]


def test_scope_section_reads_profile_fields_exactly() -> None:
    scope = _scope_section(_FakeProfile())
    assert scope == {
        "source_files": 10,
        "python_files": 4,
        "analyzed_ratio": 0.4,
        "out_of_scope_ratio": 0.6,
        "language_breakdown": {"Go": 2, "JavaScript": 1},  # sorted
    }


def test_scope_section_getattr_defaults_when_fields_absent() -> None:
    """A profile object missing every scope attribute falls back to 0 / 0.0 / {}.

    This pins the ``getattr(..., DEFAULT)`` defaults themselves: a mutant that
    nudges any default (0 -> 1, 0.0 -> 1.0) would change this output.
    """
    class _Bare:  # no scope attributes at all
        pass

    assert _scope_section(_Bare()) == {
        "source_files": 0,
        "python_files": 0,
        "analyzed_ratio": 0.0,
        "out_of_scope_ratio": 0.0,
        "language_breakdown": {},
    }


def test_scope_section_none_profile_is_all_zero() -> None:
    """The ``profile is None`` branch yields the empty/zero section."""
    assert _scope_section(None) == {
        "source_files": 0,
        "python_files": 0,
        "analyzed_ratio": 0.0,
        "out_of_scope_ratio": 0.0,
        "language_breakdown": {},
    }


# --- _findings_section: Python security + polyglot folding ------------------

def test_findings_section_combines_security_and_polyglot() -> None:
    polyglot = [{"kind": "js-eval"}, {"kind": "js-eval"}, {"kind": "sh-curl"}]
    findings = _findings_section(_FakeProfile(), polyglot)
    assert findings == {
        "python_security_modules": ["mod_a", "mod_b"],  # sorted
        "python_security_count": 2,
        "polyglot_findings_count": 3,
        "polyglot_findings_by_kind": {"js-eval": 2, "sh-curl": 1},  # sorted
        "high_confidence_total": 5,  # 2 + 3, not 2*3 or 2-3
    }


def test_findings_section_none_profile_and_empty_polyglot() -> None:
    findings = _findings_section(None, [])
    assert findings == {
        "python_security_modules": [],
        "python_security_count": 0,
        "polyglot_findings_count": 0,
        "polyglot_findings_by_kind": {},
        "high_confidence_total": 0,
    }


def test_findings_section_polyglot_without_kind_is_unknown() -> None:
    findings = _findings_section(None, [{}, {"kind": "js-eval"}])
    assert findings["polyglot_findings_by_kind"] == {"<unknown>": 1, "js-eval": 1}
    assert findings["high_confidence_total"] == 2


# --- _actionability_lines: exact rendering & percentage rounding ------------

def test_actionability_lines_exact_rendering_with_buckets() -> None:
    act = {
        "actionability": 0.6,
        "executable_steps": 3,
        "total_steps": 5,
        "flag_steps": 2,
        "executable_action_types": {"a": 2, "b": 1},
        "flag_action_types": {"design_task": 2},
    }
    assert _actionability_lines(act) == [
        "## Fixer vs Linter",
        "",
        "- **Actionability:** 60% (3/5 steps auto-fixable) — "
        "auto-fixer — most planned steps have a deterministic transform",
        "- **Auto-fixable steps:** 3",
        "- **Flag-only steps:** 2",
        "",
        "### Auto-fixable by action",
        "- `a` × 2",
        "- `b` × 1",
        "",
        "### Flag-only by action",
        "- `design_task` × 2",
    ]


def test_actionability_lines_percentage_rounds_to_nearest_int() -> None:
    """``int(round(ratio * 100))`` — 0.3334 -> 33%, 0.6667 -> 67%."""
    low = _actionability_lines({
        "actionability": 0.3334, "executable_steps": 1, "total_steps": 3,
        "flag_steps": 2, "executable_action_types": {}, "flag_action_types": {}})
    assert "**Actionability:** 33% (1/3 steps auto-fixable)" in low[2]
    # Below 0.6 but at/above 0.3 -> the mixed verdict is appended.
    assert low[2].endswith(
        "mixed — a meaningful share auto-fixes, the rest is flag-only")

    high = _actionability_lines({
        "actionability": 0.6667, "executable_steps": 2, "total_steps": 3,
        "flag_steps": 1, "executable_action_types": {}, "flag_action_types": {}})
    assert "**Actionability:** 67% (2/3 steps auto-fixable)" in high[2]


def test_actionability_lines_none_fallback_when_empty_buckets() -> None:
    """Empty exec/flag bucket maps render the literal ``- (none)`` placeholder."""
    lines = _actionability_lines({
        "actionability": 0.0, "executable_steps": 0, "total_steps": 0,
        "flag_steps": 0, "executable_action_types": {}, "flag_action_types": {}})
    assert lines == [
        "## Fixer vs Linter",
        "",
        "- **Actionability:** 0% (0/0 steps auto-fixable) — "
        "mostly linter — most findings are flagged for a human, not auto-fixed",
        "- **Auto-fixable steps:** 0",
        "- **Flag-only steps:** 0",
        "",
        "### Auto-fixable by action",
        "- (none)",
        "",
        "### Flag-only by action",
        "- (none)",
    ]


# --- _scope_lines: exact percentages and optional language line -------------

def test_scope_lines_with_language_breakdown() -> None:
    lines = _scope_lines({
        "analyzed_ratio": 0.25, "out_of_scope_ratio": 0.75,
        "source_files": 4, "python_files": 1,
        "language_breakdown": {"Go": 1, "JavaScript": 2}})
    assert lines == [
        "## Repo Coverage",
        "",
        "- **Source files:** 4 (1 Python)",
        "- **Analyzed (Python):** 25% · **out of scope:** 75%",
        "- **Non-Python languages:** Go 1, JavaScript 2",
    ]


def test_scope_lines_omits_language_line_when_empty() -> None:
    lines = _scope_lines({
        "analyzed_ratio": 1.0, "out_of_scope_ratio": 0.0,
        "source_files": 3, "python_files": 3, "language_breakdown": {}})
    assert lines == [
        "## Repo Coverage",
        "",
        "- **Source files:** 3 (3 Python)",
        "- **Analyzed (Python):** 100% · **out of scope:** 0%",
    ]


# --- _findings_lines: exact rendering and optional by-kind line -------------

def test_findings_lines_with_polyglot_by_kind() -> None:
    lines = _findings_lines({
        "high_confidence_total": 3, "python_security_count": 1,
        "polyglot_findings_count": 2,
        "polyglot_findings_by_kind": {"js-eval": 2}})
    assert lines == [
        "## High-Confidence Findings",
        "",
        "- **Total:** 3 (Python security 1 · polyglot 2)",
        "- **Polyglot findings by kind:** js-eval 2",
    ]


def test_findings_lines_omits_by_kind_when_empty() -> None:
    lines = _findings_lines({
        "high_confidence_total": 0, "python_security_count": 0,
        "polyglot_findings_count": 0, "polyglot_findings_by_kind": {}})
    assert lines == [
        "## High-Confidence Findings",
        "",
        "- **Total:** 0 (Python security 0 · polyglot 0)",
    ]


# --- best-effort except branches return their empty fallbacks ---------------

def test_polyglot_findings_returns_empty_list_on_scan_failure(monkeypatch) -> None:
    """If the polyglot scan raises, the helper swallows it and returns ``[]``.

    Pins the except-branch fallback as an empty *list* (not ``None``): the
    downstream ``Counter``/``len`` over it must stay well-defined.
    """
    import app.engine.polyglot_findings as pf
    import app.engine.readiness_report as rr

    def _boom(_root):
        raise RuntimeError("scan exploded")

    monkeypatch.setattr(pf, "scan_polyglot_findings", _boom)
    result = rr._polyglot_findings("any-root")
    assert result == []
    assert isinstance(result, list)


def test_profile_returns_none_on_profiler_failure(monkeypatch) -> None:
    """If the profiler raises, ``_profile`` swallows it and returns ``None``."""
    import app.engine.readiness_report as rr
    import app.tools.project_profile as ppmod

    class _Boom:
        def __init__(self, _root):
            raise RuntimeError("profile exploded")

    monkeypatch.setattr(ppmod, "ProjectProfiler", _Boom)
    assert rr._profile("any-root") is None


# --- readiness_summary: embeds exactly the standalone pieces ----------------

def test_summary_embeds_standalone_actionability(tmp_path: Path) -> None:
    root = _py_project(tmp_path)
    summary = readiness_summary(root)
    assert summary["root"] == str(root)
    assert summary["actionability"] == fix_actionability(root)
    # The four top-level keys are exactly these.
    assert set(summary) == {"root", "actionability", "scope", "findings"}


def test_summary_polyglot_tree_exact_scope_and_findings(tmp_path: Path) -> None:
    """A fixed 2-Python-files + 1-JS tree pins exact scope ratios and findings.

    This drives ``_profile`` and ``_polyglot_findings`` end-to-end (not via
    monkeypatch): a mutant that short-circuits either helper to its empty
    fallback would zero out one of these exact values.
    """
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "m.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
    (tmp_path / "app.js").write_text(
        "function r(i){ eval(i); return i; }\n", encoding="utf-8")

    summary = readiness_summary(str(tmp_path))
    scope = summary["scope"]
    assert scope["source_files"] == 3
    assert scope["python_files"] == 2
    assert scope["analyzed_ratio"] == 0.6667   # 2/3 at 4 dp
    assert scope["out_of_scope_ratio"] == 0.3333
    assert scope["language_breakdown"] == {"JavaScript": 1}

    findings = summary["findings"]
    assert findings["polyglot_findings_count"] == 1
    assert findings["polyglot_findings_by_kind"] == {"js-eval": 1}
    assert findings["python_security_count"] == 0
    assert findings["high_confidence_total"] == 1


def test_summary_missing_root_is_zero_findings(tmp_path: Path) -> None:
    missing = str(tmp_path / "nope")
    summary = readiness_summary(missing)
    assert summary["findings"]["high_confidence_total"] == 0
    assert summary["scope"]["source_files"] == 0


# --- render_readiness_markdown: composition & determinism -------------------

def test_render_markdown_structure_and_order(tmp_path: Path) -> None:
    md = render_readiness_markdown(_py_project(tmp_path))
    assert md.startswith(f"# Apex Readiness — {Path(tmp_path).resolve().name}\n")
    assert md.endswith("\n")
    # The three sections appear once each, in this exact order.
    fixer = md.index("## Fixer vs Linter")
    coverage = md.index("## Repo Coverage")
    findings = md.index("## High-Confidence Findings")
    assert fixer < coverage < findings
    assert md.count("## Fixer vs Linter") == 1


def test_render_markdown_is_deterministic(tmp_path: Path) -> None:
    root = _py_project(tmp_path)
    assert render_readiness_markdown(root) == render_readiness_markdown(root)


def test_render_markdown_uses_resolved_dir_name(tmp_path: Path) -> None:
    """The report title is the resolved basename of the root path."""
    sub = tmp_path / "my_project"
    sub.mkdir()
    md = render_readiness_markdown(str(sub))
    assert md.startswith("# Apex Readiness — my_project\n")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
