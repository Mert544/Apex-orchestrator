"""Edge-path coverage for app.cli_insight cmd_* dispatch handlers.

Targets the handlers the scattered insight tests leave uncovered: cmd_brief
(build / --check / --develop / --save, plus their None guards), cmd_dream,
cmd_outcomes (--init / pass / fail / no-rubric), cmd_recipes, cmd_changelog
(stdout + --out), cmd_grade (markdown / json / --diff / --save / --min-score),
cmd_impact, cmd_duplication, and cmd_mutants — markdown and json each.

Deterministic, stdlib-only, no network. Every heavy builder (the permutation
engine, brief/dream/outcomes/grade/impact/dedup/mutation engines) is
monkeypatched at its source module so the handler branches run in isolation
and the suite stays fast and hermetic.
"""

from __future__ import annotations

import argparse
import json

import app.cli_insight as cli_insight


def _ns(**overrides) -> argparse.Namespace:
    base = dict(target="", json=False)
    base.update(overrides)
    return argparse.Namespace(**base)


# === cmd_explain: the no-ideas guard ===================================

def test_cmd_explain_no_ideas_returns_1(monkeypatch, capsys):
    # An empty report with no branch given hits the --top no-ideas guard.
    class FakeReport:
        ideas = []

    class FakeEngine:
        def __init__(self, *a, **k):
            pass

        def run(self, objective=None):
            return FakeReport()

    monkeypatch.setattr("app.engine.idea_permutation.IdeaPermutationEngine", FakeEngine)
    args = _ns(branch="", objective="", depth=2, breadth=4, max_ideas=40, facets=False)
    assert cli_insight.cmd_explain(args) == 1
    assert "No ideas generated for this target" in capsys.readouterr().out


# === cmd_brief ==========================================================

def _fake_engine(monkeypatch):
    """Stub IdeaPermutationEngine to a no-op report (brief builders are stubbed)."""
    class FakeReport:
        ideas = []

    class FakeEngine:
        def __init__(self, *a, **k):
            pass

        def run(self, objective=None):
            return FakeReport()

    monkeypatch.setattr("app.engine.idea_permutation.IdeaPermutationEngine", FakeEngine)


