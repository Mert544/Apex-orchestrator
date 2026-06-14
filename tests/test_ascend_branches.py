"""Remaining branch edges for the ascend climb.

Targets the last uncovered branches: a zero-budget climb that falls through
to a forced fixpoint (263->295, line 297) and the markdown renderer's
unmeasured-grade branch (365->369).
"""

from __future__ import annotations

import app.engine.ascend as asc
from app.engine.ascend import (
    AscendReport,
    AscendRound,
    render_ascend_markdown,
)


# --- ascend: zero round budget → loop never runs → forced fixpoint -----------

def test_ascend_zero_rounds_forces_fixpoint(tmp_path, monkeypatch):
    # With max_rounds=0 the `for n in range(1, 1)` loop body never executes, so
    # the climb reaches line 295 with no rounds and fixpoint still False; the
    # trailing guard then declares a fixpoint rather than reporting a silent no-op.
    monkeypatch.setattr(asc, "_grade", lambda r: 42)

    def _never_called(*a, **k):  # the loop must not rank anything at budget 0
        raise AssertionError("rank_objectives should not run at max_rounds=0")

    monkeypatch.setattr(asc, "rank_objectives", _never_called)

    report = asc.ascend(str(tmp_path), apply=True, verify=False, max_rounds=0)
    assert report.fixpoint is True
    assert report.rounds == []
    assert report.grade_start == 42
    assert report.grade_end == 42


# --- render_ascend_markdown: rounds present but grade unmeasured (365->369) --

def test_render_ascend_markdown_skips_health_line_when_unmeasured():
    # grade_start defaults to -1 (never measured), so the health summary line is
    # skipped even though there are rounds to render in the table.
    report = AscendReport(
        applied=True,
        rounds=[AscendRound(1, "dead-params", "tidy", 2, 70, 72, 3.0)],
    )
    assert report.grade_start == -1
    md = render_ascend_markdown(report)
    # The round table still renders...
    assert "| 1 | `dead-params` | tidy | 2 | 70→72 |" in md
    # ...but the "Health: ... → ..." proven-climb line is omitted.
    assert "Health:" not in md
