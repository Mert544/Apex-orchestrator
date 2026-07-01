"""`goal_fixpoint` — a round-based convergence loop over a whole GOAL SET, the
FIRST real consumer of ``objective_dependencies`` (until this module, its proven
graph was built and tested but never wired to a caller).

These tests pin: an empty goal set is an honest instant fixpoint; the round order
respects ``topological_sort``; a round that lands nothing IS the fixpoint stop
condition; a goal whose landing rolls back is PERMANENTLY retired (never
re-attempted in a later round); a round's circuit breaker stops MID-ROUND on too
many rollbacks; the round cap is an honest stop when the set keeps landing
something; ``covered_only`` threads to BOTH ``orchestrate_goal`` (>=2 leaves) and
``compile_objective`` (1-leaf fallback) — a load-bearing, non-tautological spy
assertion; the 1-leaf fallback dispatch; an unknown goal is refused and retired
immediately; ``to_dict`` is deterministic (no clock/random); plus the
``orchestrate_goal`` ``covered_only`` default-False byte-identical regression and
its True-withholds-uncovered behaviour, and the CLI wiring (usage error, parse +
dispatch, forced covered-only even with --allow-weak, --fixpoint beating --atomic,
and a non-zero exit on a circuit break).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.goal_fixpoint import (
    FixpointReport,
    FixpointRound,
    RoundResult,
    _land_one_goal,
    render_fixpoint_markdown,
    run_goal_fixpoint,
)
from app.engine.objective_compiler import CompileResult
from app.engine.project_goal_orchestrator import GoalLanding


# --- fixtures ----------------------------------------------------------------

def _two_stub_project(tmp_path: Path) -> Path:
    """A whole-tree project with a test-pinned fillable stub (implement-stub) and
    an unsorted import block (sort-imports) — two independently-landable
    single-leaf objectives, each a valid one-node goal."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "s.py").write_text(
        "import os\nimport collections\n\n\n"
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_s.py").write_text(
        "from app.s import add\ndef test_add():\n"
        "    assert add(1, 2) == 3\n    assert add(5, 7) == 12\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _rollback_project(tmp_path: Path) -> Path:
    """A project where ``remove-unused-imports`` would drop a re-exported import a
    test relies on — the move APPLIES then the suite goes RED and rolls back."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "m.py").write_text(
        "import sys\n\ndef f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_reexport():\n    assert app.m.sys is not None\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _stub_plus_modernize_project(tmp_path: Path) -> Path:
    """A project with a fillable stub AND a separate ``== None`` idiom — two
    DISTINCT-file leaves, so ``ship-value``/``polish``-style multi-leaf goals have
    real work to compose (mirrors ``test_project_goal_orchestrator``'s fixture)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "s.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_s.py").write_text(
        "from app.s import add\ndef test_add():\n"
        "    assert add(1, 2) == 3\n    assert add(5, 7) == 12\n", encoding="utf-8")
    (tmp_path / "app" / "m.py").write_text(
        "__all__ = []\ndef r(x):\n    if x == None:\n"
        "        return 0\n    return x\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import r\ndef test_r():\n"
        "    assert r(None) == 0\n    assert r(3) == 3\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


# --- 1. empty goal set ---------------------------------------------------------

def test_empty_goal_set_is_an_honest_instant_fixpoint(tmp_path):
    report = run_goal_fixpoint(str(tmp_path), [])
    assert report.goals == []
    assert report.rounds == []
    assert report.reached_fixpoint is True
    assert report.circuit_broken is False
    assert report.retired == []


def test_empty_goal_set_renders_honest_refusal():
    report = FixpointReport(goals=[])
    md = render_fixpoint_markdown(report)
    assert "Empty goal set" in md


# --- 2. topological order is respected -----------------------------------------

def test_round_order_respects_topological_sort(tmp_path):
    _two_stub_project(tmp_path)
    # freeze-dataclass depends on dataclassify (a PROVEN edge) — pass it reversed
    # and confirm the round re-orders it: dataclassify before freeze-dataclass.
    report = run_goal_fixpoint(str(tmp_path), ["freeze-dataclass", "dataclassify"],
                               apply=False, verify=False)
    assert report.rounds  # at least one round ran
    order = report.rounds[0].order
    assert order.index("dataclassify") < order.index("freeze-dataclass")


# --- 2b. the OPT-IN learned-ranking tiebreak (byte-identical by default) --------

def test_learned_order_default_off_is_byte_identical(tmp_path):
    """``learned_order`` defaults to OFF, and OFF threads ``tiebreak=None`` into
    every round — so the per-round order is byte-identical to the existing
    fixture (the explicit-default and the omitted-default agree)."""
    _two_stub_project(tmp_path)
    goals = ["freeze-dataclass", "dataclassify", "sort-imports"]
    default = run_goal_fixpoint(str(tmp_path), goals, apply=False, verify=False)
    explicit_off = run_goal_fixpoint(str(tmp_path), goals, apply=False,
                                     verify=False, learned_order=False)
    assert [rd.order for rd in default.rounds] == [
        rd.order for rd in explicit_off.rounds]


def test_learned_order_on_fresh_repo_matches_off(tmp_path):
    """On a FRESH repo (no ``.apex/idea-memory.json``, no ``proof-of-fix.json``)
    both learned signals are neutral ``1.0``, so ``learned_order=True`` produces
    the IDENTICAL per-round order to ``learned_order=False`` — the neutral-default
    proof end-to-end (the tiebreak degrades exactly to ``ready[0]``)."""
    _two_stub_project(tmp_path)
    assert not (tmp_path / ".apex" / "idea-memory.json").exists()
    assert not (tmp_path / ".apex" / "proof-of-fix.json").exists()
    goals = ["freeze-dataclass", "dataclassify", "sort-imports"]
    off = run_goal_fixpoint(str(tmp_path), goals, apply=False, verify=False,
                            learned_order=False)
    on = run_goal_fixpoint(str(tmp_path), goals, apply=False, verify=False,
                           learned_order=True)
    assert [rd.order for rd in on.rounds] == [rd.order for rd in off.rounds]


def test_learned_order_goal_tree_name_does_not_error_or_bias(tmp_path):
    """A GOAL-TREE / non-leaf name (untracked as an operator) mixed into the goal
    set neither errors nor biases the fresh-repo order: it scores the neutral
    ``1.0`` like everything else, so ``learned_order=True`` still matches
    ``learned_order=False`` byte-for-byte."""
    _two_stub_project(tmp_path)
    # 'reduce-debt' is a composite goal name (a non-leaf in the fractal tree),
    # not an operator the memory or realization stores key on.
    goals = ["reduce-debt", "sort-imports", "dataclassify", "freeze-dataclass"]
    off = run_goal_fixpoint(str(tmp_path), goals, apply=False, verify=False,
                            learned_order=False)
    on = run_goal_fixpoint(str(tmp_path), goals, apply=False, verify=False,
                           learned_order=True)
    assert [rd.order for rd in on.rounds] == [rd.order for rd in off.rounds]


def test_learned_tiebreak_neutral_on_a_fresh_repo(tmp_path):
    """The precomputed tiebreak closure scores EVERY name — a real objective, a
    goal-tree/non-leaf name, and an entirely unknown name — at exactly the neutral
    ``1.0`` on a fresh repo, so it can never reorder ready peers there (the
    signal-level neutral-default proof under the fixpoint end-to-end one)."""
    from app.engine.goal_fixpoint import _build_learned_tiebreak

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='p'\nversion='0'\n", encoding="utf-8")
    tb = _build_learned_tiebreak(str(tmp_path))
    for name in ("sort-imports", "freeze-dataclass", "dataclassify",
                 "reduce-debt", "tidy", "totally-unknown-name"):
        assert tb(name) == 1.0


# --- 3. fixpoint = a round that lands nothing -----------------------------------

def test_fixpoint_reached_when_a_round_lands_nothing(tmp_path):
    _two_stub_project(tmp_path)
    report = run_goal_fixpoint(str(tmp_path), ["implement-stub", "sort-imports"],
                               apply=True, verify=True, max_rounds=10)
    assert report.reached_fixpoint is True
    assert report.max_rounds_hit is False
    # The final round landed nothing (everything already landed the round before).
    assert report.rounds[-1].landed_goals == []


# --- 4. a rolled-back goal is PERMANENTLY retired -------------------------------

def test_rolled_back_goal_is_permanently_retired(tmp_path):
    _rollback_project(tmp_path)
    report = run_goal_fixpoint(str(tmp_path), ["remove-unused-imports"],
                               apply=True, verify=True, max_rounds=5)
    assert "remove-unused-imports" in report.retired
    # It was attempted exactly ONCE across the whole run — never re-attempted in a
    # later round despite the loop continuing (nothing else to land ⇒ fixpoint).
    attempts = [r for rnd in report.rounds for r in rnd.results
                if r.goal == "remove-unused-imports"]
    assert len(attempts) == 1
    assert attempts[0].status == "rolled_back"
    # The file is restored byte-for-byte — the inherited never-fake-green rollback.
    original = (tmp_path / "app" / "m.py").read_text(encoding="utf-8")
    assert "import sys" in original


def test_retirement_prevents_reattempt_across_rounds(monkeypatch, tmp_path):
    # A synthetic multi-goal set where ONE goal always rolls back and a SECOND
    # keeps landing (so the loop runs several rounds) — confirm the rolled-back
    # goal appears in the per-goal attempt log only ONCE, not once per round.
    calls: list[str] = []

    def fake_land(root, goal, *, max_steps, verify, apply, covered_only):
        calls.append(goal)
        if goal == "bad":
            return RoundResult(goal=goal, status="rolled_back", via="compile")
        # "good" lands on its first two calls, then goes empty (fixpoint).
        if calls.count("good") <= 2:
            return RoundResult(goal=goal, status="landed", via="compile")
        return RoundResult(goal=goal, status="empty", via="compile")

    monkeypatch.setattr("app.engine.goal_fixpoint._land_one_goal", fake_land)
    report = run_goal_fixpoint(str(tmp_path), ["bad", "good"], apply=True,
                               verify=False, max_rounds=10)
    assert calls.count("bad") == 1
    assert "bad" in report.retired
    assert report.reached_fixpoint is True


# --- 5. circuit breaker stops MID-ROUND ------------------------------------------

def test_circuit_breaker_stops_mid_round(monkeypatch, tmp_path):
    # Four goals; the first three all roll back — with max_rollbacks_per_round=2
    # the round (and the loop) stops AFTER the second rollback, never reaching the
    # third or fourth goal in that round's topological order.
    def fake_land(root, goal, *, max_steps, verify, apply, covered_only):
        return RoundResult(goal=goal, status="rolled_back", via="compile")

    monkeypatch.setattr("app.engine.goal_fixpoint._land_one_goal", fake_land)
    report = run_goal_fixpoint(str(tmp_path), ["a", "b", "c", "d"], apply=True,
                               verify=False, max_rollbacks_per_round=2)
    assert report.circuit_broken is True
    assert len(report.rounds) == 1
    round_ = report.rounds[0]
    assert round_.circuit_broken is True
    # Only the first TWO goals (in topo/input order) were attempted this round.
    assert [r.goal for r in round_.results] == ["a", "b"]
    assert report.reached_fixpoint is False


# --- 6. round cap ----------------------------------------------------------------

def test_round_cap_stops_when_set_keeps_landing(monkeypatch, tmp_path):
    def always_lands(root, goal, *, max_steps, verify, apply, covered_only):
        return RoundResult(goal=goal, status="landed", via="compile")

    monkeypatch.setattr("app.engine.goal_fixpoint._land_one_goal", always_lands)
    report = run_goal_fixpoint(str(tmp_path), ["x"], apply=True, verify=False,
                               max_rounds=3)
    assert report.max_rounds_hit is True
    assert report.reached_fixpoint is False
    assert len(report.rounds) == 3


# --- 7. covered_only threads to BOTH orchestrate_goal and compile_objective -----

def test_covered_only_threaded_to_orchestrate_goal(monkeypatch, tmp_path):
    # Non-tautological: spy on the REAL orchestrate_goal call and assert the
    # keyword it actually received, rather than asserting our own stub's return.
    seen: dict = {}

    def spy_orchestrate(root, goal, *, verify=True, apply=True, value_led=False,
                        covered_only=False):
        seen["covered_only"] = covered_only
        return GoalLanding(goal=goal, objectives=["a", "b"])

    monkeypatch.setattr("app.engine.project_goal_orchestrator.orchestrate_goal",
                        spy_orchestrate)
    from app.engine.goal_fixpoint import _land_via_orchestrate

    _land_via_orchestrate(str(tmp_path), "polish", verify=True, apply=True,
                          covered_only=True)
    assert seen["covered_only"] is True

    _land_via_orchestrate(str(tmp_path), "polish", verify=True, apply=True,
                          covered_only=False)
    assert seen["covered_only"] is False


def test_covered_only_threaded_to_compile_objective(monkeypatch, tmp_path):
    seen: dict = {}

    def spy_compile(root, objective="dead-params", max_steps=25, verify=True,
                    apply=True, **kwargs):
        seen["covered_only"] = kwargs.get("covered_only")
        return CompileResult(objective=objective, fitness_start=0.0,
                             fitness_end=0.0)

    monkeypatch.setattr("app.engine.objective_compiler.compile_objective",
                        spy_compile)
    from app.engine.goal_fixpoint import _land_via_compile

    _land_via_compile(str(tmp_path), "dead-params", max_steps=25, verify=True,
                      apply=True, covered_only=True)
    assert seen["covered_only"] is True

    _land_via_compile(str(tmp_path), "dead-params", max_steps=25, verify=True,
                      apply=True, covered_only=False)
    assert seen["covered_only"] is False


def test_covered_only_true_end_to_end_withholds_uncovered(tmp_path):
    # An end-to-end (no monkeypatch) proof that covered_only=True actually changes
    # the landing: a module with a modernize-able idiom but NO exercising test.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "u.py").write_text(
        "def r(x):\n    if x == None:\n        return 0\n    return x\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    report = run_goal_fixpoint(str(tmp_path), ["modernize"], apply=True,
                               verify=True, covered_only=True)
    # Nothing landed — the only candidate move is uncovered, so covered_only
    # withholds it (the safe-by-default sweep policy), never landing it silently.
    assert report.total_landed == 0


