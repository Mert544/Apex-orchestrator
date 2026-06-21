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
    # Scope guard: when an APPLY session LANDS work, the report FIELD stays ``None``
    # — the cause of an empty contribution list is moot when work landed, so the
    # honest "baseline RED" disclosure (and its field) is reserved for the no-work
    # case. (On apply the baseline is probed ONCE up front to pick the gate scope,
    # but that drives gating, not this disclosure field.)
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


# --- the cross-module apply deadlock: tidy work lands on a RED baseline --------
#
# The field-test blocker: a realistic "finish my project" repo whose suite is RED
# at baseline (an unfinished stub in ONE module) dry-runs N tidy contributions
# READY but lands only the stub work, because the TIDY objectives gated their
# CORRECT change against the FULL red suite and every change was rolled back
# (``tests failed after rename; all files restored``) for an UNRELATED reason.
# The fix probes the baseline ONCE up front; on a RED baseline it forces
# impact-scoped gating for ALL objectives, so a tidy change is gated only against
# the tests it actually impacts (which pass) — never the unrelated pre-existing
# failure. The full-suite backstop is still the commit-time guard, so the report
# still HONESTLY discloses the suite is RED after (never-fake-green).


def _red_baseline_with_tidy_work(root: Path) -> Path:
    """A multi-module foreign package whose suite is RED at baseline (an
    UNSYNTHESIZABLE stub in ``pkg/stub.py`` keeps it red) but with REAL tidy work
    in OTHER modules, each covered by a PASSING test:

      * ``pkg/__init__.py`` — empty / under-exported  -> wire-exports
      * ``pkg/models.py``   — a pure data-holder class -> dataclassify + hints
      * ``pkg/calc.py``     — a function w/ inferable hints (covered, passing)

    The tidy modules are imported by ``tests/test_tidy.py`` (which PASSES), so
    impact-scoped gating runs those passing tests and the tidy change genuinely
    lands. ``pkg/stub.py`` is imported only by ``tests/test_stub.py`` (which
    FAILS on the unsatisfiable contract), so the baseline stays RED and
    implement-stub REFUSES it."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "stub.py").write_text(
        "def f(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (root / "pkg" / "calc.py").write_text(
        "def double(n):\n    return n + n\n", encoding="utf-8")
    (root / "pkg" / "models.py").write_text(
        "class Point:\n    def __init__(self, x, y):\n"
        "        self.x = x\n        self.y = y\n", encoding="utf-8")
    # The stub's pinned test asserts a contract no fixed template satisfies -> the
    # baseline suite is RED for this UNRELATED reason.
    (root / "tests" / "test_stub.py").write_text(
        "from pkg.stub import f\n"
        "def test_f():\n    assert f(2, 3) == 999999\n", encoding="utf-8")
    # The tidy modules (and the package itself, for wire-exports) are imported by
    # a PASSING test, so impact-scoped gating exercises them and they land.
    (root / "tests" / "test_tidy.py").write_text(
        "from pkg.calc import double\nfrom pkg.models import Point\nimport pkg\n"
        "def test_double():\n    assert double(4) == 8\n"
        "def test_point():\n    p = Point(1, 2)\n    assert (p.x, p.y) == (1, 2)\n",
        encoding="utf-8")
    return root


def test_red_baseline_lands_tidy_work_despite_unrelated_red_suite(tmp_path: Path):
    # The blocker fix, end-to-end: WITHOUT --fast/scope_verify, the tidy objectives
    # now LAND on a RED baseline instead of being vetoed by the unrelated red suite.
    _red_baseline_with_tidy_work(tmp_path)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)

    landed = {o.objective for o in report.objectives if o.moves}
    # The tidy contributions that the field test saw rolled back now land.
    assert "wire-exports" in landed
    assert "infer-type-hints" in landed
    assert "dataclassify" in landed
    # More than the ~1 the blocker stranded at: the report shows >1 contribution.
    assert report.total_moves > 1

    # The exports are wired and the data-holder became a dataclass — REAL diffs.
    init_src = (tmp_path / "pkg" / "__init__.py").read_text()
    assert "__all__" in init_src
    models_src = (tmp_path / "pkg" / "models.py").read_text()
    assert "@dataclass" in models_src or "dataclass" in models_src

    # Never-fake-green: the unsynthesizable stub is UNTOUCHED, still raising, so
    # the full-suite backstop honestly reports the suite is RED after the session.
    stub_src = (tmp_path / "pkg" / "stub.py").read_text()
    assert "raise NotImplementedError" in stub_src
    assert report.suite_available is True
    assert report.suite_green_after is False
    md = render_session_markdown(report)
    assert "full suite RED after the session" in md


def test_red_baseline_lands_nothing_without_the_fix(tmp_path: Path):
    # Proves the blocker existed: with the OLD full-suite gating (scope_verify
    # False, as the session forwarded on a red baseline before the fix), every
    # tidy change is vetoed by the unrelated red suite — ZERO land.
    #
    # NOTE: wire-exports is intentionally EXCLUDED here — it now carries its own
    # ``scope_verify=True`` spec flag (the red-baseline value-leak fix), so
    # ``effective_scope = scope_verify or spec.scope_verify`` keeps it impact-scoped
    # even when the caller passes ``scope_verify=False``; it correctly lands. The
    # session-level forcing this test pins is still demonstrated by the objectives
    # WITHOUT a spec flag.
    from app.engine.objective_compiler import compile_objective

    _red_baseline_with_tidy_work(tmp_path)
    landed = 0
    for obj in ("infer-type-hints", "dataclassify"):
        r = compile_objective(str(tmp_path), objective=obj, apply=True,
                              verify=True, scope_verify=False)
        landed += len(r.steps)
    assert landed == 0


def _spy_session(monkeypatch, root, **kw):
    """Run a session recording the ``scope_verify`` each objective received."""
    from app.engine import develop_session as ds
    from app.engine.objective_compiler import compile_objective as real

    seen: list[bool] = []

    def spy(root_, *, objective, scope_verify=False, **kw_):
        seen.append(scope_verify)
        return real(root_, objective=objective, scope_verify=scope_verify, **kw_)

    monkeypatch.setattr(ds, "compile_objective", spy)
    report = run_develop_session(str(root), **kw)
    return report, seen


def test_red_baseline_forces_impact_scoped_gating(tmp_path: Path, monkeypatch):
    # On a RED baseline the up-front probe forces scope_verify=True for EVERY
    # objective (impact-scoped gating), even though the buyer did NOT pass --fast.
    _red_baseline_with_tidy_work(tmp_path)
    _report, seen = _spy_session(monkeypatch, tmp_path, apply=True, verify=True)
    assert seen and all(s is True for s in seen)


def test_green_baseline_keeps_full_suite_gating_unchanged(tmp_path: Path, monkeypatch):
    # The happy path is UNCHANGED: on a GREEN baseline the forwarded scope_verify
    # equals the caller's (False here) — full-suite gating, exactly as before. The
    # fix never churns the green path.
    _green_baseline_with_tidy_work(tmp_path)
    report, seen = _spy_session(monkeypatch, tmp_path, apply=True, verify=True)
    assert seen and all(s is False for s in seen)
    # And it still lands the tidy work (gated against a green full suite).
    assert report.total_moves >= 1
    assert report.suite_green_after is True


def _green_baseline_with_tidy_work(root: Path) -> Path:
    """A GREEN-at-baseline foreign package WITH real tidy work: a data-holder class
    + an unwired ``__init__``, all covered by a PASSING suite. The session lands the
    tidy work via the unchanged full-suite gate (the green happy path)."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "models.py").write_text(
        "class Point:\n    def __init__(self, x, y):\n"
        "        self.x = x\n        self.y = y\n", encoding="utf-8")
    (root / "tests" / "test_tidy.py").write_text(
        "from pkg.models import Point\nimport pkg\n"
        "def test_point():\n    p = Point(1, 2)\n    assert (p.x, p.y) == (1, 2)\n",
        encoding="utf-8")
    return root


