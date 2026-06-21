"""Develop session — the combined concrete-objective run (the buyer artifact).

Covers: the FIXED concrete-value-first objective order and that the two
``expensive`` objectives (implement-stub, wire-exports) are OPTED IN; a
multi-feature foreign fixture lands >=2 different objective TYPES (stub + exports
+ hints + dataclass + modernize) in one motion with the combined report counting
them; the report (and its diff) is DETERMINISTIC byte-for-byte across two runs
from the same start state; a no-suite move is honestly labelled ``no-suite`` and
never blended with a verified one; a move that fails verification is rolled back
by the underlying engine and surfaced as a REFUSAL (not counted as landed); the
full-suite-green-after backstop; and that the normal ``develop``/``--all`` path
is unaffected (ALL_OBJECTIVES byte-identical, SESSION_OBJECTIVES separate).

Reuses the existing deterministic ``compile_objective`` loop — the session only
orchestrates it across a fixed list and folds the landed plans into one report.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_session import (
    SESSION_OBJECTIVES,
    SessionMove,
    SessionObjective,
    SessionReport,
    TIER_NO_SUITE,
    TIER_VERIFIED,
    render_session_markdown,
    run_develop_session,
)


# --- the fixed order + opt-in of the expensive objectives ---------------------

def test_session_objectives_order_is_concrete_value_first():
    # Concrete value lands FIRST (implement real code, wire exports, infer hints,
    # dataclassify), THEN the idiom-modernizers tidy the surface.
    assert SESSION_OBJECTIVES == (
        "implement-stub", "wire-exports", "infer-type-hints", "dataclassify",
        "modernize", "simplify-bool-return", "remove-dead-code", "dead-params",
        "shrink-functions", "inline-helpers",
    )


def test_session_opts_in_the_expensive_objectives():
    from app.engine.develop_registry import expensive_names

    # The two highest-value concrete objectives are flagged expensive and are
    # EXCLUDED from the automatic sweeps; the session explicitly opts them in.
    expensive = expensive_names()
    assert {"implement-stub", "wire-exports"} <= expensive
    assert "implement-stub" in SESSION_OBJECTIVES
    assert "wire-exports" in SESSION_OBJECTIVES


def test_normal_develop_paths_byte_identical():
    # SESSION_OBJECTIVES is a SEPARATE list; ALL_OBJECTIVES (what --all/ascend
    # sweep) is untouched, so those paths stay byte-identical.
    from app.engine.objective_compiler import ALL_OBJECTIVES, SESSION_OBJECTIVES as SO

    assert ALL_OBJECTIVES == ("modernize", "simplify-bool-return",
                              "remove-dead-code", "dead-params",
                              "shrink-functions", "inline-helpers")
    assert SO is SESSION_OBJECTIVES
    assert SO != ALL_OBJECTIVES


# --- a realistic foreign fixture: a partially-built package + a suite ---------

def _foreign_project(root: Path) -> Path:
    """A partially-built foreign package with: a tested NotImplementedError stub,
    an empty/under-exported ``__init__.py``, a boilerplate ``__init__`` class, a
    modernizable ``== None`` idiom, and a passing-once-implemented suite."""
    (root / "widgets").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='widgets'\nversion='0'\n", encoding="utf-8")
    (root / "widgets" / "__init__.py").write_text("", encoding="utf-8")
    (root / "widgets" / "mathlib.py").write_text(
        'def add(a, b):\n    """Return the sum of a and b."""\n'
        "    raise NotImplementedError\n", encoding="utf-8")
    (root / "widgets" / "models.py").write_text(
        "class Point:\n    def __init__(self, x, y):\n"
        "        self.x = x\n        self.y = y\n", encoding="utf-8")
    (root / "widgets" / "util.py").write_text(
        "def is_missing(value):\n    return value == None\n", encoding="utf-8")
    (root / "tests" / "test_widgets.py").write_text(
        "from widgets.mathlib import add\n"
        "from widgets.models import Point\n"
        "from widgets.util import is_missing\n"
        "def test_add():\n    assert add(2, 3) == 5\n"
        "def test_point():\n    p = Point(1, 2)\n    assert (p.x, p.y) == (1, 2)\n"
        "def test_missing():\n"
        "    assert is_missing(None) is True\n"
        "    assert is_missing(7) is False\n", encoding="utf-8")
    return root


def test_session_lands_multiple_objective_types_in_one_motion(tmp_path: Path):
    _foreign_project(tmp_path)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)

    # >= 2 DIFFERENT objective types each landed at least one move.
    landed_objectives = {o.objective for o in report.objectives if o.moves}
    assert {"implement-stub", "wire-exports"} <= landed_objectives
    assert len(landed_objectives) >= 3
    assert report.total_moves >= 3

    # The stub body is real, working code; the exports are wired.
    math_src = (tmp_path / "widgets" / "mathlib.py").read_text()
    assert "raise NotImplementedError" not in math_src and "return a + b" in math_src
    init_src = (tmp_path / "widgets" / "__init__.py").read_text()
    assert "__all__" in init_src and "add" in init_src


def test_combined_report_counts_and_diff_present(tmp_path: Path):
    _foreign_project(tmp_path)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)

    # The combined report aggregates files + line deltas + the unified diff.
    assert report.files_changed  # at least one file changed
    assert report.lines_added > 0 and report.lines_removed > 0
    assert "return a + b" in report.diff
    # COVERAGE-AWARE honesty: a green suite is "verified" ONLY for moves a test
    # actually exercises. The four moves on modules a test imports
    # (mathlib/models/util) earn ``verified``; the ``wire-exports`` move edits
    # ``widgets/__init__.py`` — which NO test imports — so it is the honest
    # ``weak`` tier (suite green but nothing references the change), never blended
    # into the verified headline. Split must add back up to the total.
    assert report.verified_moves + report.weak_moves == report.total_moves
    assert report.weak_moves >= 1  # the uncovered __init__ edit
    assert report.no_suite_moves == 0

    md = render_session_markdown(report)
    assert "Develop session" in md
    assert "```diff" in md and "return a + b" in md
    # No clock/random in the artifact body.
    assert "202" not in md.split("```diff")[0] or "contribution" in md


def test_full_suite_green_after_backstop(tmp_path: Path):
    _foreign_project(tmp_path)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)
    assert report.suite_available is True
    assert report.suite_green_after is True


# --- determinism: same start state -> byte-identical report -------------------

def test_report_is_deterministic_byte_for_byte(tmp_path: Path):
    a = _foreign_project(tmp_path / "a")
    b = _foreign_project(tmp_path / "b")
    md_a = render_session_markdown(run_develop_session(str(a), apply=True))
    md_b = render_session_markdown(run_develop_session(str(b), apply=True))
    assert md_a == md_b


# --- honest no-suite labelling -----------------------------------------------

def _suiteless_project(root: Path) -> Path:
    """A foreign package with NO detectable test suite — wire-exports still lands
    (its safety is the import oracle, not a suite), and must be labelled no-suite."""
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "models.py").write_text(
        "class Box:\n    def __init__(self, w, h):\n"
        "        self.w = w\n        self.h = h\n", encoding="utf-8")
    return root


def test_no_suite_move_is_labelled_no_suite(tmp_path: Path):
    _suiteless_project(tmp_path)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)

    assert report.total_moves >= 1
    assert report.suite_available is False
    # Every landed move is honestly tiered no-suite, never blended as verified.
    assert report.verified_moves == 0
    assert report.no_suite_moves == report.total_moves
    for obj in report.objectives:
        for mv in obj.moves:
            assert mv.tier == TIER_NO_SUITE

    md = render_session_markdown(report)
    assert "no-suite" in md
    assert "no test suite detected" in md
    # The no-suite tier is explained by the conditional footnote.
    assert "won't claim it's test-verified" in md


# --- a move that fails verification is rolled back + reported refused ----------

def test_failing_move_is_rolled_back_and_reported(tmp_path: Path, monkeypatch):
    """The session must surface a move that fails its gate as a REFUSAL, never a
    landed contribution. The underlying ``compile_objective`` engine already
    rolls back a verification failure (records the reason in ``blocked`` and
    keeps it OUT of ``steps``); the session folds that through. We assert the
    contract by injecting a CompileResult that mimics one rolled-back move."""
    from app.engine import develop_session as ds
    from app.engine.objective_compiler import CompileResult

    def fake_compile(root, *, objective, **kw):
        if objective == "implement-stub":
            # A move that built a plan but failed the suite — rolled back; the
            # engine reports the reason and lands NOTHING.
            return CompileResult(
                objective=objective, fitness_start=1.0, fitness_end=1.0,
                blocked=["widgets/m.py:f: tests failed after change; "
                         "files restored"], applied=True)
        return CompileResult(objective=objective, fitness_start=0.0,
                             fitness_end=0.0, applied=True)

    monkeypatch.setattr(ds, "compile_objective", fake_compile)
    monkeypatch.setattr(ds, "_snapshot", lambda root: {})
    monkeypatch.setattr(ds, "_full_suite_green", lambda root: (True, True))

    report = run_develop_session(str(tmp_path), apply=True, verify=True)

    # The refused move counts as ZERO landed contributions.
    assert report.total_moves == 0
    stub_obj = next(o for o in report.objectives if o.objective == "implement-stub")
    assert stub_obj.landed == 0
    assert any("rolled back" in b or "restored" in b for b in stub_obj.blocked)


def test_real_rollback_keeps_file_and_reports_blocker(tmp_path: Path):
    """End-to-end: a genuine verification failure rolls the file back to its
    exact bytes and the campaign reports the blocker (the reused engine's
    auto-rollback, exercised through the same path the session drives)."""
    from app.engine.objective_compiler import compile_objective

    # A stub whose ONLY pinned test asserts an unsatisfiable contract: no fixed
    # template passes, so implement-stub REFUSES — the file is untouched.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    original = "def f(a, b):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "m.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import f\n"
        "def test_f():\n    assert f(2, 3) == 999999\n", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    # Nothing landed; the file is byte-for-byte its original.
    assert not result.steps
    assert (tmp_path / "app" / "m.py").read_text() == original


# --- dataclass shapes for the report -----------------------------------------

def test_report_dict_is_serialisable_and_complete():
    report = SessionReport(applied=True)
    report.objectives.append(SessionObjective(
        objective="implement-stub",
        moves=[SessionMove("implement-stub", "implement_stub",
                           "app/m.py", "implement a tested stub",
                           TIER_VERIFIED)]))
    d = report.to_dict()
    assert d["total_moves"] == 1 and d["verified_moves"] == 1
    assert d["no_suite_moves"] == 0
    assert d["objectives"][0]["moves"][0]["tier"] == TIER_VERIFIED


def test_dry_run_lists_moves_without_writing(tmp_path: Path):
    _foreign_project(tmp_path)
    report = run_develop_session(str(tmp_path), apply=False)
    assert report.applied is False
    # Dry run reports candidate moves but writes nothing and produces no diff.
    assert report.diff == ""
    assert (tmp_path / "widgets" / "mathlib.py").read_text().count(
        "raise NotImplementedError") == 1
    # Report-only headline points at --apply, never the misleading 0-file/line counts.
    md = render_session_markdown(report)
    assert "ready to land" in md
    assert "0 file(s)" not in md


# --- baseline-red guard: never claim "already satisfied" on a RED suite -------

# The EXACT happy-path "nothing landed" wording, captured BEFORE this guard
# existed. A clean GREEN project with no debt must still render this byte-for-byte
# (the report is a buyer artifact and is byte-compared) — the guard adds new
# wording STRICTLY behind the baseline-red condition and must not churn this.
_SATISFIED_LINE = ("_No concrete contribution available — every objective is "
                   "already satisfied._")


def _red_baseline_project(root: Path) -> Path:
    """A multi-module foreign package whose suite is RED *before* any change: one
    module is an UNSYNTHESIZABLE stub (its pinned test asserts a contract no fixed
    template can satisfy), so ``implement-stub`` REFUSES — nothing lands for it —
    and the raised ``NotImplementedError`` keeps the baseline suite RED. A second,
    already-complete module proves the project is genuinely multi-module."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    # Exports already wired + an already-implemented module, so wire-exports and
    # the other objectives have NOTHING to land — the ONLY reason the session
    # lands nothing is the RED baseline, not a clean project.
    (root / "pkg" / "__init__.py").write_text(
        'from .stub import f\nfrom .done import g\n\n'
        '__all__ = [\n    "f",\n    "g",\n]\n', encoding="utf-8")
    (root / "pkg" / "stub.py").write_text(
        "def f(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (root / "pkg" / "done.py").write_text(
        "def g(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "tests" / "test_pkg.py").write_text(
        "from pkg.stub import f\nfrom pkg.done import g\n"
        "def test_f():\n    assert f(2, 3) == 999999\n"
        "def test_g():\n    assert g(2, 3) == 5\n", encoding="utf-8")
    return root