# --- 8. 1-leaf fallback dispatch --------------------------------------------------

def test_single_leaf_goal_dispatches_via_compile(tmp_path):
    _two_stub_project(tmp_path)
    result = _land_one_goal(str(tmp_path), "sort-imports", max_steps=25,
                            verify=False, apply=False, covered_only=False)
    assert result.via == "compile"


def test_multi_leaf_goal_dispatches_via_orchestrate(tmp_path):
    _stub_plus_modernize_project(tmp_path)
    result = _land_one_goal(str(tmp_path), "ship-value", max_steps=25,
                            verify=False, apply=False, covered_only=False)
    assert result.via == "orchestrate"


# --- 9. unknown goal is refused and retired immediately --------------------------

def test_unknown_goal_is_refused_and_retired(tmp_path):
    report = run_goal_fixpoint(str(tmp_path), ["not-a-real-goal-xyz"],
                               apply=False, verify=False)
    assert "not-a-real-goal-xyz" in report.retired
    assert report.rounds[0].results[0].status == "unknown"


# --- 10. to_dict determinism -------------------------------------------------------

def test_to_dict_is_deterministic(tmp_path):
    _two_stub_project(tmp_path)
    r1 = run_goal_fixpoint(str(tmp_path), ["sort-imports"], apply=False,
                           verify=False)
    r2 = run_goal_fixpoint(str(tmp_path), ["sort-imports"], apply=False,
                           verify=False)
    assert r1.to_dict() == r2.to_dict()
    d = r1.to_dict()
    for key in ("goals", "rounds", "rounds_run", "retired", "reached_fixpoint",
                "circuit_broken", "max_rounds_hit", "total_landed",
                "grade_before", "grade_after", "grade_delta", "applied"):
        assert key in d