def _brief_ns(**overrides) -> argparse.Namespace:
    base = dict(
        target="", branch="", subject="", objective="", depth=2, breadth=4,
        max_ideas=40, save=False, check=False, develop=False, apply=False,
        max_steps=25, no_verify=False, json=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_cmd_brief_build_markdown(monkeypatch, capsys):
    _fake_engine(monkeypatch)

    class FakeBrief:
        branch_path = "x.a"

        def to_dict(self):
            return {"branch": "x.a"}

    monkeypatch.setattr("app.engine.idea_brief.build_brief",
                        lambda report, branch_path, subject: FakeBrief())
    monkeypatch.setattr("app.engine.idea_brief.render_brief_markdown",
                        lambda brief: "# Brief x.a")

    assert cli_insight.cmd_brief(_brief_ns()) == 0
    assert "# Brief x.a" in capsys.readouterr().out


def test_cmd_brief_build_none_returns_1(monkeypatch, capsys):
    _fake_engine(monkeypatch)
    monkeypatch.setattr("app.engine.idea_brief.build_brief",
                        lambda report, branch_path, subject: None)
    assert cli_insight.cmd_brief(_brief_ns()) == 1
    assert "No design-level idea to brief" in capsys.readouterr().out


def test_cmd_brief_build_json_and_save(monkeypatch, capsys):
    _fake_engine(monkeypatch)

    class FakeBrief:
        branch_path = "x.b"

        def to_dict(self):
            return {"branch": "x.b"}

    monkeypatch.setattr("app.engine.idea_brief.build_brief",
                        lambda report, branch_path, subject: FakeBrief())
    monkeypatch.setattr("app.engine.idea_brief.render_brief_markdown", lambda brief: "md")
    monkeypatch.setattr("app.engine.idea_brief.save_brief",
                        lambda brief, target: "/p/baseline.json")

    assert cli_insight.cmd_brief(_brief_ns(json=True, save=True)) == 0
    out = capsys.readouterr().out
    # JSON shape, then the save confirmation line.
    assert json.loads(out[: out.index("\n[brief]")]) == {"branch": "x.b"}
    assert "Evidence baseline saved to /p/baseline.json" in out


def test_cmd_brief_check_needs_branch(capsys):
    assert cli_insight.cmd_brief(_brief_ns(check=True, branch="")) == 1
    assert "--check needs the BRANCH" in capsys.readouterr().out


def test_cmd_brief_check_no_saved_brief(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.idea_brief.check_brief",
                        lambda target, branch: None)
    assert cli_insight.cmd_brief(_brief_ns(check=True, branch="x.a")) == 1
    assert "no saved brief for `x.a`" in capsys.readouterr().out


def test_cmd_brief_check_markdown(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.idea_brief.check_brief",
                        lambda target, branch: {"resolved": 1})
    monkeypatch.setattr("app.engine.idea_brief.render_check_markdown",
                        lambda result: "# Burndown")
    assert cli_insight.cmd_brief(_brief_ns(check=True, branch="x.a")) == 0
    assert "# Burndown" in capsys.readouterr().out


def test_cmd_brief_check_json(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.idea_brief.check_brief",
                        lambda target, branch: {"resolved": 2})
    assert cli_insight.cmd_brief(_brief_ns(check=True, branch="x.a", json=True)) == 0
    assert json.loads(capsys.readouterr().out) == {"resolved": 2}


def test_cmd_brief_develop_none_returns_1(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.brief_develop.develop_brief",
                        lambda *a, **k: None)
    assert cli_insight.cmd_brief(_brief_ns(develop=True)) == 1
    assert "No design-level idea to develop" in capsys.readouterr().out


def test_cmd_brief_develop_dry_run_markdown(monkeypatch, capsys):
    class FakeResult:
        def to_dict(self):
            return {"moves": []}

    monkeypatch.setattr("app.engine.brief_develop.develop_brief",
                        lambda *a, **k: FakeResult())
    monkeypatch.setattr("app.engine.brief_develop.render_brief_develop_markdown",
                        lambda result: "# Develop")
    assert cli_insight.cmd_brief(_brief_ns(develop=True, apply=False)) == 0
    out = capsys.readouterr().out
    assert "# Develop" in out
    assert "Dry run — re-run with --develop --apply" in out


def test_cmd_brief_develop_apply_json_no_dry_run_note(monkeypatch, capsys):
    class FakeResult:
        def to_dict(self):
            return {"moves": ["m1"]}

    monkeypatch.setattr("app.engine.brief_develop.develop_brief",
                        lambda *a, **k: FakeResult())
    assert cli_insight.cmd_brief(_brief_ns(develop=True, apply=True, json=True)) == 0
    out = capsys.readouterr().out
    assert json.loads(out) == {"moves": ["m1"]}
    assert "Dry run" not in out


# === cmd_dream ==========================================================

def test_cmd_dream_markdown_with_digest(monkeypatch, capsys):
    class FakeReport:
        digest_path = "/p/dream.md"

        def to_dict(self):
            return {"patterns": []}

    monkeypatch.setattr("app.engine.dream.dream",
                        lambda target, curate, learn_gates=False: FakeReport())
    monkeypatch.setattr("app.engine.dream.render_dream_markdown", lambda r: "# Dream")
    assert cli_insight.cmd_dream(_ns(curate=False)) == 0
    out = capsys.readouterr().out
    assert "# Dream" in out
    assert "[dream] Digest written to /p/dream.md" in out


def test_cmd_dream_json_passes_curate_flag(monkeypatch, capsys):
    seen: dict = {}

    class FakeReport:
        digest_path = ""

        def to_dict(self):
            return {"curated": True}

    def fake_dream(target, curate, learn_gates=False):
        seen["curate"] = curate
        seen["learn_gates"] = learn_gates
        return FakeReport()

    monkeypatch.setattr("app.engine.dream.dream", fake_dream)
    assert cli_insight.cmd_dream(_ns(curate=True, json=True)) == 0
    assert json.loads(capsys.readouterr().out) == {"curated": True}
    assert seen["curate"] is True
    assert seen["learn_gates"] is False


def test_cmd_dream_threads_learn_gates_flag(monkeypatch, capsys):
    seen: dict = {}

    class FakeReport:
        digest_path = ""

        def to_dict(self):
            return {}

    def fake_dream(target, curate, learn_gates=False):
        seen["learn_gates"] = learn_gates
        return FakeReport()

    monkeypatch.setattr("app.engine.dream.dream", fake_dream)
    assert cli_insight.cmd_dream(_ns(curate=True, learn_gates=True, json=True)) == 0
    assert seen["learn_gates"] is True


# === cmd_outcomes =======================================================

def test_cmd_outcomes_init(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.outcomes.init_rubric",
                        lambda target: "/p/outcomes.json")
    assert cli_insight.cmd_outcomes(_ns(init=True)) == 0
    assert "Starter rubric written to /p/outcomes.json" in capsys.readouterr().out


def test_cmd_outcomes_no_rubric_returns_1(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.outcomes.evaluate", lambda target: None)
    assert cli_insight.cmd_outcomes(_ns(init=False)) == 1
    assert "no rubric at" in capsys.readouterr().out


def test_cmd_outcomes_passed_markdown(monkeypatch, capsys):
    class FakeReport:
        passed = True

        def to_dict(self):
            return {"passed": True}

    monkeypatch.setattr("app.engine.outcomes.evaluate", lambda target: FakeReport())
    monkeypatch.setattr("app.engine.outcomes.render_outcomes_markdown", lambda r: "# Outcomes")
    assert cli_insight.cmd_outcomes(_ns(init=False)) == 0
    assert "# Outcomes" in capsys.readouterr().out


def test_cmd_outcomes_failed_json_returns_1(monkeypatch, capsys):
    class FakeReport:
        passed = False

        def to_dict(self):
            return {"passed": False, "gaps": 3}

    monkeypatch.setattr("app.engine.outcomes.evaluate", lambda target: FakeReport())
    assert cli_insight.cmd_outcomes(_ns(init=False, json=True)) == 1
    assert json.loads(capsys.readouterr().out) == {"passed": False, "gaps": 3}


# === cmd_recipes ========================================================

def test_cmd_recipes_markdown(monkeypatch, capsys):
    monkeypatch.setattr("app.execution.recipes.render_recipes_markdown",
                        lambda: "# Recipes")
    assert cli_insight.cmd_recipes(_ns()) == 0
    assert "# Recipes" in capsys.readouterr().out


def test_cmd_recipes_json(monkeypatch, capsys):
    class FakeRecipe:
        def to_dict(self):
            return {"name": "extract"}

    monkeypatch.setattr("app.execution.recipes.RECIPES", {"extract": FakeRecipe()})
    monkeypatch.setattr("app.execution.recipes.COMPOSITES", {"combo": ["a", "b"]})
    assert cli_insight.cmd_recipes(_ns(json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"recipes": [{"name": "extract"}], "composites": {"combo": ["a", "b"]}}


# === cmd_changelog ======================================================

def test_cmd_changelog_stdout_only(monkeypatch, capsys):
    monkeypatch.setattr("app.reporting.changelog.build_changelog",
                        lambda target: "# Changelog\n")
    assert cli_insight.cmd_changelog(_ns(out="")) == 0
    out = capsys.readouterr().out
    assert "# Changelog" in out
    assert "Written to" not in out


def test_cmd_changelog_writes_out(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("app.reporting.changelog.build_changelog",
                        lambda target: "# CL\n")
    out_file = tmp_path / "notes" / "CHANGELOG.md"
    assert cli_insight.cmd_changelog(_ns(out=str(out_file))) == 0
    assert out_file.read_text(encoding="utf-8") == "# CL\n"
    assert "[changelog] Written to" in capsys.readouterr().out


# === cmd_grade ==========================================================

def _grade_ns(**overrides) -> argparse.Namespace:
    base = dict(target="", json=False, diff=False, save=False, min_score=0)
    base.update(overrides)
    return argparse.Namespace(**base)


class _FakeGrade:
    score = 80

    def to_dict(self):
        return {"score": 80}


def test_cmd_grade_markdown(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.health_score.grade", lambda target: _FakeGrade())
    monkeypatch.setattr("app.engine.health_score.render_grade_markdown", lambda h: "# Grade B")
    assert cli_insight.cmd_grade(_grade_ns()) == 0
    assert "# Grade B" in capsys.readouterr().out


def test_cmd_grade_json(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.health_score.grade", lambda target: _FakeGrade())
    assert cli_insight.cmd_grade(_grade_ns(json=True)) == 0
    assert json.loads(capsys.readouterr().out) == {"score": 80}


def test_cmd_grade_diff_with_snapshot(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.health_score.grade", lambda target: _FakeGrade())
    monkeypatch.setattr("app.engine.health_score.load_grade_snapshot",
                        lambda target: _FakeGrade())
    monkeypatch.setattr("app.engine.health_score.render_grade_diff_markdown",
                        lambda old, new: "# Grade diff")
    assert cli_insight.cmd_grade(_grade_ns(diff=True)) == 0
    assert "# Grade diff" in capsys.readouterr().out


def test_cmd_grade_diff_without_snapshot_falls_back(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.health_score.grade", lambda target: _FakeGrade())
    monkeypatch.setattr("app.engine.health_score.load_grade_snapshot",
                        lambda target: None)
    monkeypatch.setattr("app.engine.health_score.render_grade_markdown", lambda h: "# Grade")
    assert cli_insight.cmd_grade(_grade_ns(diff=True)) == 0
    out = capsys.readouterr().out
    assert "No grade snapshot found" in out
    assert "# Grade" in out


def test_cmd_grade_save_confirms(monkeypatch, capsys):
    saved: dict = {}
    monkeypatch.setattr("app.engine.health_score.grade", lambda target: _FakeGrade())
    monkeypatch.setattr("app.engine.health_score.render_grade_markdown", lambda h: "g")
    monkeypatch.setattr("app.engine.health_score.save_grade_snapshot",
                        lambda target, h: saved.__setitem__("done", True))
    assert cli_insight.cmd_grade(_grade_ns(save=True)) == 0
    assert saved["done"] is True
    assert "[grade] Snapshot saved" in capsys.readouterr().out


def test_cmd_grade_min_score_gate_fails(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.health_score.grade", lambda target: _FakeGrade())
    monkeypatch.setattr("app.engine.health_score.render_grade_markdown", lambda h: "g")
    # score 80 < min_score 90 → non-zero exit (CI gate).
    assert cli_insight.cmd_grade(_grade_ns(min_score=90)) == 1


def test_cmd_grade_min_score_gate_passes(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.health_score.grade", lambda target: _FakeGrade())
    monkeypatch.setattr("app.engine.health_score.render_grade_markdown", lambda h: "g")
    assert cli_insight.cmd_grade(_grade_ns(min_score=70)) == 0


# === cmd_impact =========================================================

class _FakeDef:
    def to_dict(self):
        return {"name": "f"}


class _FakeGraph:
    @staticmethod
    def build(root):
        return _FakeGraph()

    def definitions(self, fn):
        return [_FakeDef()]

    def direct_callers(self, fn):
        return [_FakeDef()]

    def blast_radius(self, fn):
        return [_FakeDef()]


def test_cmd_impact_markdown(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.call_graph.CallGraph", _FakeGraph)
    monkeypatch.setattr("app.engine.call_graph.render_impact_markdown",
                        lambda fn, graph: f"# Impact {fn}")
    assert cli_insight.cmd_impact(_ns(function="run")) == 0
    assert "# Impact run" in capsys.readouterr().out


def test_cmd_impact_json(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.call_graph.CallGraph", _FakeGraph)
    assert cli_insight.cmd_impact(_ns(function="run", json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["function"] == "run"
    assert payload["definitions"] == [{"name": "f"}]
    assert payload["direct_callers"] == [{"name": "f"}]
    assert payload["blast_radius"] == [{"name": "f"}]


# === cmd_duplication ====================================================

class _FakeBlock:
    def to_dict(self):
        return {"lines": 6}


def test_cmd_duplication_markdown(monkeypatch, capsys):
    seen: dict = {}

    def fake_find(root, min_statements, min_occurrences):
        seen["min_statements"] = min_statements
        seen["min_occurrences"] = min_occurrences
        return [_FakeBlock()]

    monkeypatch.setattr("app.engine.dedup.find_duplicates", fake_find)
    monkeypatch.setattr("app.engine.dedup.render_duplicates_markdown",
                        lambda blocks: "# Duplicates")
    assert cli_insight.cmd_duplication(_ns(min_statements=8)) == 0
    assert "# Duplicates" in capsys.readouterr().out
    assert seen == {"min_statements": 8, "min_occurrences": 2}


def test_cmd_duplication_json(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.dedup.find_duplicates",
                        lambda root, min_statements, min_occurrences: [_FakeBlock()])
    assert cli_insight.cmd_duplication(_ns(min_statements=5, json=True)) == 0
    assert json.loads(capsys.readouterr().out) == [{"lines": 6}]


# === cmd_mutants ========================================================

class _FakeMutationResult:
    def to_dict(self):
        return {"killed": 3, "survived": 1}


def test_cmd_mutants_markdown(monkeypatch, capsys):
    seen: dict = {}

    def fake_score(root, module, *, max_mutants, verify_timeout):
        seen.update(module=module, max_mutants=max_mutants, verify_timeout=verify_timeout)
        return _FakeMutationResult()

    monkeypatch.setattr("app.engine.mutation_tester.mutation_score", fake_score)
    monkeypatch.setattr("app.engine.mutation_tester.render_mutation_markdown",
                        lambda result: "# Mutation")
    args = _ns(module="app/x.py", max_mutants=10, timeout=30)
    assert cli_insight.cmd_mutants(args) == 0
    assert "# Mutation" in capsys.readouterr().out
    assert seen == {"module": "app/x.py", "max_mutants": 10, "verify_timeout": 30}


def test_cmd_mutants_json(monkeypatch, capsys):
    monkeypatch.setattr("app.engine.mutation_tester.mutation_score",
                        lambda root, module, *, max_mutants, verify_timeout: _FakeMutationResult())
    args = _ns(module="app/x.py", max_mutants=5, timeout=60, json=True)
    assert cli_insight.cmd_mutants(args) == 0
    assert json.loads(capsys.readouterr().out) == {"killed": 3, "survived": 1}