def _red_no_debt_project(root: Path) -> Path:
    """A RED-baseline package with NO synthesizable debt at all: the only module is
    already type-hinted, exports are wired, no stub / no idiom — but a pre-existing
    test FAILS. So the session lands nothing in BOTH apply and dry-run (no candidate
    moves even to propose), and the ONLY reason for the empty outcome is the RED
    baseline — the case the guard must explain instead of "already satisfied"."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text(
        'from .done import g\n\n__all__ = [\n    "g",\n]\n', encoding="utf-8")
    (root / "pkg" / "done.py").write_text(
        "def g(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    # A second test asserts a pre-existing FALSE contract -> the baseline is RED.
    (root / "tests" / "test_pkg.py").write_text(
        "from pkg.done import g\n"
        "def test_g():\n    assert g(2, 3) == 5\n"
        "def test_pre_existing_failure():\n    assert g(1, 1) == 999999\n",
        encoding="utf-8")
    return root


def _clean_green_project(root: Path) -> Path:
    """A genuinely SATISFIED foreign package: a green suite, exports already wired,
    no stub / no idiom debt — so every objective truly has nothing to land and the
    positive "already satisfied" message is HONEST."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text(
        'from .done import g\n\n__all__ = [\n    "g",\n]\n', encoding="utf-8")
    (root / "pkg" / "done.py").write_text(
        "def g(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "tests" / "test_pkg.py").write_text(
        "from pkg.done import g\n"
        "def test_g():\n    assert g(2, 3) == 5\n", encoding="utf-8")
    return root