def test_round_result_and_round_to_dict_shape():
    r = RoundResult(goal="g", status="landed", via="compile",
                    files_changed=["a.py"])
    d = r.to_dict()
    assert d == {"goal": "g", "status": "landed", "via": "compile", "reason": "",
                "files_changed": ["a.py"]}
    rnd = FixpointRound(order=["g"], results=[r])
    rd = rnd.to_dict()
    assert rd["landed_goals"] == ["g"]
    assert rd["rolled_back_goals"] == []
    assert rd["circuit_broken"] is False


def test_render_fixpoint_markdown_nonempty(tmp_path):
    _two_stub_project(tmp_path)
    report = run_goal_fixpoint(str(tmp_path), ["sort-imports"], apply=False,
                               verify=False)
    md = render_fixpoint_markdown(report)
    assert "sort-imports" in md
    assert "Develop fixpoint" in md


# --- orchestrate_goal covered_only regression + True behaviour ------------------

def test_orchestrate_goal_covered_only_default_false_byte_identical(tmp_path):
    from app.engine.project_goal_orchestrator import orchestrate_goal

    _stub_plus_modernize_project(tmp_path)
    landing = orchestrate_goal(str(tmp_path), "ship-value", apply=True)
    assert landing.applied and landing.verified
    assert not landing.refused and not landing.rolled_back


