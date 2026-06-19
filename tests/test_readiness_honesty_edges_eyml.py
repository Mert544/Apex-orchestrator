"""Honesty-edge tests for ``app.engine.readiness_report`` (polyglot red-team).

A polyglot red-team found a dishonest edge in the readiness report: when the
profiler fails ENTIRELY (``profile is None``) the Repo Coverage block rendered
"Analyzed 0% · out of scope 0%" — a confident-looking but logically
inconsistent claim (0% analyzed yet also 0% out of scope). These tests pin the
honest replacement ("unknown — analysis unavailable") WITHOUT disturbing the
normal (profiler-succeeds) path, which the companion suites pin byte-for-byte.

The profiler failure is forced deterministically by monkeypatching
``_build_plan_with_profile`` AND ``_profile`` to return ``None`` — the only two
sources of the profile inside :func:`readiness_summary` — so the
``profile is None`` branch is reached without any real profiler error.
Deterministic: fixed literals / monkeypatched returns only (no time, no
randomness, no network).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.engine.readiness_report as rr
from app.engine.readiness_report import (
    readiness_summary,
    render_readiness_markdown,
)


def _force_profile_none(monkeypatch) -> None:
    """Make BOTH profile sources in ``readiness_summary`` return ``None``."""
    monkeypatch.setattr(rr, "_build_plan_with_profile", lambda root: (None, None))
    monkeypatch.setattr(rr, "_profile", lambda root: None)
    # Keep the polyglot scan from touching a real path either.
    monkeypatch.setattr(rr, "_polyglot_findings", lambda root: [])


# --- FIX 1: profile-is-None scope is flagged unanalyzable, not 0%/0% ---------

def test_summary_scope_marked_unanalyzable_when_profile_is_none(monkeypatch) -> None:
    """``readiness_summary`` flags ``analyzable: False`` when the profiler fails.

    The numeric scope fields stay at their best-effort zeros (so existing
    consumers do not crash), but the additive ``analyzable`` flag distinguishes
    "no analysis happened" from "analysis found zero files".
    """
    _force_profile_none(monkeypatch)
    scope = readiness_summary("any-root")["scope"]

    assert scope["analyzable"] is False
    # Best-effort numeric zeros remain (the section shape is otherwise unchanged).
    assert scope["source_files"] == 0
    assert scope["python_files"] == 0
    assert scope["analyzed_ratio"] == 0.0
    assert scope["out_of_scope_ratio"] == 0.0
    assert scope["language_breakdown"] == {}


def test_markdown_renders_unknown_when_profile_is_none(monkeypatch) -> None:
    """The Repo Coverage line reads the honest "unknown" wording, not 0%/0%."""
    _force_profile_none(monkeypatch)
    md = render_readiness_markdown("any-root")

    assert "- **Analyzed (Python):** unknown — analysis unavailable" in md
    # The dishonest two-zeros phrasing must NOT appear.
    assert "Analyzed (Python):** 0% · **out of scope:** 0%" not in md
    # The block header and the source-files line still render normally.
    assert "## Repo Coverage" in md
    assert "- **Source files:** 0 (0 Python)" in md
    assert md.startswith("# Apex Readiness")
    assert md.endswith("\n")


def test_unknown_path_is_deterministic(monkeypatch) -> None:
    """Same forced-failure input → byte-identical honest report."""
    _force_profile_none(monkeypatch)
    assert render_readiness_markdown("any-root") == \
        render_readiness_markdown("any-root")
    assert readiness_summary("any-root") == readiness_summary("any-root")


# --- normal path stays honest-by-percentage (no regression) ------------------

def _py_project(tmp_path: Path) -> str:
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


def test_normal_path_keeps_percentage_line_and_analyzable_true(tmp_path: Path) -> None:
    """When the profiler succeeds, coverage shows real percentages, analyzable True."""
    root = _py_project(tmp_path)
    summary = readiness_summary(root)
    assert summary["scope"]["analyzable"] is True

    md = render_readiness_markdown(root)
    # The honest-unknown wording NEVER appears on the success path.
    assert "unknown — analysis unavailable" not in md
    # A concrete percentage line is rendered instead.
    assert "**Analyzed (Python):**" in md
    assert "out of scope:**" in md


def test_scope_lines_default_analyzable_true_is_byte_identical() -> None:
    """``_scope_lines`` on a dict WITHOUT ``analyzable`` renders the % line.

    Pins that the new flag defaults to True (back-compat): a scope dict from a
    profile-present path that never set ``analyzable`` still renders the
    percentage line, never the "unknown" wording.
    """
    lines = rr._scope_lines({
        "analyzed_ratio": 0.25, "out_of_scope_ratio": 0.75,
        "source_files": 4, "python_files": 1, "language_breakdown": {}})
    assert lines == [
        "## Repo Coverage",
        "",
        "- **Source files:** 4 (1 Python)",
        "- **Analyzed (Python):** 25% · **out of scope:** 75%",
    ]


def test_scope_lines_unknown_when_analyzable_false() -> None:
    """``_scope_lines`` renders the honest line when ``analyzable`` is False,
    and does NOT touch the (irrelevant) zero ratios."""
    lines = rr._scope_lines({
        "analyzed_ratio": 0.0, "out_of_scope_ratio": 0.0,
        "source_files": 0, "python_files": 0,
        "language_breakdown": {}, "analyzable": False})
    assert lines == [
        "## Repo Coverage",
        "",
        "- **Source files:** 0 (0 Python)",
        "- **Analyzed (Python):** unknown — analysis unavailable",
    ]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