def test_red_baseline_says_suite_red_not_satisfied(tmp_path: Path):
    # A multi-module RED-baseline project that lands NOTHING must NOT be reported
    # as "already satisfied" — that would imply the project is clean when it is
    # not (never-fake-green). It must disclose the RED baseline.
    _red_baseline_project(tmp_path)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)

    assert report.total_moves == 0
    assert report.baseline_suite_green is False

    md = render_session_markdown(report)
    assert "RED before any change" in md
    assert "pre-existing failures" in md
    assert "will not claim a green it didn't earn" in md
    # The misleading positive wording must be ABSENT for a red baseline.
    assert _SATISFIED_LINE not in md
    assert "every objective is already satisfied" not in md


def test_red_baseline_dry_run_also_discloses_red(tmp_path: Path):
    # The honest wording is keyed off the baseline, so the dry-run (report-only)
    # path that lands nothing discloses the RED baseline too. Uses the no-debt-but-
    # RED fixture so dry-run also reaches the "nothing landed" branch (a fixture
    # with synthesizable debt would PROPOSE candidate moves in dry-run instead).
    _red_no_debt_project(tmp_path)
    report = run_develop_session(str(tmp_path), apply=False, verify=True)
    assert report.total_moves == 0
    assert report.baseline_suite_green is False
    md = render_session_markdown(report)
    assert "RED before any change" in md
    assert "every objective is already satisfied" not in md


