"""Real-world-validation-lab tests for ``app.engine.readiness_report``.

These tests build a deliberately MESSY synthetic project (a mix of auto-fixable
issues — redundant else, augmented assignment — and flag-only issues — exec,
hardcoded secret, a polyglot ``eval`` in JS) and assert that the fixer-vs-linter
actionability ratio is computed for real: some steps executable, some flag-only.

The fixture is tiny and self-contained (tmp_path) so the suite stays fast — it
NEVER runs the readiness analysis on the whole Apex repo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.readiness_report import (
    fix_actionability,
    readiness_summary,
    render_readiness_markdown,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture()
def messy_project(tmp_path: Path) -> str:
    """A small polyglot project with a MIX of auto-fixable and flag-only issues."""
    pkg = tmp_path / "pkg"
    _write(pkg / "__init__.py", "")
    # Auto-fixable: redundant else + augmented-assign opportunities (+ untested).
    _write(pkg / "calc.py", (
        '"""A calculator with a mix of issues."""\n\n\n'
        "def total(items):\n"
        "    s = 0\n"
        "    for it in items:\n"
        "        s = s + it\n"
        "    return s\n\n\n"
        "def classify(n):\n"
        "    if n > 0:\n"
        '        return "pos"\n'
        "    else:\n"
        '        return "neg"\n\n\n'
        "def run_code(src):\n"
        "    exec(src)\n\n\n"
        'API_KEY = "examplekey_abcdef1234567890secrettoken"\n'
    ))
    _write(pkg / "util.py", (
        "def double(x):\n"
        "    y = x\n"
        "    y = y + x\n"
        "    return y\n"
    ))
    # Flag-only polyglot risk: Apex has no deterministic JS transform.
    _write(tmp_path / "app.js", (
        "function risky(input) {\n"
        "  eval(input);\n"
        "  return input;\n"
        "}\n"
    ))
    return str(tmp_path)


def test_actionability_has_both_executable_and_flag_steps(messy_project: str) -> None:
    """The honest fixer-vs-linter split: some auto-fixable, some flag-only."""
    act = fix_actionability(messy_project)

    assert act["total_steps"] > 0
    # Real mix: the messy project yields BOTH buckets — proving the measurement
    # discriminates auto-fixable transforms from flag-only design/security tasks.
    assert act["executable_steps"] > 0
    assert act["flag_steps"] > 0
    assert act["total_steps"] == act["executable_steps"] + act["flag_steps"]
    # The ratio is the executable fraction, in [0, 1].
    assert act["actionability"] == round(
        act["executable_steps"] / act["total_steps"], 4)
    assert 0.0 < act["actionability"] < 1.0


def test_action_type_counts_partition_total(messy_project: str) -> None:
    """Per-action counts are consistent and partitioned exec vs flag."""
    act = fix_actionability(messy_project)

    assert sum(act["by_action_type"].values()) == act["total_steps"]
    assert sum(act["executable_action_types"].values()) == act["executable_steps"]
    assert sum(act["flag_action_types"].values()) == act["flag_steps"]
    # An auto-fixable transform (e.g. redundant-else / augmented-assign / test
    # stub) appears in the executable bucket; a design_task is always flag-only.
    assert act["executable_action_types"]
    assert "design_task" not in act["executable_action_types"]


def test_design_task_is_flag_only(messy_project: str) -> None:
    """``design_task`` steps (no deterministic transform) are never executable."""
    act = fix_actionability(messy_project)
    if "design_task" in act["by_action_type"]:
        assert act["flag_action_types"].get("design_task") == \
            act["by_action_type"]["design_task"]


def test_readiness_summary_scope_and_findings(messy_project: str) -> None:
    """The summary folds in analyzability coverage and high-confidence findings."""
    summary = readiness_summary(messy_project)

    scope = summary["scope"]
    # 3 Python files (.py) + 1 JS = polyglot; Python is the analyzed subset.
    assert scope["python_files"] == 3
    assert scope["source_files"] >= 4
    assert 0.0 < scope["analyzed_ratio"] < 1.0
    assert scope["out_of_scope_ratio"] == round(1.0 - scope["analyzed_ratio"], 4)
    assert "JavaScript" in scope["language_breakdown"]

    findings = summary["findings"]
    # The polyglot eval() is a high-confidence non-Python finding.
    assert findings["polyglot_findings_count"] >= 1
    assert "js-eval" in findings["polyglot_findings_by_kind"]
    assert findings["high_confidence_total"] == (
        findings["python_security_count"] + findings["polyglot_findings_count"])


def test_summary_actionability_matches_standalone(messy_project: str) -> None:
    """``readiness_summary`` embeds exactly the standalone actionability dict."""
    assert readiness_summary(messy_project)["actionability"] == \
        fix_actionability(messy_project)


def test_determinism(messy_project: str) -> None:
    """Same input → byte-identical output (no time/random)."""
    assert fix_actionability(messy_project) == fix_actionability(messy_project)
    assert readiness_summary(messy_project) == readiness_summary(messy_project)
    assert render_readiness_markdown(messy_project) == \
        render_readiness_markdown(messy_project)


def test_render_markdown_contains_sections(messy_project: str) -> None:
    """The markdown report surfaces the three honest sections deterministically."""
    md = render_readiness_markdown(messy_project)
    assert md.startswith("# Apex Readiness")
    assert "## Fixer vs Linter" in md
    assert "## Repo Coverage" in md
    assert "## High-Confidence Findings" in md
    assert "Actionability:" in md
    assert md.endswith("\n")


def test_empty_and_missing_roots_are_best_effort(tmp_path: Path) -> None:
    """Empty / missing roots never raise — they yield a valid, consistent shape.

    The permutation engine's operator alphabet always fires, so even an empty or
    missing root produces generic plan steps rather than zero; the contract here
    is that the result is well-formed and internally consistent (best-effort),
    not that it is empty.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    act = fix_actionability(str(empty))
    assert act["total_steps"] == act["executable_steps"] + act["flag_steps"]
    assert 0.0 <= act["actionability"] <= 1.0
    assert sum(act["by_action_type"].values()) == act["total_steps"]

    missing = str(tmp_path / "does_not_exist")
    summary = readiness_summary(missing)
    # No real source on a missing root → no high-confidence findings.
    assert summary["findings"]["high_confidence_total"] == 0
    assert summary["scope"]["source_files"] == 0
    # Rendering a degenerate root still produces a valid report.
    md = render_readiness_markdown(missing)
    assert md.startswith("# Apex Readiness")
    assert md.endswith("\n")