def test_baseline_probed_at_most_once_on_apply(tmp_path: Path, monkeypatch):
    # The up-front probe drives gating AND (when nothing lands) the disclosure, so
    # the full baseline suite is run AT MOST ONCE per apply session — no regression
    # to two full-suite probes.
    from app.engine import develop_session as ds

    _red_baseline_with_tidy_work(tmp_path)
    calls = {"n": 0}
    real = ds._baseline_suite_green

    def counting(root):
        calls["n"] += 1
        return real(root)

    monkeypatch.setattr(ds, "_baseline_suite_green", counting)
    run_develop_session(str(tmp_path), apply=True, verify=True)
    assert calls["n"] == 1


def test_no_baseline_probe_when_verify_off(tmp_path: Path, monkeypatch):
    # Under --no-verify nothing is gated and no backstop runs, so the baseline is
    # NEVER probed (no full-suite run at all) and the field stays None.
    from app.engine import develop_session as ds

    _red_baseline_with_tidy_work(tmp_path)
    calls = {"n": 0}

    def boom(root):
        calls["n"] += 1
        return True

    monkeypatch.setattr(ds, "_baseline_suite_green", boom)
    report = run_develop_session(str(tmp_path), apply=True, verify=False)
    assert calls["n"] == 0
    assert report.baseline_suite_green is None


