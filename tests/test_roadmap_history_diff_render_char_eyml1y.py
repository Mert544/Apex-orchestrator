"""Characterization test: render_diff_markdown decomposition is byte-identical.

Loads the pre-refactor snapshot of roadmap_history.py (captured from git HEAD
into a scratch module) and compares its render_diff_markdown output against the
live refactored implementation over many hand-built RoadmapDiff values that
exercise every branch: previous_generated on/off; new/dropped signal phrases
present/absent (singular + plural counts); each of the five sections
present/absent; new lines with/without grounded_in; dropped lines with/without a
signal; and the empty "no changes" footer.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from app.engine.roadmap_history import (
    RoadmapChange,
    RoadmapDiff,
    render_diff_markdown,
)

_REPO = Path(__file__).resolve().parents[1]


def _load_original_render():
    """Materialize the HEAD version of the module and return its renderer."""
    src = subprocess.check_output(
        ["git", "show", "HEAD:app/engine/roadmap_history.py"],
        cwd=_REPO,
        text=True,
    )
    scratch = _REPO / "tests" / "_orig_roadmap_history_eyml1y.py"
    scratch.write_text(src)
    try:
        spec = importlib.util.spec_from_file_location(
            "_orig_roadmap_history_eyml1y", scratch
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod  # dataclass introspection needs this
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop("_orig_roadmap_history_eyml1y", None)
        scratch.unlink(missing_ok=True)
    return mod


_ORIG = _load_original_render()


def _new(title, *, phase="Stabilize", roi=1.5, grounded_in="") -> RoadmapChange:
    return RoadmapChange(
        title=title, subject="app/x.py", status="new",
        curr_phase=phase, curr_roi=roi, grounded_in=grounded_in,
    )


def _dropped(title, *, phase="Evolve", roi=2.0, grounded_in="") -> RoadmapChange:
    return RoadmapChange(
        title=title, subject="app/y.py", status="dropped",
        prev_phase=phase, prev_roi=roi, grounded_in=grounded_in,
    )


def _moved(title) -> RoadmapChange:
    return RoadmapChange(
        title=title, subject="app/z.py", status="phase_moved",
        prev_phase="Stabilize", curr_phase="Evolve",
        prev_roi=1.0, curr_roi=1.2, roi_delta=0.2,
    )


def _roi_up(title) -> RoadmapChange:
    return RoadmapChange(
        title=title, subject="app/u.py", status="roi_up",
        prev_phase="Refine", curr_phase="Refine",
        prev_roi=1.0, curr_roi=1.5, roi_delta=0.5,
    )


def _roi_down(title) -> RoadmapChange:
    return RoadmapChange(
        title=title, subject="app/d.py", status="roi_down",
        prev_phase="Secure", curr_phase="Secure",
        prev_roi=2.0, curr_roi=1.4, roi_delta=-0.6,
    )


def _diffs() -> list[RoadmapDiff]:
    cases: list[RoadmapDiff] = []

    # 1. Fully empty diff, no previous_generated -> "no changes" footer.
    cases.append(RoadmapDiff())

    # 2. Empty diff but with previous_generated set (snapshot ref line).
    cases.append(RoadmapDiff(previous_generated="2026-01-01 00:00:00 UTC"))

    # 3. Only new ideas, one grounded, one not; single distinct signal.
    cases.append(RoadmapDiff(new=[
        _new("Idea A", grounded_in="churn-hotspot: foo.py"),
        _new("Idea B", grounded_in=""),
    ]))

    # 4. New ideas with a repeated signal (plural phrase ×N) + a singular one.
    cases.append(RoadmapDiff(new=[
        _new("A", grounded_in="churn-hotspot: a"),
        _new("B", grounded_in="churn-hotspot: b"),
        _new("C", grounded_in="doc-drift: c"),
        _new("D", grounded_in=""),
    ]))

    # 5. Only dropped, one with signal, one without.
    cases.append(RoadmapDiff(dropped=[
        _dropped("Old A", grounded_in="fragile: x"),
        _dropped("Old B", grounded_in=""),
    ]))

    # 6. Both new and dropped signals present (both story lines + blank).
    cases.append(RoadmapDiff(
        new=[_new("N", grounded_in="churn-hotspot: n")],
        dropped=[_dropped("D", grounded_in="doc-drift: d")],
    ))

    # 7. New/dropped present but all with empty grounded_in (no story lines,
    #    yet the sections still render with bare lines).
    cases.append(RoadmapDiff(
        new=[_new("N1"), _new("N2")],
        dropped=[_dropped("D1")],
    ))

    # 8. Only phase_moved.
    cases.append(RoadmapDiff(phase_moved=[_moved("Mover 1"), _moved("Mover 2")]))

    # 9. Only roi_improved.
    cases.append(RoadmapDiff(roi_improved=[_roi_up("Up 1")]))

    # 10. Only roi_regressed.
    cases.append(RoadmapDiff(roi_regressed=[_roi_down("Down 1")]))

    # 11. Stable count only (no sections) -> "no changes" footer + tally.
    cases.append(RoadmapDiff(stable_count=5))

    # 12. Everything at once with previous_generated and varied signals.
    cases.append(RoadmapDiff(
        previous_generated="2025-12-31 23:59:59 UTC",
        new=[
            _new("New Hub", grounded_in="churn-hotspot: hub.py"),
            _new("New Doc", grounded_in="doc-drift: readme"),
            _new("New Bare", grounded_in=""),
        ],
        dropped=[
            _dropped("Gone Fragile", grounded_in="fragile: legacy"),
            _dropped("Gone Bare", grounded_in=""),
        ],
        phase_moved=[_moved("Shifted")],
        roi_improved=[_roi_up("Better"), _roi_up("Better2")],
        roi_regressed=[_roi_down("Worse")],
        stable_count=3,
    ))

    # 13. grounded_in with no colon (signal == whole string).
    cases.append(RoadmapDiff(new=[_new("X", grounded_in="bare-label")]))

    # 14. grounded_in with whitespace around label.
    cases.append(RoadmapDiff(dropped=[_dropped("Y", grounded_in="  spaced  : v")]))

    return cases


@pytest.mark.parametrize("diff", _diffs())
def test_render_byte_identical(diff: RoadmapDiff) -> None:
    assert render_diff_markdown(diff) == _ORIG.render_diff_markdown(diff)


def test_corpus_covers_every_rendered_block() -> None:
    joined = "\n".join(render_diff_markdown(d) for d in _diffs())
    assert "_compared against snapshot from " in joined
    assert "**Where the new work comes from:**" in joined
    assert "**Signals that stopped firing:**" in joined
    assert " ×2" in joined  # plural signal phrase
    assert "🆕 New ideas" in joined
    assert "✅ No longer surfaced (likely addressed)" in joined
    assert "🔀 Moved phase" in joined
    assert "📈 ROI improved" in joined
    assert "📉 ROI regressed" in joined
    assert "grounded in `" in joined
    assert "signal no longer fires" in joined
    assert "_No changes since the last snapshot._" in joined
    # Empty diff renders header + tally + footer only.
    assert _diffs()[0] not in (None,)
    assert render_diff_markdown(RoadmapDiff()) == (
        "# Roadmap Changes Since Last Run\n\n"
        "0 new · 0 no longer surfaced · 0 moved phase · 0 ROI↑ · 0 ROI↓ · 0 stable\n\n"
        "_No changes since the last snapshot._\n"
    )
