"""Remaining branch edges for the evolution loop's renderers and history I/O.

Targets the markdown renderer's no-per-cycle branch (223->231) and the
history loader skipping a blank line without halting (268->266).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.evolution import (
    HISTORY_REL,
    EvolutionResult,
    load_history,
    render_evolution_markdown,
)


def _result(**over):
    base = dict(
        cycles_run=1, reached_fixpoint=True, applied=2, rolled_back=0,
        before={"security_findings": 3, "executable_fixes": 5, "mean_roi": 2.0},
        after={"security_findings": 1, "executable_fixes": 2, "mean_roi": 1.0},
        roadmap_diff={"dropped": []},
        per_cycle=[],
        mode="supervised",
    )
    base.update(over)
    return EvolutionResult(**base)


# --- render markdown: empty per_cycle skips the section (223->231) -----------

def test_render_evolution_markdown_no_per_cycle_section():
    # With no per-cycle records and nothing resolved, neither optional section
    # is emitted — the renderer falls straight through to the return.
    result = _result(per_cycle=[], roadmap_diff={"dropped": []})
    md = render_evolution_markdown(result, "/tmp/proj")
    assert "Per cycle" not in md
    assert "Ideas resolved" not in md
    # The core before/after block is still present.
    assert "Before → After" in md


# --- load_history: blank lines between entries are skipped (268->266) --------

def test_load_history_skips_blank_lines(tmp_path):
    log = Path(tmp_path) / HISTORY_REL
    log.parent.mkdir(parents=True, exist_ok=True)
    # Two valid entries separated by blank/whitespace-only lines; the loader
    # continues past them rather than appending or raising.
    log.write_text(
        '{"applied": 1}\n'
        '\n'
        '   \n'
        '{"applied": 2}\n',
        encoding="utf-8")
    history = load_history(str(tmp_path))
    assert history == [{"applied": 1}, {"applied": 2}]