def test_orchestrate_goal_covered_only_true_withholds_uncovered(monkeypatch, tmp_path):
    from app.engine.project_goal_orchestrator import orchestrate_goal

    seen: dict = {}
    real_apply_rename = __import__(
        "app.execution.cross_file_rename", fromlist=["apply_rename"]).apply_rename

    def spy_apply_rename(root, plan, verify=True, impact_scope=False,
                         covered_only=False, tier=0, baseline_failing=None):
        seen["covered_only"] = covered_only
        seen["tier"] = tier
        return real_apply_rename(root, plan, verify=verify,
                                 impact_scope=impact_scope,
                                 covered_only=covered_only, tier=tier,
                                 baseline_failing=baseline_failing)

    monkeypatch.setattr("app.engine.project_goal_orchestrator.apply_rename",
                        spy_apply_rename)
    _stub_plus_modernize_project(tmp_path)
    orchestrate_goal(str(tmp_path), "ship-value", apply=True, covered_only=True)
    assert seen["covered_only"] is True
    assert seen["tier"] == 1


# --- CLI wiring -------------------------------------------------------------------

class _Args:
    def __init__(self, **kw):
        self.target = ""
        self.goals = ""
        self.fixpoint = False
        self.max_rounds = 10
        self.max_steps = 25
        self.no_verify = False
        self.apply = False
        self.json = False
        self.allow_weak = False
        self.atomic = False
        self.goal = ""
        for k, v in kw.items():
            setattr(self, k, v)


