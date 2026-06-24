from __future__ import annotations

from pathlib import Path

from app.engine.ascend import (
    AscendReport,
    GoalRanking,
    ascend,
    objective_parent,
    payoff_weights,
    rank_objectives,
    render_ascend_markdown,
    render_plan_markdown,
)


def _debt_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def render(text, color=None, width=80):\n"
        "    if text == None:\n        return dict()\n"
        "    return text[:width]\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import render\ndef test_r():\n"
        "    assert render(None) == {}\n    assert render('hi', width=2) == 'hi'\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _clean_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    # `__all__` is declared so the project is genuinely clean w.r.t. EVERY objective,
    # including wire-module-exports (which would otherwise land an explicit `__all__`
    # on this public-but-undeclared module — a real, behaviour-preserving improvement,
    # so the fixture was only INcompletely clean before).
    (tmp_path / "app" / "m.py").write_text(
        '__all__ = ["add"]\n\n\ndef add(a, b):\n    return a + b\n', encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import add\ndef test_a():\n    assert add(1, 2) == 3\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


# --- ranking ------------------------------------------------------------------

def test_objective_parent_maps_into_tree():
    assert objective_parent("modernize") == "tidy"
    assert objective_parent("dedup") == "simplify-structure"
    assert objective_parent("remove-unused-imports") == "polish"
    # An objective not nested under any goal falls back to its own name.
    assert objective_parent("totally-unknown") == "totally-unknown"


def test_rank_objectives_orders_by_pending_desc(tmp_path):
    _debt_project(tmp_path)
    rankings = rank_objectives(str(tmp_path))
    assert rankings  # every registered objective appears
    pendings = [r.pending for r in rankings]
    assert pendings == sorted(pendings, reverse=True)  # worst first
    # The project has a dead parameter, so that objective carries pending > 0.
    by_name = {r.objective: r.pending for r in rankings}
    assert by_name.get("dead-params", 0) >= 1


def test_goal_ranking_priority_amplifies_with_payoff():
    # No history → priority is exactly pending (fresh project unchanged).
    assert GoalRanking("x", 3.0, "tidy", payoff=0.0).priority == 3.0
    # A proven payoff boosts priority above an equal-pending rival.
    assert GoalRanking("x", 3.0, "tidy", payoff=2.0).priority == 9.0
    # Negative/odd payoff never drops below pending.
    assert GoalRanking("x", 3.0, "tidy", payoff=-5.0).priority == 3.0


def test_payoff_weights_reads_history(tmp_path):
    _clean_project(tmp_path)
    from app.engine.dev_history import record_run
    # Two recorded campaigns: dead-params gained 4 health over 2 moves (+2/move);
    # modernize gained nothing.
    record_run(str(tmp_path), "ascend:dead-params", 2, 80, 84)
    record_run(str(tmp_path), "modernize", 3, 84, 84)
    w = payoff_weights(str(tmp_path))
    assert w["dead-params"] == 2.0
    assert "modernize" not in w  # zero gain → no learned weight


def test_learning_reorders_equal_pending(tmp_path, monkeypatch):
    # Two objectives with identical pending; the one with a learned payoff wins.
    import app.engine.ascend as asc

    monkeypatch.setattr(asc, "payoff_weights", lambda root: {"modernize": 5.0})

    def fake_map():
        return {"modernize": (lambda r: 2.0, lambda r: []),
                "dead-params": (lambda r: 2.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives", lambda: ["dead-params", "modernize"])

    ranked = rank_objectives(str(tmp_path), ["dead-params", "modernize"])
    # Despite equal pending and later registration order, the learned objective
    # is ranked first.
    assert ranked[0].objective == "modernize"
    assert ranked[0].payoff == 5.0


def test_rank_objectives_respects_goal_restriction(tmp_path):
    _debt_project(tmp_path)
    rankings = rank_objectives(str(tmp_path), ["dead-params", "modernize"])
    assert {r.objective for r in rankings} == {"dead-params", "modernize"}


def test_rank_objectives_unknown_name_skipped(tmp_path):
    _clean_project(tmp_path)
    rankings = rank_objectives(str(tmp_path), ["modernize", "not-a-real-objective"])
    assert {r.objective for r in rankings} == {"modernize"}


# --- the climb ----------------------------------------------------------------

def test_ascend_climbs_and_proves_grade(tmp_path):
    _debt_project(tmp_path)
    report = ascend(str(tmp_path), apply=True, verify=False, max_rounds=4)
    assert report.applied
    assert report.rounds  # it did at least one round of work
    assert report.total_moves >= 1
    src = (tmp_path / "app" / "m.py").read_text()
    assert "== None" not in src and "color" not in src  # debt developed away
    assert report.grade_end >= report.grade_start  # never regressed the grade


def test_ascend_reaches_fixpoint_on_clean_project(tmp_path):
    _clean_project(tmp_path)
    report = ascend(str(tmp_path), apply=True, verify=False, max_rounds=4)
    assert report.fixpoint is True
    assert report.rounds == []  # nothing to do


def test_ascend_dry_run_changes_nothing(tmp_path):
    _debt_project(tmp_path)
    before = (tmp_path / "app" / "m.py").read_text()
    report = ascend(str(tmp_path), apply=False)
    assert report.applied is False
    assert (tmp_path / "app" / "m.py").read_text() == before
    assert report.preview  # it reported what it would do


def test_ascend_goal_restriction_only_touches_those_objectives(tmp_path):
    _debt_project(tmp_path)
    report = ascend(str(tmp_path), apply=True, verify=False, goal="tidy", max_rounds=4)
    # Every round's objective is one of tidy's leaves.
    from app.engine.fractal_develop import resolve_goal
    tidy = set(resolve_goal("tidy"))
    assert all(r.objective in tidy for r in report.rounds)


def test_ascend_records_history(tmp_path):
    _debt_project(tmp_path)
    ascend(str(tmp_path), apply=True, verify=False, max_rounds=4)
    from app.engine.dev_history import DevHistory
    runs = DevHistory.load(str(tmp_path)).entries()
    assert any(r.objective.startswith("ascend:") for r in runs)


# --- rendering & report -------------------------------------------------------

def test_render_plan_markdown_lists_board(tmp_path):
    _debt_project(tmp_path)
    md = render_plan_markdown(rank_objectives(str(tmp_path)))
    assert "Develop plan" in md and "Pending" in md and "Next move" in md


def test_render_plan_markdown_fixpoint(tmp_path):
    md = render_plan_markdown([GoalRanking("modernize", 0.0, "tidy")])
    assert "fixpoint" in md


def test_render_ascend_markdown_climb(tmp_path):
    _debt_project(tmp_path)
    md = render_ascend_markdown(ascend(str(tmp_path), apply=True, verify=False))
    assert "Ascend" in md and "Health:" in md and "Round" in md


def test_render_ascend_markdown_preview():
    report = AscendReport(applied=False, preview=[GoalRanking("dead-params", 3.0, "tidy")])
    md = render_ascend_markdown(report)
    assert "preview" in md.lower() and "dead-params" in md


def test_ascend_to_dict_round_trips(tmp_path):
    _debt_project(tmp_path)
    d = ascend(str(tmp_path), apply=True, verify=False).to_dict()
    assert "rounds" in d and "grade_delta" in d and d["applied"] is True


# --- CLI ----------------------------------------------------------------------

def test_cmd_plan(tmp_path, capsys):
    import argparse

    from app.cli_autonomy import cmd_plan
    _debt_project(tmp_path)
    rc = cmd_plan(argparse.Namespace(target=str(tmp_path), goal="", json=False))
    assert rc == 0
    assert "Develop plan" in capsys.readouterr().out


def test_cmd_ascend_apply(tmp_path, capsys):
    import argparse

    from app.cli_autonomy import cmd_ascend
    _debt_project(tmp_path)
    rc = cmd_ascend(argparse.Namespace(
        target=str(tmp_path), goal="", apply=True, max_rounds=4, max_steps=25,
        until="", no_verify=True, json=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Ascend" in out
    assert "color" not in (tmp_path / "app" / "m.py").read_text()


def test_cmd_ascend_until_letter(tmp_path, capsys):
    import argparse

    from app.cli_autonomy import cmd_ascend
    _debt_project(tmp_path)
    rc = cmd_ascend(argparse.Namespace(
        target=str(tmp_path), goal="", apply=True, max_rounds=4, max_steps=25,
        until="A-", no_verify=True, json=False))
    assert rc == 0


def test_target_score_parsing():
    from app.cli_autonomy import _target_score
    assert _target_score("90") == 90
    assert _target_score("A-") == 90
    assert _target_score("b+") == 87
    assert _target_score("") is None
    assert _target_score("nonsense") is None


# --- dream-aware ranking: the organism leads with what its dreams trust ---

def test_reliability_damps_priority():
    assert GoalRanking("x", 10.0, "tidy", reliability=1.0).priority == 10.0
    assert GoalRanking("x", 10.0, "tidy", reliability=0.15).priority == 1.5
    # reliability multiplies on top of pending and payoff.
    assert GoalRanking("x", 10.0, "tidy", payoff=1.0, reliability=0.5).priority == 10.0


def test_land_factors_reads_idea_memory(tmp_path):
    import json
    from app.engine.ascend import land_factors
    (tmp_path / ".apex").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".apex" / "idea-memory.json").write_text(json.dumps({
        "by_operator": {"sort_imports": {"applied": 0, "blocked": 5},     # 0% → blocker
                        "merge_isinstance": {"applied": 5, "blocked": 0}},  # 100% → reliable
        "by_label": {}}), encoding="utf-8")
    f = land_factors(str(tmp_path))
    assert f["sort-imports"] == 0.15        # proven blocker → floored
    # land_factors now reads the Wilson lower bound (stat.confidence), not the raw
    # success_rate, so even a perfect 5-of-5 (rate 1.000) is EVIDENCE-DAMPED to its
    # lower bound (≈0.565): proven-but-thin evidence no longer claims a full 1.0.
    # Updated from the old raw-rate expectation (1.0) — this IS the intended Wilson
    # effect (a 9-of-10, lb≈0.596, ranks above this 5-of-5; a 1-of-1 is below
    # _MIN_SAMPLES, gated out → neutral 1.0, so the damping is only among tracked ops).
    assert round(f["merge-isinstance"], 4) == 0.5655
    assert "fix-not-in-is" not in f         # no samples → absent (neutral 1.0 by default)


def test_dream_aware_rank_demotes_a_proven_blocker(tmp_path, monkeypatch):
    import app.engine.ascend as asc
    monkeypatch.setattr(asc, "payoff_weights", lambda r: {})
    monkeypatch.setattr(asc, "land_factors", lambda r: {"sort-imports": 0.15})

    def fake_map():
        return {"sort-imports": (lambda r: 10.0, lambda r: []),
                "modernize": (lambda r: 5.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)
    monkeypatch.setattr(asc, "available_objectives", lambda: ["sort-imports", "modernize"])

    ranked = asc.rank_objectives(str(tmp_path), ["sort-imports", "modernize"])
    # sort-imports has MORE pending (10 vs 5) but its dreamed 0.15 reliability sinks
    # it (10*0.15=1.5) below modernize (5*1.0=5) — the organism avoids the blocker.
    assert ranked[0].objective == "modernize"
    assert ranked[0].reliability == 1.0


# --- ascend --concrete: opt into the EXPENSIVE high-value concrete objectives ---

def test_rank_objectives_default_excludes_expensive(tmp_path):
    # The fast default board skips the expensive concrete objectives (implement-stub,
    # wire-exports, strengthen-tests, ...) so plan/ascend stay fast.
    _clean_project(tmp_path)
    from app.engine.develop_registry import expensive_names

    board = {r.objective for r in rank_objectives(str(tmp_path))}
    skipped = expensive_names()
    assert skipped  # the registry really flags some objectives expensive
    assert board.isdisjoint(skipped)
    # The named flagship concrete moves are among the skipped set.
    assert {"implement-stub", "wire-exports"} <= skipped


def test_rank_objectives_include_expensive_adds_them(tmp_path):
    # --concrete widens the board to include the expensive objectives.
    _clean_project(tmp_path)
    from app.engine.develop_registry import expensive_names

    board = {r.objective for r in rank_objectives(str(tmp_path), include_expensive=True)}
    skipped = expensive_names()
    # Track the real flag, not a hardcoded list: every expensive objective is now on
    # the board.
    assert skipped <= board
    assert {"implement-stub", "wire-exports"} <= board


def test_include_expensive_board_is_superset_of_default(tmp_path):
    # The widened board is a strict superset of the fast default board.
    _clean_project(tmp_path)
    from app.engine.develop_registry import expensive_names

    default = {r.objective for r in rank_objectives(str(tmp_path))}
    wide = {r.objective for r in rank_objectives(str(tmp_path), include_expensive=True)}
    assert default <= wide
    assert (wide - default) == expensive_names()


def test_explicit_objectives_ignore_include_expensive(tmp_path):
    # The explicit-objectives path is unchanged by the flag: an expensive name
    # passed explicitly is ranked regardless, and a non-expensive explicit list is
    # never widened.
    _clean_project(tmp_path)
    explicit = rank_objectives(str(tmp_path), ["implement-stub"])
    assert {r.objective for r in explicit} == {"implement-stub"}
    explicit_flagged = rank_objectives(str(tmp_path), ["modernize"], include_expensive=True)
    assert {r.objective for r in explicit_flagged} == {"modernize"}


def test_cmd_ascend_concrete_preview_includes_expensive(tmp_path, capsys, monkeypatch):
    import argparse

    from app.cli_autonomy import cmd_ascend

    _clean_project(tmp_path)
    # Force one expensive objective to carry pending debt so it must surface on the
    # preview board (the real fitness of a clean tmp project may be 0 for all).
    from app.engine.objective_compiler import _objectives_map as _real_objectives_map

    def fake_map():
        table = dict(_real_objectives_map())
        table["implement-stub"] = (lambda r: 3.0, lambda r: [])
        return table
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)

    rc = cmd_ascend(argparse.Namespace(
        target=str(tmp_path), goal="", apply=False, max_rounds=4, max_steps=25,
        until="", no_verify=True, fast=False, concrete=True, json=True))
    assert rc == 0
    import json as _json
    report = _json.loads(capsys.readouterr().out)
    previewed = {r["objective"] for r in report["preview"]}
    assert "implement-stub" in previewed


def test_cmd_ascend_default_preview_excludes_expensive(tmp_path, capsys, monkeypatch):
    # Without --concrete the same pending expensive debt never reaches the board.
    import argparse

    from app.cli_autonomy import cmd_ascend
    from app.engine.objective_compiler import _objectives_map as _real_objectives_map

    _clean_project(tmp_path)

    def fake_map():
        table = dict(_real_objectives_map())
        table["implement-stub"] = (lambda r: 3.0, lambda r: [])
        return table
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)

    rc = cmd_ascend(argparse.Namespace(
        target=str(tmp_path), goal="", apply=False, max_rounds=4, max_steps=25,
        until="", no_verify=True, fast=False, concrete=False, json=True))
    assert rc == 0
    import json as _json
    report = _json.loads(capsys.readouterr().out)
    previewed = {r["objective"] for r in report["preview"]}
    assert "implement-stub" not in previewed


def test_expensive_objective_landing_is_recorded_with_zero_delta(tmp_path, monkeypatch):
    # An expensive concrete objective that LANDS code is recorded as a round even
    # when the grade delta is 0 (landing code may not move the health grade — that
    # is not a regression; record_run keeps the round).
    import app.engine.ascend as asc

    _clean_project(tmp_path)

    monkeypatch.setattr(asc, "payoff_weights", lambda r: {})
    monkeypatch.setattr(asc, "land_factors", lambda r: {})
    monkeypatch.setattr(asc, "available_objectives", lambda: ["implement-stub"])
    monkeypatch.setattr(asc, "_grade", lambda r: 90)  # constant grade → delta 0

    def fake_map():
        return {"implement-stub": (lambda r: 1.0, lambda r: [])}
    monkeypatch.setattr("app.engine.objective_compiler._objectives_map", fake_map)

    class _Campaign:
        steps = [object()]  # one landed move

    monkeypatch.setattr(asc, "compile_objective",
                        lambda *a, **k: _Campaign())

    report = asc.ascend(str(tmp_path), apply=True, verify=False, max_rounds=1,
                        include_expensive=True)
    assert len(report.rounds) == 1
    landed = report.rounds[0]
    assert landed.objective == "implement-stub"
    assert landed.grade_after - landed.grade_before == 0  # zero delta, still a round
    from app.engine.dev_history import DevHistory
    runs = DevHistory.load(str(tmp_path)).entries()
    assert any(r.objective == "ascend:implement-stub" for r in runs)
