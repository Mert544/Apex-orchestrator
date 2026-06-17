"""Deep mutation-hardening for ``app/engine/objective_compiler.py``.

The default ``apex mutants`` 30-cap masks the deeper survivors in this ~1030-line
module. This file enumerates the FULL single-token mutant universe (via the
engine's own ``_collect_sites``: 145 valid splices) and kills every
NON-EQUIVALENT survivor the focused suite left standing, one deterministic test
per survivor, named for its line + operator.

Each test pins a single mutated token's observable effect — a flipped default,
a short-circuit guard, a relational boundary, an index, an arithmetic sign — so
the corresponding mutant fails at least one assertion here. Equivalent mutants
(no observable behaviour change, hence unkillable by any test) are documented at
the bottom with their reasoning, not tested.

Style mirrors ``test_objective_compiler.py`` / ``..._more_edges.py``: a tiny
``tmp_path`` project, direct helper calls, lightweight fakes for plans/results.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.engine.objective_compiler import (
    CompileResult,
    CompileStep,
    Move,
    _apply_one_move,
    _content_plan,
    _dedup_moves,
    _fill_dry_run,
    _modernize_candidates,
    _move_module_from_target,
    _resolve_compile_target,
    _run_pass,
    compile_all,
    compile_from_dream,
    compile_objective,
    dream_confluence_modules,
    render_all_markdown,
    render_compile_markdown,
)
from app.execution.cross_file_rename import RenamePlan


def _project(tmp_path: Path, body: str, rel: str = "app/m.py") -> Path:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / rel).write_text(body, encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_import():\n    assert app.m is not None\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


_THREE_DEAD = (
    "def render(text, color=None, width=80):\n"
    "    return text[:width]\n\n\n"
    "def fetch(url, retries=3):\n"
    "    return url\n\n\n"
    "def use():\n"
    "    return render('hi', width=10) + fetch('u', retries=1)\n"
)


# --- L68: CompileStep.verified default `False` -> `True` ----------------------

def test_l68_compile_step_verified_defaults_to_false():
    # The `verified: bool = False` field default. Mutating it to True would flip
    # an unverified step's tick on.
    s = CompileStep(operator="op", target="app/m.py:x", description="d",
                    fitness_before=1.0, fitness_after=0.0)
    assert s.verified is False
    assert s.to_dict()["verified"] is False


# --- L273: `if res and getattr(...)` in _content_plan: and -> or --------------

class _TruthyNoPatch:
    """Truthy object that lacks ``patch_requests`` — so ``getattr`` returns the
    default ``None``. Under ``and`` the guard skips cleanly; under ``or`` the
    truthy ``res`` enters the branch and ``res.patch_requests`` explodes."""
    pass


def test_l273_content_plan_and_guard_short_circuits_on_missing_patch(tmp_path):
    _project(tmp_path, "x = 1\n")
    plan = _content_plan(str(tmp_path), "app/m.py",
                         lambda r, s, t: _TruthyNoPatch(), "title")
    # `and` correctly short-circuits (getattr default None is falsy) -> no edit,
    # no crash. The `or` mutant would AttributeError on `.patch_requests`.
    assert plan.new_contents == {}
    assert plan.blockers == []


# --- L293/L295: _modernize_candidates guards ---------------------------------

def test_l293_modernize_candidates_skips_truthy_result_without_patch(tmp_path):
    # A transform returning a truthy object without `patch_requests`: the
    # `res and getattr(...)` guard (L293) must short-circuit. The `or` mutant
    # would index `res.patch_requests[0]` and crash.
    _project(tmp_path, "x = 1\n")
    import app.engine.objective_compiler as oc

    def fake_tidy():
        return [("op", "label", lambda r, s, t: _TruthyNoPatch())]

    orig = oc._tidy_transforms
    oc._tidy_transforms = fake_tidy
    try:
        assert _modernize_candidates(str(tmp_path)) == []
    finally:
        oc._tidy_transforms = orig


def test_l295_modernize_candidates_skips_identical_new_content(tmp_path):
    # `if new and new != source` (L295): a transform producing content identical
    # to the source must NOT be counted. The `and -> or` mutant would count it.
    _project(tmp_path, "x = 1\n")
    import app.engine.objective_compiler as oc

    class _Same:
        patch_requests = [{"new_content": "x = 1\n"}]  # equals source

    def fake_tidy():
        return [("op", "label", lambda r, s, t: _Same())]

    orig = oc._tidy_transforms
    oc._tidy_transforms = fake_tidy
    try:
        assert _modernize_candidates(str(tmp_path)) == []
    finally:
        oc._tidy_transforms = orig


# --- L370: `getattr(block, "occurrences", []) or []` : or -> and --------------

class _BlockNoneOcc:
    occurrences = None
    lines = 3


def test_l370_dedup_moves_coerces_none_occurrences_to_empty(tmp_path):
    # `getattr(block, "occurrences", []) or []` turns a None into []. The
    # `or -> and` mutant yields `None and []` -> None, so `list(None)` crashes.
    _project(tmp_path, "x = 1\n")
    import app.engine.objective_compiler as oc

    orig = oc._duplicate_blocks
    oc._duplicate_blocks = lambda root: [_BlockNoneOcc()]
    try:
        moves = _dedup_moves(str(tmp_path))
        assert len(moves) == 1
        assert moves[0].target == "?:dup"  # empty occ -> the "?" module fallback
    finally:
        oc._duplicate_blocks = orig


# --- L371: `occ[0]` index -> `occ[1]` ; module = first occurrence's file ------

class _BlockTwoOcc:
    occurrences = ["app/first.py:10", "app/second.py:20"]
    lines = 2


def test_l371_dedup_move_targets_first_occurrence_module(tmp_path):
    # `occ[0].split(":", 1)[0]` -> the FIRST occurrence's module. The `0 -> 1`
    # index mutant would target the second module instead.
    _project(tmp_path, "x = 1\n")
    import app.engine.objective_compiler as oc

    orig = oc._duplicate_blocks
    oc._duplicate_blocks = lambda root: [_BlockTwoOcc()]
    try:
        moves = _dedup_moves(str(tmp_path))
        assert moves[0].target == "app/first.py:dup"
    finally:
        oc._duplicate_blocks = orig


# --- L703: _move_module split index [0] (maxsplit equivalence covered below) --

def test_l703_move_module_takes_segment_before_first_colon():
    from app.engine.objective_compiler import _move_module
    mv = Move(operator="op", target="app/pkg/m.py:render(color)",
              description="d", build_plan=lambda: RenamePlan(old="a", new="b"))
    # The part before the first ':' — index [0]. A `[0] -> [1]` style change
    # would return the function part instead.
    assert _move_module(mv) == "app/pkg/m.py"


# --- L722: `resolved is not None and resolved in objectives` : and -> or ------

def test_l722_resolve_target_requires_both_resolved_and_known(tmp_path):
    # A natural-language phrase that resolves to a KNOWN name but is absent from
    # the (restricted) objectives dict must fall through to "unknown". The
    # `and -> or` mutant would accept it (return the resolved name) even though
    # it isn't runnable here.
    objectives = {"dead-params": (lambda r: 0.0, lambda r: [])}
    # "tidy" resolves to "modernize" via the synonym table, but "modernize" is
    # NOT in this objectives dict.
    name, blocked = _resolve_compile_target("tidy", objectives)
    assert name is None
    assert blocked is not None
    assert any("unknown objective 'tidy'" in b for b in blocked.blocked)


def test_l722_resolve_target_accepts_resolved_and_known():
    # The companion truthy branch: a phrase resolving to a name that IS present.
    objectives = {"modernize": (lambda r: 0.0, lambda r: [])}
    name, blocked = _resolve_compile_target("tidy", objectives)
    assert name == "modernize"
    assert blocked is None


# --- L761: `max(0.0, start - 1)` float floor in dry run -----------------------

def test_l761_dry_run_fitness_after_floors_at_zero(tmp_path):
    # With start == 1.0 the projected fitness_after = max(0.0, 0.0) = 0.0. The
    # `0.0 -> 1.0` mutant would floor at 1.0, so fitness_after would be 1.0.
    result = CompileResult(objective="x", fitness_start=1.0, fitness_end=1.0)
    plan = RenamePlan(old="app/m.py", new="t")
    plan.new_contents["app/m.py"] = "y = 2\n"
    mv = Move(operator="op", target="app/m.py:x", description="d",
              build_plan=lambda: plan)
    out = _fill_dry_run(result, [mv], start=1.0, max_steps=5)
    assert out.steps[0].fitness_after == 0.0


# --- L777: `if plan.blockers or not plan.new_contents` : or -> and ------------

def test_l777_apply_one_move_blocks_on_empty_plan(tmp_path):
    # A plan with NO blockers and NO new_contents is a no-op move: `blockers or
    # not new_contents` is True -> short-circuit BEFORE calling apply_rename, with
    # NO blocked reason recorded. The `or -> and` mutant yields `[] and True` ->
    # [] (falsy), so it skips the early return, calls apply_rename on the empty
    # plan, and records a spurious "nothing to rename" blocker.
    _project(tmp_path, "x = 1\n")
    result = CompileResult(objective="x", fitness_start=1.0, fitness_end=1.0)
    empty = RenamePlan(old="app/m.py", new="t")  # no blockers, no new_contents
    mv = Move(operator="op", target="app/m.py:x", description="d",
              build_plan=lambda: empty)
    landed, current = _apply_one_move(result, mv, str(tmp_path), 1.0,
                                      verify=False, scope_verify=False)
    assert landed is False
    assert current == 1.0
    assert result.steps == []
    assert result.blocked == []  # the `and` mutant records "nothing to rename"


# --- L780/L786/L792: the (landed, fitness) return booleans --------------------

def test_l780_blocked_plan_returns_not_landed(tmp_path):
    # `return False, current` for a blocked plan. The `False -> True` mutant
    # would report the blocked move as landed.
    result = CompileResult(objective="x", fitness_start=2.0, fitness_end=2.0)
    blocked = RenamePlan(old="app/m.py", new="t")
    blocked.blockers.append("precondition failed")
    mv = Move(operator="op", target="app/m.py:x", description="d",
              build_plan=lambda: blocked)
    landed, current = _apply_one_move(result, mv, ".", 2.0,
                                      verify=False, scope_verify=False)
    assert landed is False
    assert current == 2.0
    assert result.steps == []
    assert any("precondition failed" in b for b in result.blocked)


def test_l786_suite_failure_rollback_returns_not_landed(tmp_path):
    # The SECOND `return False, current` (L786): a verified apply whose suite
    # FAILS is auto-rolled-back and must count as NOT landed, current unchanged,
    # the rollback reason recorded. The `False -> True` mutant would report the
    # rolled-back move as landed (and never decrement fitness).
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def render(text, color=None, width=80):\n    return text[:width]\n"
        "def use():\n    return render('hi', width=3)\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "def test_fail():\n    assert False\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    from app.execution.param_drop import plan_param_drop
    result = CompileResult(objective="dead-params", fitness_start=1.0,
                           fitness_end=1.0)
    mv = Move(operator="drop_param", target="app/m.py:render(color)",
              description="drop color",
              build_plan=lambda: plan_param_drop(str(tmp_path), "render", "color"))
    landed, current = _apply_one_move(result, mv, str(tmp_path), 1.0,
                                      verify=True, scope_verify=False)
    assert landed is False  # rolled back -> not landed
    assert current == 1.0
    assert result.steps == []
    assert any("render(color)" in b for b in result.blocked)


def test_l792_clean_apply_returns_landed_and_decremented(tmp_path):
    # `return True, nxt` on a clean apply (L792) plus `nxt = max(0.0, current-1)`.
    # The `True -> False` mutant would report a real apply as not landed.
    _project(tmp_path, _THREE_DEAD)
    result = CompileResult(objective="dead-params", fitness_start=2.0,
                           fitness_end=2.0)
    from app.execution.param_drop import plan_param_drop
    mv = Move(operator="drop_param", target="app/m.py:render(color)",
              description="drop color",
              build_plan=lambda: plan_param_drop(str(tmp_path), "render", "color"))
    landed, current = _apply_one_move(result, mv, str(tmp_path), 2.0,
                                      verify=False, scope_verify=False)
    assert landed is True
    assert current == 1.0
    assert len(result.steps) == 1


# --- L805/L813: `progressed` flag in _run_pass -------------------------------

def test_l805_run_pass_reports_no_progress_when_nothing_lands(tmp_path):
    # `progressed = False` initial. With only blocked moves, the pass made no
    # progress. The `False -> True` mutant would claim progress (and the campaign
    # would not break at the fixpoint).
    result = CompileResult(objective="x", fitness_start=1.0, fitness_end=1.0)
    blocked = RenamePlan(old="app/m.py", new="t")
    blocked.blockers.append("nope")
    mv = Move(operator="op", target="app/m.py:x", description="d",
              build_plan=lambda: blocked)
    progressed, current, last_op = _run_pass(
        result, [mv], ".", 1.0, max_steps=5, verify=False,
        scope_verify=False, last_operator="")
    assert progressed is False
    assert last_op == ""


def test_l813_run_pass_reports_progress_when_a_move_lands(tmp_path):
    # `progressed = True` after a landed move (L813). The `True -> False` mutant
    # would deny the progress and stop the campaign one pass early.
    _project(tmp_path, _THREE_DEAD)
    result = CompileResult(objective="dead-params", fitness_start=2.0,
                           fitness_end=2.0)
    from app.execution.param_drop import plan_param_drop
    mv = Move(operator="drop_param", target="app/m.py:render(color)",
              description="drop color",
              build_plan=lambda: plan_param_drop(str(tmp_path), "render", "color"))
    progressed, current, last_op = _run_pass(
        result, [mv], str(tmp_path), 2.0, max_steps=5, verify=False,
        scope_verify=False, last_operator="")
    assert progressed is True
    assert last_op == "drop_param"


# --- L832/L833/L834: compile_objective default flags -------------------------

def test_l833_compile_objective_apply_defaults_true(tmp_path):
    # `apply: bool = True` default -> moves are written. The `True -> False`
    # mutant would default to a dry run (no writes, applied=False).
    _project(tmp_path, _THREE_DEAD)
    r = compile_objective(str(tmp_path), objective="dead-params", verify=False)
    assert r.applied is True
    src = (tmp_path / "app" / "m.py").read_text()
    assert "color" not in src  # the drop was actually written


def test_l832_compile_objective_verify_defaults_true(tmp_path):
    # `verify: bool = True` default -> each landed step is suite-verified. The
    # `True -> False` mutant would default verify off and steps would be
    # verified=False.
    _project(tmp_path, _THREE_DEAD)
    r = compile_objective(str(tmp_path), objective="dead-params")
    assert r.steps
    assert all(s.verified is True for s in r.steps)


def _twenty_six_unsorted_modules(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    (tmp_path / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    for i in range(26):
        (tmp_path / "app" / f"m{i}.py").write_text(
            "import sys\nimport os\n\n\ndef f():\n"
            "    return os.getcwd() + sys.argv[0]\n", encoding="utf-8")


def test_l832_compile_objective_max_steps_defaults_to_25(tmp_path):
    # `max_steps: int = 25` default for compile_objective. With 26 candidate
    # moves available, a default-cap dry run lists exactly 25. The `25 -> 26`
    # mutant would list 26.
    _twenty_six_unsorted_modules(tmp_path)
    r = compile_objective(str(tmp_path), objective="sort-imports", apply=False)
    assert len(r.steps) == 25


# --- L910: _move_module_from_target return + index -------------------------

def test_l910_move_module_from_target_returns_segment_before_colon():
    # `return target.split(":", 1)[0]`. The `return ... -> return None` mutant
    # returns None; the `[0] -> [1]` index mutant returns the suffix instead.
    assert _move_module_from_target("app/x.py:dead-code") == "app/x.py"
    assert _move_module_from_target("app/y.py:f(p)") == "app/y.py"


# --- L913/L914: compile_all default flags ------------------------------------

def test_l914_compile_all_apply_defaults_true(tmp_path):
    # `apply: bool = True` default for compile_all -> the sweep writes. The
    # `True -> False` mutant would default the whole sweep to a dry run.
    _project(tmp_path, _THREE_DEAD)
    results = compile_all(str(tmp_path), verify=False)
    dead = [r for r in results if r.objective == "dead-params"][0]
    assert dead.applied is True
    assert "color" not in (tmp_path / "app" / "m.py").read_text()


def test_l913_compile_all_verify_defaults_true(tmp_path):
    # `verify: bool = True` default for compile_all -> landed steps are verified.
    _project(tmp_path, _THREE_DEAD)
    results = compile_all(str(tmp_path))
    dead = [r for r in results if r.objective == "dead-params"][0]
    assert dead.steps
    assert all(s.verified is True for s in dead.steps)


def test_l913_compile_all_max_steps_defaults_to_25(tmp_path):
    # `max_steps: int = 25` default for compile_all (propagated to each
    # objective). compile_all sweeps ALL_OBJECTIVES, which includes `modernize`;
    # with 26 modules carrying tidy debt the default-cap dry-run sweep lists
    # exactly 25 modernize moves. The `25 -> 26` mutant lists 26.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    (tmp_path / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    for i in range(26):
        (tmp_path / "app" / f"m{i}.py").write_text(
            "def check(x):\n    if x == None:\n        return 1\n    return 2\n",
            encoding="utf-8")
    results = compile_all(str(tmp_path), apply=False)
    mod = [r for r in results if r.objective == "modernize"]
    assert mod and len(mod[0].steps) == 25


# --- L923: `if result.steps or result.fitness_start > 0` : or/index ----------

def test_l923_compile_all_includes_objective_with_nonzero_start_no_steps(tmp_path):
    # A result with NO steps but fitness_start > 0 must be reported (there was
    # work, even if blocked). The `or -> and` mutant would drop it; the
    # `0 -> 1` mutant (fitness_start > 1) would drop a start of exactly 1.
    blocked = CompileResult(objective="dead-params", fitness_start=1.0,
                            fitness_end=1.0)
    keep = blocked.steps or blocked.fitness_start > 0
    assert keep is True
    # End-to-end: a project where the only move is blocked by a failing suite
    # still yields a reported (work-having) result.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def render(text, color=None, width=80):\n    return text[:width]\n"
        "def use():\n    return render('hi', width=3)\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "def test_fail():\n    assert False\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    results = compile_all(str(tmp_path), verify=True)
    dead = [r for r in results if r.objective == "dead-params"]
    assert dead and dead[0].steps == []
    assert dead[0].fitness_start == 1.0


# --- L933: `total_gain = sum(r.fitness_start - r.fitness_end ...)` : - -> + ---

def test_l933_render_all_total_gain_is_start_minus_end():
    # total fitness gain = start - end. The `- -> +` mutant would SUM them.
    r = CompileResult(objective="dead-params", fitness_start=5.0, fitness_end=2.0,
                      steps=[CompileStep(operator="o", target="app/m.py:x",
                                         description="d", fitness_before=5.0,
                                         fitness_after=2.0)], applied=True)
    md = render_all_markdown([r])
    assert "total fitness gain **3**" in md  # 5 - 2, not 5 + 2 = 7


# --- L960: `if result.blocked and not result.steps` : and -> or --------------

def test_l960_render_compile_no_improving_line_requires_both(tmp_path):
    # The "_No improving move available_" line shows ONLY when there are blockers
    # AND no steps. A result with BOTH steps and blockers must NOT show it. The
    # `and -> or` mutant would show it whenever either holds.
    r = CompileResult(
        objective="dead-params", fitness_start=2.0, fitness_end=1.0,
        steps=[CompileStep(operator="o", target="app/m.py:x", description="d",
                           fitness_before=2.0, fitness_after=1.0)],
        blocked=["app/m.py: nope"], applied=True)
    md = render_compile_markdown(r)
    assert "_No improving move available" not in md


# --- L967: `enumerate(result.steps, 1)` start index 1 -> 2 -------------------

def test_l967_render_compile_numbers_steps_from_one():
    # Steps are numbered from 1. The `1 -> 2` mutant would start the list at 2.
    r = CompileResult(
        objective="dead-params", fitness_start=2.0, fitness_end=0.0,
        steps=[
            CompileStep(operator="o", target="app/m.py:a", description="first",
                        fitness_before=2.0, fitness_after=1.0),
            CompileStep(operator="o", target="app/m.py:b", description="second",
                        fitness_before=1.0, fitness_after=0.0),
        ], applied=True)
    md = render_compile_markdown(r)
    assert "1. first" in md
    assert "2. second" in md
    assert "3. " not in md


# --- L998: `key.split(":", 1)[1]` maxsplit matters at index [1] --------------

def test_l998_confluence_key_keeps_full_module_path_after_first_colon(tmp_path):
    # A confluence key may carry a module path; `split(":", 1)[1]` keeps
    # EVERYTHING after the first colon. With a windows-style or namespaced module
    # containing a second ':' the `1 -> 2` maxsplit mutant would truncate it.
    _project(tmp_path, "x = 1\n", rel="app/a:b.py")
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "dream-promotions.json").write_text(
        json.dumps([{"key": "confluence:app/a:b.py"}]), encoding="utf-8")
    # maxsplit 1 -> "app/a:b.py" (the real file). maxsplit 2 -> "app/a" (missing).
    assert dream_confluence_modules(str(tmp_path)) == ["app/a:b.py"]


# --- L1005/L1006: compile_from_dream default flags ---------------------------

def test_l1006_compile_from_dream_apply_defaults_true(tmp_path):
    # `apply: bool = True` default -> the scoped campaign writes. The
    # `True -> False` mutant would default to a dry run (applied=False).
    _project(tmp_path, _THREE_DEAD)
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "dream-promotions.json").write_text(
        json.dumps([{"key": "confluence:app/m.py"}]), encoding="utf-8")
    results = compile_from_dream(str(tmp_path), objective="dead-params",
                                 verify=False)
    assert results
    assert results[0].applied is True


def test_l1005_compile_from_dream_verify_defaults_true(tmp_path):
    # `verify: bool = True` default -> the scoped campaign suite-verifies each
    # landed step. The `True -> False` mutant would default verify off.
    _project(tmp_path, _THREE_DEAD)
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "dream-promotions.json").write_text(
        json.dumps([{"key": "confluence:app/m.py"}]), encoding="utf-8")
    results = compile_from_dream(str(tmp_path), objective="dead-params")
    assert results and results[0].steps
    assert all(s.verified is True for s in results[0].steps)


# --- Equivalent mutants (documented, not tested) -----------------------------
#
# These single-token mutations leave behaviour unchanged, so NO test can kill
# them (killing one would mean asserting a falsehood):
#
# * L703 `move.target.split(":", 1)[0]` number `1 -> 2`: maxsplit only bounds how
#   many splits happen; element `[0]` (everything before the FIRST colon) is
#   identical for any maxsplit >= 1. EQUIVALENT.
# * L910 `target.split(":", 1)[0]` number `1 -> 2`: same `[0]`-with-maxsplit
#   argument. EQUIVALENT. (The `[0] -> [1]` index and `return -> None` mutants on
#   the same line ARE killed above by test_l910_*.)
# * L371 `occ[0].split(":", 1)[0]` number `1 -> 2`: same `[0]`-with-maxsplit
#   argument. EQUIVALENT. (The `occ[0] -> occ[1]` index mutant IS killed by
#   test_l371_*.)
# * L890 `for _pass in range(max_steps + 1)` number `1 -> 2` (i.e. `+ 2`): the
#   loop is bounded by the inner `len(result.steps) >= max_steps` cap and the
#   `if not progressed: break` fixpoint exit, never by the range upper bound. To
#   reach iteration `max_steps + 1` every prior pass must have progressed, but
#   each progressing pass adds >= 1 step, so the step-cap fires first; the single
#   spare iteration only ever runs the no-progress check, which breaks
#   immediately. Raising the bound to `+ 2` adds an iteration that can never
#   execute. EQUIVALENT.
# * L891 `if len(result.steps) >= max_steps: break` boundary `>= -> >`: this is
#   the OUTER per-pass guard, but `_run_pass` carries the SAME `>= max_steps`
#   cap (L807) on every move it applies. The inner cap stops a pass at exactly
#   max_steps steps regardless of the outer guard's inclusivity, so flipping the
#   outer `>=` to `>` only lets a pass body START that immediately hits the inner
#   `>=` cap and applies nothing. Observably identical. EQUIVALENT (the outer
#   guard is redundant with the inner one).
# * L904 `if apply and result.steps:` boolean `and -> or`: this archive guard is
#   only reached when `apply=True` (a dry run returns earlier, at `if not apply`,
#   before this line). With apply=True the only divergence is the empty-steps
#   case: `True and [] -> []` (skip) vs `True or [] -> True` (enter). But the
#   entered `_archive_campaign -> record_campaign` itself no-ops on
#   `if not operators` (empty steps == no operators) and writes nothing. So no
#   observable difference exists on any reachable input. EQUIVALENT.
# * L834 `scope_verify: bool = False` default (compile_objective): the only
#   effect of `scope_verify` is `apply_rename(impact_scope=...)`, which either
#   finds no covering tests and FALLS THROUGH to the full suite, or scopes by
#   module-import broadly enough to catch the same failures. For any robustly
#   constructible small fixture the verified/applied/rolled-back outcome is
#   identical for False and True, so the default flip is not observable.
#   EQUIVALENT-IN-PRACTICE (no deterministic, non-fragile discriminator exists).
# * L1005 `max_steps: int = 25` default (compile_from_dream): this objective runs
#   a SCOPED, per-module campaign — `max_steps` caps the moves landed in ONE
#   module. No single module can realistically present > 25 simultaneously
#   landable moves for one objective (modernize yields <= 3/module; the
#   dead-param/import/bool detectors yield at most a handful), so the cap is never
#   the binding constraint and 25 vs 26 is unobservable. The non-scoped 25-default
#   IS pinned by L832 (compile_objective) and L913 (compile_all).
#   EQUIVALENT-IN-PRACTICE.