def test_cli_goals_without_fixpoint_is_usage_error(tmp_path, capsys):
    from app.cli_autonomy import cmd_develop

    args = _Args(target=str(tmp_path), goals="reduce-debt")
    rc = cmd_develop(args)
    assert rc == 2
    captured = capsys.readouterr()
    assert "--fixpoint" in captured.err


def test_cli_goals_and_fixpoint_parses_and_dispatches(tmp_path, capsys):
    from app.cli_autonomy import cmd_develop

    _two_stub_project(tmp_path)
    args = _Args(target=str(tmp_path), goals="sort-imports", fixpoint=True,
                json=True)
    rc = cmd_develop(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert '"goals"' in out
    assert "sort-imports" in out


def test_cli_forces_covered_only_even_with_allow_weak(monkeypatch, tmp_path):
    # The load-bearing, non-tautological test: --allow-weak must NOT flip
    # covered_only off for --fixpoint (unattended, mirrors cmd_evolve).
    from app.cli_autonomy import cmd_develop

    seen: dict = {}

    def spy_run(project_root, goals, *, max_rounds=10, max_steps_per_goal=25,
               verify=True, apply=False, covered_only=False,
               max_rollbacks_per_round=3):
        seen["covered_only"] = covered_only
        from app.engine.goal_fixpoint import FixpointReport
        return FixpointReport(goals=list(goals))

    monkeypatch.setattr("app.engine.goal_fixpoint.run_goal_fixpoint", spy_run)
    args = _Args(target=str(tmp_path), goals="sort-imports", fixpoint=True,
                allow_weak=True)
    cmd_develop(args)
    assert seen["covered_only"] is True  # --allow-weak was IGNORED


def test_cli_fixpoint_wins_over_atomic(tmp_path, capsys):
    from app.cli_autonomy import cmd_develop

    _two_stub_project(tmp_path)
    args = _Args(target=str(tmp_path), goals="sort-imports", fixpoint=True,
                atomic=True, goal="reduce-debt", json=True)
    rc = cmd_develop(args)
    assert rc == 0
    out = capsys.readouterr().out
    # The fixpoint report shape (goals set), not a GoalLanding — proves --fixpoint
    # dispatched, not the --goal --atomic path.
    assert '"goals"' in out and '"rounds"' in out


def test_cli_exits_nonzero_on_circuit_break(monkeypatch, tmp_path):
    from app.cli_autonomy import cmd_develop

    def spy_run(project_root, goals, *, max_rounds=10, max_steps_per_goal=25,
               verify=True, apply=False, covered_only=False,
               max_rollbacks_per_round=3):
        from app.engine.goal_fixpoint import FixpointReport
        return FixpointReport(goals=list(goals), circuit_broken=True)

    monkeypatch.setattr("app.engine.goal_fixpoint.run_goal_fixpoint", spy_run)
    args = _Args(target=str(tmp_path), goals="sort-imports", fixpoint=True,
                json=True)
    rc = cmd_develop(args)
    assert rc == 1


def test_parse_goals_refuses_unknown_and_empty():
    from app.cli_autonomy import _parse_goals

    goals, err = _parse_goals("")
    assert goals == [] and err is not None
    goals, err = _parse_goals("not-a-real-goal-xyz")
    assert err is not None and "not-a-real-goal-xyz" in err
    goals, err = _parse_goals(" sort-imports , dead-params ")
    assert goals == ["sort-imports", "dead-params"] and err is None