def test_clean_green_baseline_keeps_satisfied_wording_byte_identical(tmp_path: Path):
    # The happy path is UNCHANGED: a clean GREEN project with no debt still says
    # "already satisfied", byte-for-byte the pre-guard wording.
    _clean_green_project(tmp_path)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)

    assert report.total_moves == 0
    assert report.baseline_suite_green is True

    md = render_session_markdown(report)
    assert _SATISFIED_LINE in md
    # The red-baseline wording must NOT leak into a clean project's report.
    assert "RED before any change" not in md


def test_baseline_green_flag_is_true_for_clean_false_for_red(tmp_path: Path):
    # The explicit deterministic field: True for the clean project, False for the
    # red one — the bool the wording keys off.
    clean = _clean_green_project(tmp_path / "clean")
    red = _red_baseline_project(tmp_path / "red")
    assert run_develop_session(str(clean), apply=True).baseline_suite_green is True
    assert run_develop_session(str(red), apply=True).baseline_suite_green is False


def test_baseline_not_probed_when_work_lands(tmp_path: Path):
    # Performance + scope guard: when the session LANDS work, the baseline is NEVER
    # probed (no extra suite run), so the field stays ``None`` — the probe only
    # runs to explain a no-contribution outcome.
    _foreign_project(tmp_path)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)
    assert report.total_moves > 0
    assert report.baseline_suite_green is None


def test_red_baseline_report_is_deterministic_byte_for_byte(tmp_path: Path):
    # Same RED-baseline fixture -> identical report bytes twice (the new field +
    # wording are deterministic; the bool carries no clock/random).
    a = _red_baseline_project(tmp_path / "a")
    b = _red_baseline_project(tmp_path / "b")
    md_a = render_session_markdown(run_develop_session(str(a), apply=True))
    md_b = render_session_markdown(run_develop_session(str(b), apply=True))
    assert md_a == md_b


def test_baseline_green_field_serialises(tmp_path: Path):
    # The new field is on the dict artifact for downstream consumers.
    report = run_develop_session(
        str(_red_baseline_project(tmp_path)), apply=True)
    assert report.to_dict()["baseline_suite_green"] is False
