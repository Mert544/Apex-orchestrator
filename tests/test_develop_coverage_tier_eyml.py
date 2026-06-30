"""Coverage-aware verification tier on the develop / develop-session path.

The hardened ``maintain`` path already grades a green suite by what it actually
EXERCISED (``assess_strength``): a green run on a module NO test references proves
nothing about the change. The develop / ``develop session`` apply path used to
label EVERY landed move "verified" the moment the unrelated suite ran green — the
exact smoke-import blend ``maintain`` was hardened against, re-opened on the buyer
artifact. This pins the port of that coverage gate to the develop path:

  * a move on a module a test GENUINELY exercises (imports / names the change)
    still reports ``verified`` (never over-demoted);
  * a move on a module NO test imports, suite green, reports a DISTINCT
    coverage-aware NON-verified tier (``weak``) — never counted in the "verified"
    headline (honest, never blended with a real verified move);
  * the session headline "N verified" equals ONLY the genuinely test-covered
    moves; ``render_compile_markdown`` splits landed / verified / weak / no-suite;
  * ``--no-verify --apply`` makes NO "full suite GREEN" claim — nothing ran — and
    renders a distinct "backstop not run — moves UNVERIFIED" line;
  * determinism preserved; the maintain path is untouched.

Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_session import (
    TIER_NO_SUITE,
    TIER_VERIFIED,
    TIER_WEAK,
    render_session_markdown,
    run_develop_session,
)
from app.engine.objective_compiler import (
    compile_objective,
    render_compile_markdown,
)


# --- fixtures -----------------------------------------------------------------

# A dead-parameter the dead-params objective will drop, in a module the suite
# either DOES or does NOT import — the single knob that flips coverage. ``render``
# is non-public (empty __all__) so the public-API rail in ``_dead_param_moves``
# permits the drop; the explicit ``from app.m import render`` is unaffected.
_DEAD = (
    "__all__ = []\n"
    "def render(text, color=None, width=80):\n"
    "    return text[:width]\n"
)


def _covered_project(root: Path) -> Path:
    """``app/m.py`` carries a dead param AND a test imports it — a green suite
    genuinely exercises the change."""
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    (root / "app" / "m.py").write_text(_DEAD, encoding="utf-8")
    (root / "tests" / "test_m.py").write_text(
        "from app.m import render\n"
        "def test_render():\n    assert render('hi', width=2) == 'hi'\n",
        encoding="utf-8")
    return root


def _uncovered_project(root: Path) -> Path:
    """``app/m.py`` carries the SAME dead param, but the (green) suite imports a
    DIFFERENT module and never references ``app.m`` — a green run proves nothing
    about the change."""
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    (root / "app" / "m.py").write_text(_DEAD, encoding="utf-8")
    (root / "app" / "other.py").write_text(
        "def ping():\n    return 'pong'\n", encoding="utf-8")
    (root / "tests" / "test_other.py").write_text(
        "from app.other import ping\n"
        "def test_ping():\n    assert ping() == 'pong'\n",
        encoding="utf-8")
    return root


def _suiteless_project(root: Path) -> Path:
    """``app/m.py`` with the dead param but NO detectable test suite at all (no
    ``pyproject``/``tests`` -> ``RunTestsSkill`` finds no command to run)."""
    (root / "app").mkdir(parents=True)
    (root / "app" / "m.py").write_text(_DEAD, encoding="utf-8")
    return root


# --- the objective_compiler step tier ----------------------------------------

def test_covered_move_is_verified(tmp_path: Path):
    _covered_project(tmp_path)
    r = compile_objective(str(tmp_path), objective="dead-params",
                          apply=True, verify=True)
    assert r.steps
    step = r.steps[0]
    # A test imports the changed module -> the green suite genuinely vouches.
    assert step.verified is True
    assert step.coverage in ("function", "module")
    assert step.coverage_verified is True


def test_uncovered_green_move_is_not_verified(tmp_path: Path):
    _uncovered_project(tmp_path)
    r = compile_objective(str(tmp_path), objective="dead-params",
                          apply=True, verify=True)
    assert r.steps
    step = r.steps[0]
    # The suite ran GREEN (raw bool True) but no test references app.m, so the
    # change is NOT coverage-verified — the never-fake-green tier.
    assert step.verified is True          # raw suite-green bool
    assert step.coverage == "none"         # nothing referenced the change
    assert step.coverage_verified is False  # the honest verdict


def test_render_compile_markdown_splits_verified_from_weak(tmp_path: Path):
    _uncovered_project(tmp_path)
    r = compile_objective(str(tmp_path), objective="dead-params",
                          apply=True, verify=True)
    md = render_compile_markdown(r)
    # The headline counts the uncovered-green move as WEAK, not verified.
    assert "0 verified" in md
    assert "weak" in md
    # Per-move line is NOT a green "verified" tick.
    assert "✅ tests pass (covered)" not in md
    assert "no test covers this move" in md


def test_covered_render_counts_verified(tmp_path: Path):
    _covered_project(tmp_path)
    r = compile_objective(str(tmp_path), objective="dead-params",
                          apply=True, verify=True)
    md = render_compile_markdown(r)
    assert "1 verified" in md
    assert "✅ tests pass (covered)" in md


# --- the develop-session headline --------------------------------------------

def test_session_headline_counts_only_covered_moves(tmp_path: Path):
    _uncovered_project(tmp_path)
    report = run_develop_session(
        str(tmp_path), apply=True, verify=True,
        objectives=("dead-params",))
    assert report.total_moves >= 1
    # The uncovered-green move is tiered weak and is NOT in the verified headline.
    assert report.verified_moves == 0
    assert report.weak_moves >= 1
    assert report.no_suite_moves == 0
    assert all(m.tier == TIER_WEAK for o in report.objectives for m in o.moves)

    md = render_session_markdown(report)
    assert "0 verified" in md
    assert "weak" in md


def test_session_headline_counts_covered_move_verified(tmp_path: Path):
    _covered_project(tmp_path)
    report = run_develop_session(
        str(tmp_path), apply=True, verify=True,
        objectives=("dead-params",))
    assert report.verified_moves >= 1
    assert report.weak_moves == 0
    assert all(m.tier == TIER_VERIFIED for o in report.objectives for m in o.moves)


def test_session_no_suite_move_is_no_suite_tier(tmp_path: Path):
    _suiteless_project(tmp_path)
    report = run_develop_session(
        str(tmp_path), apply=True, verify=True,
        objectives=("dead-params",))
    assert report.total_moves >= 1
    assert report.verified_moves == 0
    assert report.weak_moves == 0
    assert all(m.tier == TIER_NO_SUITE for o in report.objectives for m in o.moves)


# --- the --no-verify fake-green fix -------------------------------------------

def test_no_verify_apply_makes_no_green_claim(tmp_path: Path):
    _covered_project(tmp_path)
    report = run_develop_session(
        str(tmp_path), apply=True, verify=False,
        objectives=("dead-params",))
    # The backstop did NOT run under --no-verify.
    assert report.backstop_ran is False
    md = render_session_markdown(report)
    # No "full suite GREEN" claim is made when nothing ran.
    assert "full suite GREEN" not in md
    assert "backstop not run" in md
    assert "UNVERIFIED" in md
    # And no move is counted as verified.
    assert report.verified_moves == 0


def test_verify_apply_still_makes_backstop_claim(tmp_path: Path):
    _covered_project(tmp_path)
    report = run_develop_session(
        str(tmp_path), apply=True, verify=True,
        objectives=("dead-params",))
    assert report.backstop_ran is True
    md = render_session_markdown(report)
    assert "full suite GREEN" in md
    assert "backstop not run" not in md


# --- determinism --------------------------------------------------------------

def test_coverage_tier_is_deterministic(tmp_path: Path):
    a = _uncovered_project(tmp_path / "a")
    b = _uncovered_project(tmp_path / "b")
    md_a = render_session_markdown(run_develop_session(
        str(a), apply=True, verify=True, objectives=("dead-params",)))
    md_b = render_session_markdown(run_develop_session(
        str(b), apply=True, verify=True, objectives=("dead-params",)))
    # Same shape (paths differ only in the diff headers, which we strip here):
    assert md_a.split("```diff")[0] == md_b.split("```diff")[0]
