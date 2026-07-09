"""FIX: dry-run (preview) moves must NEVER be labelled ``no-suite``.

The 2026-07-08 adversarial audit finding: ``_fill_dry_run`` stamps every
projected step ``verified=False``; ``develop_session._tier_for`` mapped
``verified=False`` -> ``TIER_NO_SUITE``; the renderers then printed
"⚠️ no-suite" with a footnote claiming the move was "applied but no test suite
exists to verify this code". On a PREVIEW nothing was applied and the project
may well HAVE a suite — both claims are false (the real "48 moves, ALL
no-suite" confusion on pyparsing).

The fix keys a DISTINCT preview labelling off the result/report's ``applied``
flag: a dry-run move reads "preview — not applied yet; will be test-verified
on --apply", never "no-suite". Applied-mode labelling is byte-identical.

Red-first: ``test_dry_run_compile_render_reads_preview_not_no_suite``,
``test_dry_run_breakdown_never_counts_no_suite``,
``test_session_dry_run_moves_are_preview_tier`` and
``test_session_dry_run_render_never_claims_no_suite`` all FAIL on the pre-fix
code (which rendered the no-suite tag/footnote for dry runs). The applied-mode
pins cannot be red-first (they assert byte-identity with today) — they pin the
old behaviour end-to-end so a regression cannot pass silently.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_session import (
    TIER_NO_SUITE,
    TIER_PREVIEW,
    TIER_VERIFIED,
    TIER_WEAK,
    SessionReport,
    render_session_markdown,
    run_develop_session,
)
from app.engine.objective_compiler import (
    CompileStep,
    compile_objective,
    render_compile_markdown,
)

_PREVIEW_PHRASE = "preview — not applied yet; will be test-verified on --apply"


def _suited_debt_project(root: Path) -> Path:
    """A project WITH a real pytest suite and one droppable dead parameter —
    the exact shape the audit's mislabel hit: a preview on it claimed both
    "applied" and "no test suite exists", and both claims were false."""
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "m.py").write_text(
        "__all__ = ['use']\n\n\n"
        "def render(text, color=None, width=80):\n"
        "    return text[:width]\n\n\n"
        "def use():\n"
        "    return render('hi', width=10)\n", encoding="utf-8")
    (root / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_import():\n    assert app.m is not None\n",
        encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return root


def _suiteless_debt_project(root: Path) -> Path:
    """The same droppable debt with NO detectable test suite at all (the
    no-suite edge — no tests/ and no pyproject, so no test command detects)."""
    (root / "app").mkdir(parents=True)
    (root / "app" / "m.py").write_text(
        "__all__ = ['use']\n\n\n"
        "def render(text, color=None, width=80):\n"
        "    return text[:width]\n\n\n"
        "def use():\n"
        "    return render('hi', width=10)\n", encoding="utf-8")
    return root


# --- the compile renderer: dry run reads preview, never no-suite ---------------

def test_dry_run_compile_render_reads_preview_not_no_suite(tmp_path: Path):
    # RED-FIRST: pre-fix this rendered " ⚠️ no-suite — applied, nothing verified
    # it" for every projected step — on a project that HAS a suite and where
    # nothing was applied.
    _suited_debt_project(tmp_path)
    r = compile_objective(str(tmp_path), objective="dead-params", apply=False)
    assert r.steps and not r.applied
    md = render_compile_markdown(r)
    assert "no-suite" not in md
    assert "applied, nothing verified it" not in md
    assert _PREVIEW_PHRASE in md


def test_dry_run_breakdown_never_counts_no_suite(tmp_path: Path):
    # RED-FIRST: pre-fix the headline read "would apply 1 move(s): 0 verified,
    # 1 no-suite" — the "48 moves, ALL no-suite" confusion in miniature.
    _suited_debt_project(tmp_path)
    r = compile_objective(str(tmp_path), objective="dead-params", apply=False)
    md = render_compile_markdown(r)
    assert "0 verified" not in md
    assert "1 no-suite" not in md
    assert "would apply 1 move(s) — preview" in md


def test_dry_run_on_suiteless_project_is_also_preview(tmp_path: Path):
    # Edge: the preview label keys off ``applied``, not suite presence — a
    # suite-less DRY RUN still applied nothing, so it must read preview too.
    _suiteless_debt_project(tmp_path)
    r = compile_objective(str(tmp_path), objective="dead-params", apply=False)
    assert r.steps
    md = render_compile_markdown(r)
    assert "no-suite" not in md
    assert _PREVIEW_PHRASE in md


def test_applied_no_suite_tag_is_byte_identical(tmp_path: Path):
    # BYTE-IDENTITY PIN (cannot be red-first): a genuinely suite-less APPLY
    # keeps the exact honest no-suite wording — the preview branch must never
    # leak into applied mode.
    _suiteless_debt_project(tmp_path)
    r = compile_objective(str(tmp_path), objective="dead-params",
                          apply=True, verify=True)
    assert r.steps and r.applied
    md = render_compile_markdown(r)
    assert "no-suite — applied, nothing verified it" in md
    assert _PREVIEW_PHRASE not in md


def test_compile_tier_tag_default_is_applied_mode():
    # BYTE-IDENTITY PIN: the one-arg call (the existing contract) still yields
    # the applied-mode tags, so every applied render is unchanged.
    from app.engine.objective_compiler import _compile_tier_tag

    plain = CompileStep(operator="o", target="m:f", description="d",
                        fitness_before=1.0, fitness_after=0.0)
    assert _compile_tier_tag(plain) == " ⚠️ no-suite — applied, nothing verified it"
    covered = CompileStep(operator="o", target="m:f", description="d",
                          fitness_before=1.0, fitness_after=0.0,
                          verified=True, coverage="function")
    assert _compile_tier_tag(covered) == " ✅ tests pass (covered)"
    # And the preview branch is reachable ONLY by opting out of applied mode.
    assert _PREVIEW_PHRASE in _compile_tier_tag(plain, applied=False)


# --- the develop session: dry-run moves carry the distinct preview tier --------

def test_session_dry_run_moves_are_preview_tier(tmp_path: Path):
    # RED-FIRST: pre-fix every dry-run move was tiered TIER_NO_SUITE and counted
    # in ``no_suite_moves`` — on a project WITH a suite.
    _suited_debt_project(tmp_path)
    report = run_develop_session(str(tmp_path), apply=False,
                                 objectives=("dead-params",))
    assert report.total_moves >= 1
    tiers = [m.tier for o in report.objectives for m in o.moves]
    assert all(t == TIER_PREVIEW for t in tiers)
    assert report.no_suite_moves == 0
    assert report.preview_moves == report.total_moves
    # The additive dict disclosure: present on a preview, absent otherwise.
    d = report.to_dict()
    assert d["preview_moves"] == report.preview_moves
    assert d["no_suite_moves"] == 0
    assert d["objectives"][0]["moves"][0]["tier"] == TIER_PREVIEW


def test_session_dry_run_render_never_claims_no_suite(tmp_path: Path):
    # RED-FIRST: pre-fix the per-move tag read "⚠️ no-suite" and the footnote
    # claimed "applied but no test suite exists to verify this code" — both
    # false on a preview of a suite-carrying project.
    _suited_debt_project(tmp_path)
    report = run_develop_session(str(tmp_path), apply=False,
                                 objectives=("dead-params",))
    md = render_session_markdown(report)
    assert "no-suite" not in md
    assert "no test suite exists to verify this code" not in md
    assert _PREVIEW_PHRASE in md
    # The preview footnote explains the tier honestly.
    assert "`preview`" in md and "--apply" in md


def test_session_applied_tiers_unchanged(tmp_path: Path):
    # BYTE-IDENTITY PIN (cannot be red-first): an APPLIED suite-less session
    # still tiers no-suite with the existing footnote — the preview tier exists
    # only for report-only runs.
    _suiteless_debt_project(tmp_path)
    report = run_develop_session(str(tmp_path), apply=True, verify=True,
                                 objectives=("dead-params",))
    assert report.total_moves >= 1
    assert all(m.tier == TIER_NO_SUITE
               for o in report.objectives for m in o.moves)
    assert report.preview_moves == 0
    assert "preview_moves" not in report.to_dict()  # additive: absent when 0
    md = render_session_markdown(report)
    assert "no-suite" in md
    assert "no test suite exists to verify this code" in md
    assert _PREVIEW_PHRASE not in md


# --- constants + empty edges ---------------------------------------------------

def test_tier_preview_constant_is_distinct():
    # Contract pin (cannot be red-first — the constant is new): the preview tier
    # is its own vocabulary word, never aliasing an applied tier.
    assert TIER_PREVIEW == "preview"
    assert TIER_PREVIEW not in {TIER_VERIFIED, TIER_WEAK, TIER_NO_SUITE}


def test_empty_report_has_no_preview_moves():
    # Empty edge: a report with no moves counts zero previews and renders no
    # preview footnote (present-only-when-present).
    report = SessionReport(applied=False)
    assert report.preview_moves == 0
    assert "preview_moves" not in report.to_dict()
    assert "`preview`" not in render_session_markdown(report)