def test_red_baseline_tidy_session_is_deterministic(tmp_path: Path):
    # Same RED-baseline-with-tidy-work fixture -> identical report AND identical
    # landed files across two independent runs (no clock/random; one cached probe).
    a = _red_baseline_with_tidy_work(tmp_path / "a")
    b = _red_baseline_with_tidy_work(tmp_path / "b")
    ra = run_develop_session(str(a), apply=True)
    rb = run_develop_session(str(b), apply=True)
    assert render_session_markdown(ra) == render_session_markdown(rb)
    for rel in ("pkg/__init__.py", "pkg/models.py", "pkg/calc.py", "pkg/stub.py"):
        assert (a / rel).read_text() == (b / rel).read_text()
    assert ra.total_moves == rb.total_moves and ra.total_moves > 1


# --- the auto-rollback MOAT fix: a transitive regression on a RED baseline ----
#
# THE VIOLATION (verified end-to-end by a red-team): on a RED baseline the session
# forces impact-SCOPED gating for every objective (for speed — so the unrelated
# pre-existing failure can't veto a correct tidy change). That scoping is BLIND to
# a previously-GREEN test reachable only TRANSITIVELY (outside the impacted scope).
# A behaviour-CHANGING transform — ``modernize``'s ``x == None`` -> ``x is None``,
# which DIFFERS when an operand's class overrides ``__eq__`` — can break such a
# test, and the change LANDED and was NEVER rolled back: the post-session
# full-suite backstop only DISCLOSED (suite_green_after=False), and on a red
# baseline a newly-introduced failure was indistinguishable from the pre-existing
# one and silently kept.
#
# THE FIX (sound for ALL transforms): capture the baseline's failing-NODE set up
# front, rerun the suite once after the session, and if ANY node that was GREEN at
# baseline is now RED, ROLL THE WHOLE SESSION BACK to its pre-session bytes.


