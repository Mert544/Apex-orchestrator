"""Low-support ``candidate`` hypotheses must be SHOWN, not silently dropped.

A red-team verification found that suppressing over-claiming tautologies had
relocated the dishonesty: the engine computed a ``candidate`` verdict for a clean
rule on a thin (2-4 module) population, but the report renderer's ``_VERDICTS``
listed only ``confirmed``/``weak``/``refuted`` — so candidates were dropped and a
buyer saw "Nothing notable" while six honest low-support leads existed. A hidden
under-report is no more honest than an over-claim. This pins that ``candidate`` is
rendered. Deterministic; stdlib-only.
"""

from __future__ import annotations

from pathlib import Path

from app.engine import intelligence_report as ir


def test_candidate_is_in_the_rendered_verdicts():
    assert "candidate" in ir._VERDICTS
    # Order: confirmed first (strongest), candidate before weak/refuted.
    v = ir._VERDICTS
    assert v.index("confirmed") < v.index("candidate") < v.index("weak")


def test_candidate_hypotheses_are_rendered_not_dropped(tmp_path: Path):
    from app.tools.project_profile import ProjectProfiler

    # Three modules each with a real security finding (eval) but no test → the
    # empirical "security ⇒ untested" association holds at support 3 → candidate.
    for i in range(3):
        (tmp_path / f"m{i}.py").write_text("def run(x):\n    return eval(x)\n",
                                           encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    report = ir.build_intelligence_report(profile, str(tmp_path))
    # The candidate lead is surfaced (NOT hidden as "nothing notable").
    assert "candidate" in report.lower()