def _transitive_regression_project(root: Path) -> Path:
    """A RED-baseline project where ``modernize`` breaks a previously-GREEN test
    reachable ONLY transitively (outside the move's impacted scope).

    Layout:
      * ``pkg/sentinel.py`` — a ``Missing`` sentinel whose ``__eq__`` treats
        ``== None`` as True (so ``x == None`` and ``x is None`` genuinely DIFFER —
        the exact behaviour-change ``modernize``'s ``==None``->``is None`` makes).
      * ``pkg/check.py`` — ``def is_blank(value): return value == None`` — the
        modernizable idiom. Its OWN test (``test_check.py``, in scope) passes both
        BEFORE and AFTER the rewrite (``None``/``7`` cases are identical for ``==``
        and ``is``), so the impact-scoped gate LETS THE MOVE LAND.
      * ``pkg/wrapper.py`` — calls ``is_blank`` indirectly; ``test_wrapper.py``
        imports the WRAPPER (not ``check``), so it is OUTSIDE the move's impacted
        scope. It feeds ``MISSING`` and is GREEN at baseline (``MISSING == None``)
        but RED after the rewrite (``MISSING is None`` is False) — the transitive
        regression the scoped gate misses.
      * ``tests/test_unrelated_red.py`` — a pre-existing FAILING test (unrelated),
        which FORCES the session onto the impact-scoped path (the violation's
        precondition)."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "sentinel.py").write_text(
        "class Missing:\n"
        "    def __eq__(self, other):\n"
        "        return other is None or isinstance(other, Missing)\n"
        "    def __hash__(self):\n        return 0\n\n\n"
        "MISSING = Missing()\n", encoding="utf-8")
    (root / "pkg" / "check.py").write_text(
        "def is_blank(value):\n    return value == None\n", encoding="utf-8")
    (root / "pkg" / "wrapper.py").write_text(
        "from pkg.check import is_blank\n\n\n"
        "def blank_via_wrapper(value):\n    return is_blank(value)\n",
        encoding="utf-8")
    (root / "tests" / "test_check.py").write_text(
        "from pkg.check import is_blank\n"
        "def test_blank_none():\n    assert is_blank(None) is True\n"
        "def test_blank_value():\n    assert is_blank(7) is False\n",
        encoding="utf-8")
    (root / "tests" / "test_wrapper.py").write_text(
        "from pkg.wrapper import blank_via_wrapper\n"
        "from pkg.sentinel import MISSING\n"
        "def test_missing_is_blank():\n"
        "    assert blank_via_wrapper(MISSING) is True\n", encoding="utf-8")
    (root / "tests" / "test_unrelated_red.py").write_text(
        "def test_preexisting_failure():\n    assert 1 == 2\n", encoding="utf-8")
    return root


def test_transitive_regression_on_red_baseline_is_rolled_back(tmp_path: Path):
    # THE MOAT FIX, end-to-end. A behaviour-changing modernize move that breaks a
    # previously-GREEN test reachable only transitively now ROLLS BACK (not merely
    # discloses). The file is restored to its baseline bytes and the previously-
    # green test passes again.
    _transitive_regression_project(tmp_path)
    check_before = (tmp_path / "pkg" / "check.py").read_text()

    report = run_develop_session(str(tmp_path), apply=True, verify=True)

    # The session rolled the whole thing back: nothing landed, the node is named.
    assert report.regression_rolled_back is True
    assert report.regressed_nodes == [
        "tests/test_wrapper.py::test_missing_is_blank"]
    assert report.total_moves == 0
    # The modernize change was UN-landed: check.py is byte-for-byte its baseline
    # (still ``== None``), so the previously-green transitive test passes again.
    assert (tmp_path / "pkg" / "check.py").read_text() == check_before
    assert "== None" in (tmp_path / "pkg" / "check.py").read_text()

    # The report HONESTLY says a regression was detected and restored.
    md = render_session_markdown(report)
    assert "Auto-rollback" in md
    assert "ROLLED BACK" in md
    assert "tests/test_wrapper.py::test_missing_is_blank" in md
    # NOT the misleading "already satisfied" wording.
    assert "every objective is already satisfied" not in md


def test_transitive_regression_actually_lands_without_the_backstop(tmp_path: Path):
    # Proves the violation EXISTS: with the per-move impact-scoped gate alone (no
    # end-of-session baseline-diff backstop), the behaviour-changing modernize move
    # LANDS — its own in-scope test still passes — and the transitive green test is
    # broken and silently kept. This is exactly what the backstop now catches.
    from app.engine.objective_compiler import compile_objective

    _transitive_regression_project(tmp_path)
    result = compile_objective(str(tmp_path), objective="modernize", apply=True,
                               verify=True, scope_verify=True)
    # The move landed (scoped gate saw only check.py's own passing tests).
    assert result.steps
    assert "value is None" in (tmp_path / "pkg" / "check.py").read_text()
    # And the transitive green test is now broken — the silent regression.
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q",
         str(tmp_path / "tests" / "test_wrapper.py")],
        cwd=str(tmp_path), env={"PYTHONPATH": str(tmp_path), "PATH": ""},
        capture_output=True, text=True)
    assert proc.returncode != 0  # previously-green test now FAILS, un-rolled-back


def test_red_baseline_clean_session_still_lands_no_over_rollback(tmp_path: Path):
    # THE NO-OVER-ROLLBACK GUARD. A RED-baseline session whose changes do NOT
    # regress any green node must still LAND its contributions; the pre-existing
    # red test (the unsynthesizable stub) must NOT trigger a rollback. (Reuses the
    # tidy-work fixture: red at baseline via an unsynthesizable stub, real tidy
    # work in other modules.)
    _red_baseline_with_tidy_work(tmp_path)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)

    # No regression detected: the pre-existing red is NOT counted as one.
    assert report.regression_rolled_back is False
    assert report.regressed_nodes == []
    # The tidy contributions still LAND (the moat fix preserves them).
    assert report.total_moves > 1
    landed = {o.objective for o in report.objectives if o.moves}
    assert "wire-exports" in landed and "dataclassify" in landed
    # The still-red baseline (unsynthesizable stub) is honestly disclosed as
    # BEFORE — a pre-existing red is disclosure, never a regression-rollback.
    assert report.suite_available is True
    assert report.suite_green_after is False
    md = render_session_markdown(report)
    assert "full suite RED after the session" in md
    assert "Auto-rollback" not in md  # nothing was rolled back


def test_green_baseline_never_runs_regression_backstop(tmp_path: Path, monkeypatch):
    # The GREEN-baseline path is BYTE-IDENTICAL: it gates full-suite per move, so
    # the regression backstop never runs and never rolls anything back. We pin that
    # the failing-node capture is NEVER invoked on a green baseline.
    from app.engine import develop_session as ds

    _green_baseline_with_tidy_work(tmp_path)
    calls = {"n": 0}
    real = ds._failing_nodes

    def counting(root):
        calls["n"] += 1
        return real(root)

    monkeypatch.setattr(ds, "_failing_nodes", counting)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)
    assert calls["n"] == 0  # never captured on a green baseline
    assert report.regression_rolled_back is False
    assert report.regressed_nodes == []
    assert report.total_moves >= 1
    assert report.suite_green_after is True


def test_regression_rollback_is_deterministic_byte_for_byte(tmp_path: Path):
    # Same transitive-regression fixture -> identical rollback outcome + report
    # bytes across two runs (sorted node sets; no clock/random).
    a = _transitive_regression_project(tmp_path / "a")
    b = _transitive_regression_project(tmp_path / "b")
    ra = run_develop_session(str(a), apply=True)
    rb = run_develop_session(str(b), apply=True)
    assert ra.regression_rolled_back is rb.regression_rolled_back is True
    assert ra.regressed_nodes == rb.regressed_nodes
    assert render_session_markdown(ra) == render_session_markdown(rb)
    # The restored tree is byte-identical too.
    assert (a / "pkg" / "check.py").read_text() == (
        b / "pkg" / "check.py").read_text()


def test_regression_fields_serialise(tmp_path: Path):
    # The new fields are on the dict artifact for downstream consumers.
    _transitive_regression_project(tmp_path)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)
    d = report.to_dict()
    assert d["regression_rolled_back"] is True
    assert d["regressed_nodes"] == [
        "tests/test_wrapper.py::test_missing_is_blank"]
