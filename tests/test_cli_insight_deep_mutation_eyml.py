"""DEEP mutation-hardening guards for app/cli_insight.py — past the 30-cap.

The default ``apex mutants`` run caps verification at 30 mutants, leaving the
bulk of cli_insight's single-token mutant universe unverified. Here the FULL
universe was enumerated with ``app.engine.mutation_tester._collect_sites`` (221
mutable sites) and each one spliced + run against the behavioural covering tests
in an isolated copy. Against the full covering suite every one of the 221 is
already killed (zero real survivors); but 79 of them are killed ONLY by the one
existing deep-mutation file (``test_cli_reporting_insight_deep_mutation_eyml``)
— i.e. they are exactly the mutants the 30-cap masks and that no other covering
test independently catches. This file adds a SECOND, self-contained killer for
each such masked-universe survivor so the hardening no longer rests on a single
test module.

Each test targets one observable behaviour (a branch, an error path, a boundary
value, a default fallback, a return value, or a JSON/text shape) so the seeded
mutation flips an asserted outcome. Heavy engine dependencies are stubbed via
``sys.modules`` injection so each test exercises cli_insight's OWN logic offline;
filesystem behaviour uses tmp dirs. No timestamps, wall-clock, or unordered
collections are asserted, so the suite is byte-stable across runs.

No production module is modified (add-only). No genuine bug was found: the
module's tested behaviour matches its documented contract on every path probed.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import types
from pathlib import Path

import pytest

import app.cli_insight as INS_MOD


def _ns(**kw):
    return argparse.Namespace(**kw)


class _FakeModule(types.ModuleType):
    def __init__(self, name, **attrs):
        super().__init__(name)
        for k, v in attrs.items():
            setattr(self, k, v)


@contextlib.contextmanager
def _inject(**mods):
    saved = {}
    for name, mod in mods.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = mod
    try:
        yield
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def _cap(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*a, **k)
    return rc, buf.getvalue()


def _idea(value, branch):
    return types.SimpleNamespace(value=value, branch_path=branch)


# --------------------------------------------------------------------------
# cmd_explain (lines 16-46)
# --------------------------------------------------------------------------

def _explain_mods(ideas, exp, cfg=None):
    class IPE:
        def __init__(self, config=None, project_root=None):
            if cfg is not None:
                cfg.update(config or {})

        def run(self, objective=None):
            if cfg is not None:
                cfg["_objective"] = objective
            return types.SimpleNamespace(ideas=ideas)

    ie = _FakeModule(
        "app.engine.idea_explain",
        explain_idea=lambda report, branch: exp,
        render_explanation_markdown=lambda e: "EXPMD",
    )
    ip = _FakeModule("app.engine.idea_permutation", IdeaPermutationEngine=IPE)
    return {"app.engine.idea_explain": ie, "app.engine.idea_permutation": ip}


def _explain_args(**over):
    base = dict(target="", max_ideas=40, depth=2, breadth=3, facets=False,
                objective="", branch="", json=False)
    base.update(over)
    return _ns(**base)


def test_explain_facets_default_false_24():
    # Line 24: ``getattr(args, "facets", False)`` default — with no facets attr the
    # default must be False (flip to True would request fractal facets).
    cfg = {}
    exp = types.SimpleNamespace(to_dict=lambda: {})
    args = argparse.Namespace(target="", max_ideas=40, depth=2, breadth=3,
                              objective="", branch="a", json=False)
    with _inject(**_explain_mods([_idea(0.5, "a")], exp, cfg)):
        INS_MOD.cmd_explain(args)
    assert cfg["fractal_facets"] is False, cfg


def test_explain_objective_empty_becomes_none_26():
    # Line 26: ``args.objective or None`` — empty string must collapse to None.
    cfg = {}
    exp = types.SimpleNamespace(to_dict=lambda: {})
    with _inject(**_explain_mods([_idea(0.5, "a")], exp, cfg)):
        INS_MOD.cmd_explain(_explain_args(branch="a", objective=""))
    assert cfg["_objective"] is None, cfg


def test_explain_branch_default_blank_28():
    # Line 28: ``getattr(args, "branch", "") or ""`` — a blank branch routes to the
    # --top path (picks the max-value idea), not the explicit-branch path.
    cfg = {}
    captured = {}
    exp = types.SimpleNamespace(to_dict=lambda: {})
    mods = _explain_mods([_idea(0.1, "a"), _idea(0.9, "b")], exp, cfg)
    mods["app.engine.idea_explain"].explain_idea = (
        lambda report, branch: captured.setdefault("branch", branch) or exp
    )
    args = argparse.Namespace(target="", max_ideas=40, depth=2, breadth=3,
                              facets=False, objective="", json=False)
    with _inject(**mods):
        INS_MOD.cmd_explain(args)
    # max-value idea is "b"; the blank branch must have been replaced by it.
    assert captured["branch"] == "b", captured


def test_explain_no_ideas_returns_1_and_message_37_40():
    # Lines 37 (``if not report.ideas``) and 40 (``return 1``): empty ideas →
    # early return 1 with the no-ideas message.
    exp = types.SimpleNamespace(to_dict=lambda: {})
    with _inject(**_explain_mods([], exp)):
        rc, txt = _cap(INS_MOD.cmd_explain, _explain_args(branch=""))
    assert rc == 1 and "No ideas generated" in txt, (rc, txt)


def test_explain_not_found_returns_1_46():
    # Line 43/46: explain_idea returns None → message + return 1.
    with _inject(**_explain_mods([_idea(0.5, "a")], None)):
        rc, txt = _cap(INS_MOD.cmd_explain, _explain_args(branch="x"))
    assert rc == 1 and "No idea found at branch" in txt, (rc, txt)


def test_explain_max_value_idea_chosen_34():
    # Line 34: ``max(report.ideas, key=lambda i: i.value)`` — the HIGHEST value
    # idea's branch is explained when no branch is given.
    cfg = {}
    captured = {}
    exp = types.SimpleNamespace(to_dict=lambda: {})
    mods = _explain_mods([_idea(0.2, "lo"), _idea(0.8, "hi")], exp, cfg)
    mods["app.engine.idea_explain"].explain_idea = (
        lambda report, branch: captured.setdefault("b", branch) or exp
    )
    with _inject(**mods):
        INS_MOD.cmd_explain(_explain_args(branch=""))
    assert captured["b"] == "hi", captured


def test_explain_json_indent_two_43():
    # Line 43: ``json.dumps(..., indent=2)`` — two-space indent (flip to 3 widens).
    exp = types.SimpleNamespace(to_dict=lambda: {"a": 1})
    with _inject(**_explain_mods([_idea(0.5, "a")], exp)):
        rc, txt = _cap(INS_MOD.cmd_explain, _explain_args(branch="a", json=True))
    assert txt.splitlines()[1].startswith('  "') and not txt.splitlines()[1].startswith('   "'), txt


# --------------------------------------------------------------------------
# cmd_brief and its sub-paths (lines 49-155)
# --------------------------------------------------------------------------

def _brief_args(**over):
    base = dict(target="", branch="b.0", subject="", objective="", depth=2,
                breadth=4, max_ideas=40, save=False, check=False, develop=False,
                apply=False, max_steps=25, no_verify=False, json=False)
    base.update(over)
    return _ns(**base)


def test_brief_check_no_branch_returns_1_56():
    # Lines 53-56 (_brief_check): no branch → message + return 1.
    ib = _FakeModule("app.engine.idea_brief",
                     check_brief=lambda t, b: {"x": 1},
                     render_check_markdown=lambda r: "CHKMD")
    with _inject(**{"app.engine.idea_brief": ib}):
        rc, txt = _cap(INS_MOD.cmd_brief, _brief_args(check=True, branch=""))
    assert rc == 1 and "--check needs the BRANCH" in txt, (rc, txt)


def test_brief_check_no_saved_returns_1_61():
    # Line 58/61 (_brief_check): check_brief returns None → message + return 1.
    ib = _FakeModule("app.engine.idea_brief",
                     check_brief=lambda t, b: None,
                     render_check_markdown=lambda r: "CHKMD")
    with _inject(**{"app.engine.idea_brief": ib}):
        rc, txt = _cap(INS_MOD.cmd_brief, _brief_args(check=True, branch="b.0"))
    assert rc == 1 and "no saved brief for" in txt, (rc, txt)


def test_brief_check_markdown_path_66():
    # Line 63/66 (_brief_check): non-JSON render path returns 0 with the markdown.
    ib = _FakeModule("app.engine.idea_brief",
                     check_brief=lambda t, b: {"x": 1},
                     render_check_markdown=lambda r: "CHKMD")
    with _inject(**{"app.engine.idea_brief": ib}):
        rc, txt = _cap(INS_MOD.cmd_brief, _brief_args(check=True, branch="b.0"))
    assert rc == 0 and "CHKMD" in txt, (rc, txt)


def test_brief_check_json_indent_two_63():
    # Line 63: ``json.dumps(result, indent=2)`` in _brief_check.
    ib = _FakeModule("app.engine.idea_brief",
                     check_brief=lambda t, b: {"a": 1},
                     render_check_markdown=lambda r: "CHKMD")
    with _inject(**{"app.engine.idea_brief": ib}):
        rc, txt = _cap(INS_MOD.cmd_brief,
                       _brief_args(check=True, branch="b.0", json=True))
    assert txt.splitlines()[1].startswith('  "') and not txt.splitlines()[1].startswith('   "'), txt


def test_brief_check_dispatched_before_develop_136():
    # Line 136: ``if getattr(args, "check", False)`` — check wins over develop when
    # both are set (dispatch order). We assert the CHECK path ran.
    ib = _FakeModule("app.engine.idea_brief",
                     check_brief=lambda t, b: {"x": 1},
                     render_check_markdown=lambda r: "CHKMD")
    with _inject(**{"app.engine.idea_brief": ib}):
        rc, txt = _cap(INS_MOD.cmd_brief,
                       _brief_args(check=True, develop=True, branch="b.0"))
    assert "CHKMD" in txt, txt


def test_brief_develop_none_returns_1_138():
    # Lines 138 (dispatch to develop) + _brief_develop None path.
    bd = _FakeModule("app.engine.brief_develop",
                     develop_brief=lambda *a, **k: None,
                     render_brief_develop_markdown=lambda r: "DEVMD")
    with _inject(**{"app.engine.brief_develop": bd}):
        rc, txt = _cap(INS_MOD.cmd_brief,
                       _brief_args(develop=True, branch="b.0"))
    assert rc == 1 and "No design-level idea to develop" in txt, (rc, txt)


def test_brief_develop_dry_run_hint_91():
    # Line 91: ``if not getattr(args, "apply", False)`` — dry-run prints the hint.
    result = types.SimpleNamespace(to_dict=lambda: {})
    bd = _FakeModule("app.engine.brief_develop",
                     develop_brief=lambda *a, **k: result,
                     render_brief_develop_markdown=lambda r: "DEVMD")
    with _inject(**{"app.engine.brief_develop": bd}):
        rc, txt = _cap(INS_MOD.cmd_brief,
                       _brief_args(develop=True, apply=False, branch="b.0"))
    assert "Dry run" in txt, txt


def test_brief_develop_apply_no_hint_91():
    # Line 91 (inverse): --apply suppresses the dry-run hint.
    result = types.SimpleNamespace(to_dict=lambda: {})
    bd = _FakeModule("app.engine.brief_develop",
                     develop_brief=lambda *a, **k: result,
                     render_brief_develop_markdown=lambda r: "DEVMD")
    with _inject(**{"app.engine.brief_develop": bd}):
        rc, txt = _cap(INS_MOD.cmd_brief,
                       _brief_args(develop=True, apply=True, branch="b.0"))
    assert "Dry run" not in txt, txt


def test_brief_develop_json_indent_two_88():
    # Line 88: ``json.dumps(result.to_dict(), indent=2)`` in _brief_develop.
    result = types.SimpleNamespace(to_dict=lambda: {"a": 1})
    bd = _FakeModule("app.engine.brief_develop",
                     develop_brief=lambda *a, **k: result,
                     render_brief_develop_markdown=lambda r: "DEVMD")
    with _inject(**{"app.engine.brief_develop": bd}):
        rc, txt = _cap(INS_MOD.cmd_brief,
                       _brief_args(develop=True, branch="b.0", json=True))
    assert txt.splitlines()[1].startswith('  "') and not txt.splitlines()[1].startswith('   "'), txt


def _brief_build_mods(brief, save_path="/tmp/brief.json"):
    class IPE:
        def __init__(self, *a, **k):
            pass

        def run(self, objective=None):
            return types.SimpleNamespace(ideas=[])

    ib = _FakeModule(
        "app.engine.idea_brief",
        build_brief=lambda report, branch_path, subject: brief,
        render_brief_markdown=lambda b: "BRIEFMD",
        save_brief=lambda b, t: save_path,
    )
    ip = _FakeModule("app.engine.idea_permutation", IdeaPermutationEngine=IPE)
    return {"app.engine.idea_brief": ib, "app.engine.idea_permutation": ip}


def test_brief_build_none_returns_1_114():
    # Lines 112/114 (_brief_build): build_brief None → message + return 1.
    with _inject(**_brief_build_mods(None)):
        rc, txt = _cap(INS_MOD.cmd_brief, _brief_args(branch="b.0"))
    assert rc == 1 and "No design-level idea to brief" in txt, (rc, txt)


def test_brief_build_markdown_returns_0_123():
    # Line 123 (_brief_build): default render path returns 0.
    brief = types.SimpleNamespace(branch_path="b.0", to_dict=lambda: {})
    with _inject(**_brief_build_mods(brief)):
        rc, txt = _cap(INS_MOD.cmd_brief, _brief_args(branch="b.0"))
    assert rc == 0 and "BRIEFMD" in txt, (rc, txt)


def test_brief_build_save_prints_path_119():
    # Line 119: ``if getattr(args, "save", False)`` — save path prints baseline note.
    brief = types.SimpleNamespace(branch_path="b.0", to_dict=lambda: {})
    with _inject(**_brief_build_mods(brief, save_path="/tmp/x.json")):
        rc, txt = _cap(INS_MOD.cmd_brief, _brief_args(branch="b.0", save=True))
    assert "Evidence baseline saved to /tmp/x.json" in txt, txt


def test_brief_build_no_save_no_note_119():
    # Line 119 (inverse): without --save the baseline note is absent.
    brief = types.SimpleNamespace(branch_path="b.0", to_dict=lambda: {})
    with _inject(**_brief_build_mods(brief)):
        rc, txt = _cap(INS_MOD.cmd_brief, _brief_args(branch="b.0", save=False))
    assert "Evidence baseline saved" not in txt, txt


def test_brief_build_json_indent_two_116():
    # Line 116: ``json.dumps(brief.to_dict(), indent=2)`` in _brief_build.
    brief = types.SimpleNamespace(branch_path="b.0", to_dict=lambda: {"a": 1})
    with _inject(**_brief_build_mods(brief)):
        rc, txt = _cap(INS_MOD.cmd_brief, _brief_args(branch="b.0", json=True))
    assert txt.splitlines()[1].startswith('  "') and not txt.splitlines()[1].startswith('   "'), txt


# --------------------------------------------------------------------------
# cmd_dream (lines 143-155)
# --------------------------------------------------------------------------

def _dream_mods(report):
    dm = _FakeModule("app.engine.dream",
                     dream=lambda t, curate=False, learn_gates=False: report,
                     render_dream_markdown=lambda r: "DREAMMD")
    return {"app.engine.dream": dm}


def test_dream_digest_path_printed_153():
    # Line 153: ``if report.digest_path`` — a truthy digest path is reported.
    rep = types.SimpleNamespace(digest_path="/tmp/d.md", to_dict=lambda: {})
    with _inject(**_dream_mods(rep)):
        rc, txt = _cap(INS_MOD.cmd_dream,
                       _ns(target="", curate=False, json=False))
    assert rc == 0 and "Digest written to /tmp/d.md" in txt, (rc, txt)


def test_dream_no_digest_path_silent_153():
    # Line 153 (inverse): falsy digest path → no digest line.
    rep = types.SimpleNamespace(digest_path="", to_dict=lambda: {})
    with _inject(**_dream_mods(rep)):
        rc, txt = _cap(INS_MOD.cmd_dream,
                       _ns(target="", curate=False, json=False))
    assert "Digest written" not in txt, txt


def test_dream_json_indent_two_150():
    # Line 150: ``json.dumps(report.to_dict(), indent=2)``.
    rep = types.SimpleNamespace(digest_path="", to_dict=lambda: {"a": 1})
    with _inject(**_dream_mods(rep)):
        rc, txt = _cap(INS_MOD.cmd_dream,
                       _ns(target="", curate=False, json=True))
    assert txt.splitlines()[1].startswith('  "') and not txt.splitlines()[1].startswith('   "'), txt


# --------------------------------------------------------------------------
# cmd_outcomes (lines 158-181)
# --------------------------------------------------------------------------

def _outcomes_mods(report, rubric_rel="rubric.json", init_path="init.json"):
    oc = _FakeModule("app.engine.outcomes",
                     RUBRIC_REL=rubric_rel,
                     evaluate=lambda t: report,
                     init_rubric=lambda t: init_path,
                     render_outcomes_markdown=lambda r: "OUTMD")
    return {"app.engine.outcomes": oc}


def test_outcomes_init_returns_0_172():
    # Lines 168/172: --init writes rubric and returns 0.
    with _inject(**_outcomes_mods(None, init_path="/tmp/r.json")):
        rc, txt = _cap(INS_MOD.cmd_outcomes,
                       _ns(target="", init=True, json=False))
    assert rc == 0 and "Starter rubric written to /tmp/r.json" in txt, (rc, txt)


def test_outcomes_no_rubric_returns_1_176():
    # Lines 174/176: evaluate None → message + return 1.
    with _inject(**_outcomes_mods(None, rubric_rel="RUB.json")):
        rc, txt = _cap(INS_MOD.cmd_outcomes,
                       _ns(target="", init=False, json=False))
    assert rc == 1 and "no rubric at RUB.json" in txt, (rc, txt)


def test_outcomes_passed_returns_0_181():
    # Line 181: ``return 0 if report.passed else 1`` — passed → 0.
    rep = types.SimpleNamespace(passed=True, to_dict=lambda: {})
    with _inject(**_outcomes_mods(rep)):
        rc, txt = _cap(INS_MOD.cmd_outcomes,
                       _ns(target="", init=False, json=False))
    assert rc == 0 and "OUTMD" in txt, (rc, txt)


def test_outcomes_failed_returns_1_181():
    # Line 181 (the ``else 1``): not passed → 1.
    rep = types.SimpleNamespace(passed=False, to_dict=lambda: {})
    with _inject(**_outcomes_mods(rep)):
        rc, txt = _cap(INS_MOD.cmd_outcomes,
                       _ns(target="", init=False, json=False))
    assert rc == 1, rc


def test_outcomes_json_indent_two_178():
    # Line 178: ``json.dumps(report.to_dict(), indent=2)``.
    rep = types.SimpleNamespace(passed=True, to_dict=lambda: {"a": 1})
    with _inject(**_outcomes_mods(rep)):
        rc, txt = _cap(INS_MOD.cmd_outcomes,
                       _ns(target="", init=False, json=True))
    assert txt.splitlines()[1].startswith('  "') and not txt.splitlines()[1].startswith('   "'), txt


# --------------------------------------------------------------------------
# cmd_recipes / cmd_changelog / cmd_impact / cmd_duplication / cmd_mutants
# JSON indent + numeric defaults (lines 191, 230, 255, 270-273, 294)
# --------------------------------------------------------------------------

def test_recipes_json_indent_two_191():
    # Line 191: ``json.dumps(..., indent=2)`` in cmd_recipes.
    r1 = types.SimpleNamespace(to_dict=lambda: {"a": 1})
    rec = _FakeModule("app.execution.recipes", RECIPES={"r": r1},
                      COMPOSITES={"c": ["a"]},
                      render_recipes_markdown=lambda: "RECMD")
    with _inject(**{"app.execution.recipes": rec}):
        rc, txt = _cap(INS_MOD.cmd_recipes, _ns(json=True))
    assert txt.splitlines()[1].startswith('  "') and not txt.splitlines()[1].startswith('   "'), txt


def test_impact_json_indent_two_255():
    # Line 255: ``json.dumps(..., indent=2)`` in cmd_impact.
    class Graph:
        @staticmethod
        def build(root):
            return Graph()

        def definitions(self, fn):
            return []

        def direct_callers(self, fn):
            return []

        def blast_radius(self, fn):
            return []

    cg = _FakeModule("app.engine.call_graph", CallGraph=Graph,
                     render_impact_markdown=lambda fn, g: "IMPMD")
    with _inject(**{"app.engine.call_graph": cg}):
        rc, txt = _cap(INS_MOD.cmd_impact,
                       _ns(target="", function="foo", json=True))
    assert txt.splitlines()[1].startswith('  "') and not txt.splitlines()[1].startswith('   "'), txt


def test_cmd_impact_markdown_returns_zero_258():
    # Line 258: cmd_impact non-JSON path returns 0 (kills the 0->1 / value->None
    # flips on the trailing ``return 0``).
    class Graph:
        @staticmethod
        def build(root):
            return Graph()

    cg = _FakeModule("app.engine.call_graph", CallGraph=Graph,
                     render_impact_markdown=lambda fn, g: "IMPMD")
    with _inject(**{"app.engine.call_graph": cg}):
        rc, txt = _cap(INS_MOD.cmd_impact,
                       _ns(target="", function="foo", json=False))
    assert rc == 0 and "IMPMD" in txt, (rc, txt)


def test_duplication_min_statements_default_270():
    # Line 270: ``getattr(args, "min_statements", 5)`` default — with no attr the
    # default 5 must reach find_duplicates (flip to 6 changes the arg).
    cap = {}

    def find_duplicates(root, min_statements=5, min_occurrences=2):
        cap["min_statements"] = min_statements
        cap["min_occurrences"] = min_occurrences
        return []

    dd = _FakeModule("app.engine.dedup", find_duplicates=find_duplicates,
                     render_duplicates_markdown=lambda b: "DUPMD")
    args = argparse.Namespace(target="", json=False)
    with _inject(**{"app.engine.dedup": dd}):
        INS_MOD.cmd_duplication(args)
    assert cap["min_statements"] == 5 and cap["min_occurrences"] == 2, cap


def test_duplication_json_indent_two_273():
    # Line 273: ``json.dumps(..., indent=2)`` in cmd_duplication.
    block = types.SimpleNamespace(to_dict=lambda: {"a": 1})
    dd = _FakeModule("app.engine.dedup",
                     find_duplicates=lambda *a, **k: [block],
                     render_duplicates_markdown=lambda b: "DUPMD")
    args = argparse.Namespace(target="", min_statements=5, json=True)
    with _inject(**{"app.engine.dedup": dd}):
        rc, txt = _cap(INS_MOD.cmd_duplication, args)
    # Top-level is a JSON array; the inner key line carries the 4-space indent
    # that indent=2 produces (a flip to indent=3 would widen it to 6 spaces).
    key_line = next(ln for ln in txt.splitlines() if '"a"' in ln)
    assert key_line.startswith('    "a"') and not key_line.startswith('     "a"'), txt


def test_mutants_json_indent_two_294():
    # Line 294: ``json.dumps(result.to_dict(), indent=2)`` in cmd_mutants.
    result = types.SimpleNamespace(to_dict=lambda: {"a": 1})
    mt = _FakeModule("app.engine.mutation_tester",
                     mutation_score=lambda *a, **k: result,
                     render_mutation_markdown=lambda r: "MUTMD")
    args = argparse.Namespace(target="", module="app/x.py", max_mutants=30,
                              timeout=120, json=True)
    with _inject(**{"app.engine.mutation_tester": mt}):
        rc, txt = _cap(INS_MOD.cmd_mutants, args)
    assert rc == 0
    assert txt.splitlines()[1].startswith('  "') and not txt.splitlines()[1].startswith('   "'), txt


# --------------------------------------------------------------------------
# _proof_tally / _coerce_count / _read_proof_of_fix (lines 335-380, 405-415)
# --------------------------------------------------------------------------

def test_coerce_count_none_falls_back_376():
    # Line 375/376: value is None → return fallback (not None, not 0).
    assert INS_MOD._coerce_count(None, 7) == 7


def test_coerce_count_bad_value_falls_back_380():
    # Line 378/380: non-coercible value → return fallback.
    assert INS_MOD._coerce_count("not-a-number", 9) == 9


def test_coerce_count_real_value_wins_378():
    # Line 378: a coercible value wins over fallback.
    assert INS_MOD._coerce_count("12", 0) == 12


def test_proof_tally_totals_win_over_count_397_398():
    # Lines 397/398: recorded totals win when ``totals`` is present.
    proof = {
        "totals": {"applied": 5, "rolled_back": 2},
        "fixes": [{"outcome": "applied"}],  # count would be 1, but totals win
    }
    landed, reverted = INS_MOD._proof_tally(proof)
    assert (landed, reverted) == (5, 2)


def test_proof_tally_count_fallback_when_no_totals_395_396():
    # Lines 395/396: no totals → count outcomes from fixes.
    proof = {"fixes": [{"outcome": "applied"}, {"outcome": "applied"},
                       {"outcome": "rolled_back"}]}
    landed, reverted = INS_MOD._proof_tally(proof)
    assert (landed, reverted) == (2, 1)


def test_proof_tally_missing_total_key_uses_count_397():
    # Line 397: totals present but missing 'applied' key → fall back to count.
    proof = {"totals": {"rolled_back": 0},
             "fixes": [{"outcome": "applied"}, {"outcome": "applied"}]}
    landed, reverted = INS_MOD._proof_tally(proof)
    assert landed == 2


def test_read_proof_of_fix_missing_returns_empty(tmp_path):
    # Lines 359-366: missing file → {} (read defensively).
    assert INS_MOD._read_proof_of_fix(tmp_path) == {}


def test_read_proof_of_fix_corrupt_returns_empty_365(tmp_path):
    # Line 365: invalid JSON → {} not a crash.
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text("{not json", encoding="utf-8")
    assert INS_MOD._read_proof_of_fix(tmp_path) == {}


def test_read_proof_of_fix_non_dict_returns_empty_366(tmp_path):
    # Line 366: valid JSON but not a dict → {}.
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert INS_MOD._read_proof_of_fix(tmp_path) == {}


def test_read_proof_of_fix_real_dict(tmp_path):
    # Lines 363/366: a real dict is returned verbatim.
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text('{"k": 1}', encoding="utf-8")
    assert INS_MOD._read_proof_of_fix(tmp_path) == {"k": 1}


# --------------------------------------------------------------------------
# _reliability_table (lines 405-415)
# --------------------------------------------------------------------------

def test_reliability_table_merges_both_views_405():
    # Line 405: rows come from BOTH most_reliable AND least_reliable.
    mem = {
        "most_reliable": [{"key": "a", "success_rate": 0.9, "samples": 4}],
        "least_reliable": [{"key": "b", "success_rate": 0.1, "samples": 2}],
    }
    rows = INS_MOD._reliability_table(mem)
    keys = {r["key"] for r in rows}
    assert keys == {"a", "b"}, rows


def test_reliability_table_skips_blank_key_409():
    # Line 409: ``if key and key not in by_key`` — a blank key is skipped.
    mem = {"most_reliable": [{"key": "", "success_rate": 0.5, "samples": 1},
                             {"key": "a", "success_rate": 0.5, "samples": 1}]}
    rows = INS_MOD._reliability_table(mem)
    assert [r["key"] for r in rows] == ["a"], rows


def test_reliability_table_dedup_first_wins_409():
    # Line 409: ``key not in by_key`` — a duplicate key keeps the FIRST occurrence.
    mem = {"most_reliable": [{"key": "a", "success_rate": 0.9, "samples": 4}],
           "least_reliable": [{"key": "a", "success_rate": 0.1, "samples": 9}]}
    rows = INS_MOD._reliability_table(mem)
    assert len(rows) == 1 and rows[0]["samples"] == 4, rows


def test_reliability_table_success_rate_default_412():
    # Line 412: ``float(row.get("success_rate", 0.0))`` — missing key → 0.0.
    mem = {"most_reliable": [{"key": "a", "samples": 3}]}
    rows = INS_MOD._reliability_table(mem)
    assert rows[0]["success_rate"] == 0.0, rows


def test_reliability_table_samples_default_413():
    # Line 413: ``int(row.get("samples", 0))`` — missing key → 0.
    mem = {"most_reliable": [{"key": "a", "success_rate": 0.5}]}
    rows = INS_MOD._reliability_table(mem)
    assert rows[0]["samples"] == 0, rows


def test_reliability_table_sorted_by_rate_desc_415():
    # Line 415: sorted by (-success_rate, key) — higher rate first.
    mem = {"most_reliable": [{"key": "lo", "success_rate": 0.2, "samples": 1},
                             {"key": "hi", "success_rate": 0.8, "samples": 1}]}
    rows = INS_MOD._reliability_table(mem)
    assert [r["key"] for r in rows] == ["hi", "lo"], rows


# --------------------------------------------------------------------------
# _trackrecord (lines 435-443) + render_trackrecord_markdown (459-498)
# --------------------------------------------------------------------------

def _mem_stub(summary):
    class IM:
        @staticmethod
        def load(root):
            return IM()

        def summary(self):
            return summary

    return {"app.engine.idea_memory": _FakeModule(
        "app.engine.idea_memory", IdeaMemory=IM)}


def test_trackrecord_has_record_when_landed_positive_435(tmp_path):
    # Line 435: ``landed > 0 or bool(by_type)`` — landed>0 alone sets has_record.
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text(
        '{"totals": {"applied": 3, "rolled_back": 0}}', encoding="utf-8")
    with _inject(**_mem_stub({"operators_tracked": 0})):
        rec = INS_MOD._trackrecord(tmp_path)
    assert rec["has_record"] is True and rec["verified_fixes"] == 3, rec


def test_trackrecord_no_record_when_empty_435(tmp_path):
    # Line 435 (boundary): landed==0 AND no by_type → has_record False.
    with _inject(**_mem_stub({"operators_tracked": 0})):
        rec = INS_MOD._trackrecord(tmp_path)
    assert rec["has_record"] is False, rec


def test_trackrecord_has_record_when_bytype_only_435(tmp_path):
    # Line 435: ``or bool(by_type)`` — by_type alone (landed==0) sets has_record.
    with _inject(**_mem_stub(
            {"operators_tracked": 1,
             "most_reliable": [{"key": "a", "success_rate": 0.5, "samples": 2}]})):
        rec = INS_MOD._trackrecord(tmp_path)
    assert rec["has_record"] is True and rec["verified_fixes"] == 0, rec


def test_trackrecord_operators_tracked_default_439(tmp_path):
    # Line 439: ``int(mem.get("operators_tracked", 0) or 0)`` — missing → 0.
    with _inject(**_mem_stub({})):
        rec = INS_MOD._trackrecord(tmp_path)
    assert rec["operators_tracked"] == 0, rec


def test_render_trackrecord_no_record_message():
    # Lines 452-454: no record → the "no track record yet" message.
    out = INS_MOD.render_trackrecord_markdown(
        {"has_record": False, "verified_fixes": 0, "rolled_back": 0,
         "by_type": []})
    assert "no track record yet" in out, out


def test_render_trackrecord_singular_fix_459():
    # Line 459: ``"fix" if landed == 1 else "fixes"`` — exactly 1 → singular.
    out = INS_MOD.render_trackrecord_markdown(
        {"has_record": True, "verified_fixes": 1, "rolled_back": 0,
         "by_type": []})
    assert "**1 fix**" in out and "**1 fixes**" not in out, out


def test_render_trackrecord_plural_fix_459():
    # Line 459 (else): 2 → plural.
    out = INS_MOD.render_trackrecord_markdown(
        {"has_record": True, "verified_fixes": 2, "rolled_back": 0,
         "by_type": []})
    assert "**2 fixes**" in out, out


def test_render_trackrecord_reverted_singular_465():
    # Line 465: ``"attempt" if reverted == 1 else "attempts"``.
    out = INS_MOD.render_trackrecord_markdown(
        {"has_record": True, "verified_fixes": 1, "rolled_back": 1,
         "by_type": []})
    assert "1 attempt were" in out and "1 attempts" not in out, out


def test_render_trackrecord_no_reverted_section_464():
    # Line 464: ``if reverted`` — zero reverted → no rollback sentence.
    out = INS_MOD.render_trackrecord_markdown(
        {"has_record": True, "verified_fixes": 1, "rolled_back": 0,
         "by_type": []})
    assert "rolled back automatically" not in out, out


def test_render_trackrecord_samples_singular_480():
    # Line 480: ``"sample" if samples == 1 else "samples"``.
    out = INS_MOD.render_trackrecord_markdown(
        {"has_record": True, "verified_fixes": 1, "rolled_back": 0,
         "by_type": [{"key": "a", "success_rate": 0.5, "samples": 1}]})
    assert "over 1 sample " in out, out


def test_render_trackrecord_reliable_floor_boundary_481():
    # Line 481: ``>= _RELIABLE_FLOOR`` (0.75) — exactly 0.75 is reliable.
    out = INS_MOD.render_trackrecord_markdown(
        {"has_record": True, "verified_fixes": 1, "rolled_back": 0,
         "by_type": [{"key": "a", "success_rate": 0.75, "samples": 3}]})
    assert "reliable — lead with this" in out, out


def test_render_trackrecord_just_below_floor_mixed_481():
    # Line 481 (boundary): 0.74 is NOT reliable → "mixed" (kills >= -> >).
    out = INS_MOD.render_trackrecord_markdown(
        {"has_record": True, "verified_fixes": 1, "rolled_back": 0,
         "by_type": [{"key": "a", "success_rate": 0.74, "samples": 3}]})
    assert "reliable — lead with this" not in out and "(mixed)" in out, out


def test_render_trackrecord_risky_ceil_boundary_483():
    # Line 483: ``<= _RISKY_CEIL`` (0.40) — exactly 0.40 is risky.
    out = INS_MOD.render_trackrecord_markdown(
        {"has_record": True, "verified_fixes": 1, "rolled_back": 0,
         "by_type": [{"key": "a", "success_rate": 0.40, "samples": 3}]})
    assert "risky — expect blocks/rollbacks" in out, out


def test_render_trackrecord_just_above_ceil_mixed_483():
    # Line 483 (boundary): 0.41 is NOT risky → "mixed" (kills <= -> <).
    out = INS_MOD.render_trackrecord_markdown(
        {"has_record": True, "verified_fixes": 1, "rolled_back": 0,
         "by_type": [{"key": "a", "success_rate": 0.41, "samples": 3}]})
    assert "risky — expect blocks/rollbacks" not in out and "(mixed)" in out, out


def test_render_trackrecord_pct_rounded_478():
    # Line 478: ``round(row["success_rate"] * 100)`` — 0.5 → 50%.
    out = INS_MOD.render_trackrecord_markdown(
        {"has_record": True, "verified_fixes": 1, "rolled_back": 0,
         "by_type": [{"key": "a", "success_rate": 0.5, "samples": 2}]})
    assert "50% landed" in out, out


def test_module_reliable_risky_constants():
    # Lines 446/447: the documented thresholds.
    assert INS_MOD._RELIABLE_FLOOR == 0.75
    assert INS_MOD._RISKY_CEIL == 0.40


# --------------------------------------------------------------------------
# _SCOPE_EMPTY_REPORT (lines 514-522)
# --------------------------------------------------------------------------

def test_scope_empty_report_constants_515_519():
    # Lines 515-519: the empty-repo report shape.
    r = INS_MOD._SCOPE_EMPTY_REPORT
    assert r["source_file_count"] == 0
    assert r["python_file_count"] == 0
    assert r["analyzed_pct"] == 100
    assert r["out_of_scope_pct"] == 0
    assert r["all_python"] is True


# --------------------------------------------------------------------------
# _scope_file_entry / _scope_file_line / _scope_report (lines 535-614)
# --------------------------------------------------------------------------

def _fact(path="a.js", language="javascript", loc=10, churn=2, debt=0):
    return types.SimpleNamespace(path=path, language=language, loc=loc,
                                 churn=churn, debt_markers=debt)


def test_scope_file_entry_has_test_exact_stem_545():
    # Line 545: ``stem in test_stems`` — exact stem match → has_test True.
    entry = INS_MOD._scope_file_entry(_fact(path="foo.js"), {"foo"})
    assert entry["has_test"] is True


def test_scope_file_entry_substring_match_545():
    # Line 545: ``any(stem in t for t in test_stems)`` — substring match.
    entry = INS_MOD._scope_file_entry(_fact(path="foo.js"), {"test_foo_extra"})
    assert entry["has_test"] is True


def test_scope_file_entry_no_test_545():
    # Line 545 (both branches false): no matching stem → has_test False.
    entry = INS_MOD._scope_file_entry(_fact(path="foo.js"), {"bar"})
    assert entry["has_test"] is False


def test_scope_file_entry_debt_included_only_when_positive_554():
    # Line 553/554: ``if debt > 0`` — positive debt is recorded.
    entry = INS_MOD._scope_file_entry(_fact(debt=3), set())
    assert entry["debt_markers"] == 3


def test_scope_file_entry_debt_zero_omitted_554():
    # Line 554 (boundary): debt==0 → key omitted entirely.
    entry = INS_MOD._scope_file_entry(_fact(debt=0), set())
    assert "debt_markers" not in entry


def test_scope_file_line_singular_commit_652():
    # Line 652: ``"commit" if f["churn"] == 1 else "commits"``.
    line = INS_MOD._scope_file_line(
        {"path": "a.js", "language": "js", "loc": 5, "churn": 1,
         "has_test": True})
    assert "1 commit)" in line and "1 commits" not in line, line


def test_scope_file_line_plural_commits_652():
    line = INS_MOD._scope_file_line(
        {"path": "a.js", "language": "js", "loc": 5, "churn": 3,
         "has_test": True})
    assert "3 commits)" in line, line


def test_scope_file_line_no_test_flag():
    # The ``— no test found`` flag when has_test is False.
    line = INS_MOD._scope_file_line(
        {"path": "a.js", "language": "js", "loc": 5, "churn": 2,
         "has_test": False})
    assert "no test found" in line, line


def test_scope_file_line_debt_clause_656():
    # Line 656: ``f.get("debt_markers", 0) or 0`` then ``if debt > 0`` clause.
    line = INS_MOD._scope_file_line(
        {"path": "a.js", "language": "js", "loc": 5, "churn": 2,
         "has_test": True, "debt_markers": 4})
    assert "4 TODO/FIXME" in line, line


def test_scope_file_line_no_debt_clause_656():
    line = INS_MOD._scope_file_line(
        {"path": "a.js", "language": "js", "loc": 5, "churn": 2,
         "has_test": True})
    assert "TODO/FIXME" not in line, line


def _profile_stub(**over):
    base = dict(source_file_count=5, python_file_count=3, analyzed_ratio=0.6,
                out_of_scope_ratio=0.4, language_breakdown={"js": 2},
                test_files=[])
    base.update(over)
    return types.SimpleNamespace(**base)


def _scope_report_mods(profile, facts=(), cross=()):
    pp = _FakeModule(
        "app.tools.project_profile",
        ProjectProfiler=lambda root: types.SimpleNamespace(
            profile=lambda light=True: profile),
    )
    pf = _FakeModule("app.tools.polyglot_facts",
                     scan_polyglot_facts=lambda root: list(facts))
    cl = _FakeModule("app.engine.cross_language_coupling",
                     cross_language_coupling=lambda root: list(cross))
    return {"app.tools.project_profile": pp,
            "app.tools.polyglot_facts": pf,
            "app.engine.cross_language_coupling": cl}


def test_scope_report_empty_when_no_source_595(tmp_path):
    # Line 595: ``profile is None or profile.source_file_count <= 0`` — zero
    # source files → the empty (all-Python) shape.
    prof = _profile_stub(source_file_count=0)
    with _inject(**_scope_report_mods(prof)):
        rep = INS_MOD._scope_report(tmp_path)
    assert rep == dict(INS_MOD._SCOPE_EMPTY_REPORT)


def test_scope_report_not_empty_at_boundary_595(tmp_path):
    # Line 595 boundary (<= -> <): source_file_count==1 must NOT be empty.
    prof = _profile_stub(source_file_count=1, language_breakdown={"js": 1})
    with _inject(**_scope_report_mods(prof, facts=[_fact()])):
        rep = INS_MOD._scope_report(tmp_path)
    assert rep["source_file_count"] == 1, rep


def test_scope_report_all_python_false_when_out_of_scope_600(tmp_path):
    # Line 600: ``not (out_of_scope_ratio > 0 and language_breakdown)`` — a repo
    # with out-of-scope files and a breakdown is NOT all-Python.
    prof = _profile_stub(out_of_scope_ratio=0.4, language_breakdown={"js": 2})
    with _inject(**_scope_report_mods(prof, facts=[_fact()])):
        rep = INS_MOD._scope_report(tmp_path)
    assert rep["all_python"] is False, rep


def test_scope_report_all_python_true_when_ratio_zero_600(tmp_path):
    # Line 600 (boundary > -> >=): out_of_scope_ratio==0 → all_python True.
    prof = _profile_stub(out_of_scope_ratio=0.0, language_breakdown={})
    with _inject(**_scope_report_mods(prof)):
        rep = INS_MOD._scope_report(tmp_path)
    assert rep["all_python"] is True, rep


def test_scope_report_pct_rounding_608_609(tmp_path):
    # Lines 608/609: ``round(analyzed_ratio * 100)`` / ``round(out_of_scope * 100)``.
    prof = _profile_stub(analyzed_ratio=0.6, out_of_scope_ratio=0.4,
                         language_breakdown={"js": 2})
    with _inject(**_scope_report_mods(prof, facts=[_fact()])):
        rep = INS_MOD._scope_report(tmp_path)
    assert rep["analyzed_pct"] == 60 and rep["out_of_scope_pct"] == 40, rep


def test_scope_profile_failure_collapses_to_none_530(tmp_path):
    # Line 530: a profiler exception collapses to None (→ empty report).
    class Boom:
        def __init__(self, root):
            pass

        def profile(self, light=True):
            raise RuntimeError("boom")

    pp = _FakeModule("app.tools.project_profile", ProjectProfiler=Boom)
    with _inject(**{"app.tools.project_profile": pp}):
        assert INS_MOD._scope_profile(tmp_path) is None


# --------------------------------------------------------------------------
# _scope_breakdown_lines / _scope_cross_lines (lines 636-691)
# --------------------------------------------------------------------------

def test_scope_breakdown_singular_file_644():
    # Line 644: ``"file" if n == 1 else "files"``.
    lines = INS_MOD._scope_breakdown_lines([{"language": "js", "files": 1}])
    body = "\n".join(lines)
    assert "1 file" in body and "1 files" not in body, body


def test_scope_breakdown_plural_files_644():
    lines = INS_MOD._scope_breakdown_lines([{"language": "js", "files": 2}])
    assert "2 files" in "\n".join(lines)


def test_scope_breakdown_empty_returns_nothing():
    assert INS_MOD._scope_breakdown_lines([]) == []


def test_scope_cross_singular_cochange_685():
    # Line 685: ``"co-change" if c["cochanges"] == 1 else "co-changes"``.
    lines = INS_MOD._scope_cross_lines(
        [{"py": "a.py", "other": "b.js", "language": "js", "cochanges": 1}])
    body = "\n".join(lines)
    assert "1 co-change)" in body and "1 co-changes" not in body, body


def test_scope_cross_plural_cochanges_685():
    lines = INS_MOD._scope_cross_lines(
        [{"py": "a.py", "other": "b.js", "language": "js", "cochanges": 3}])
    assert "3 co-changes)" in "\n".join(lines)


def test_scope_cross_empty_returns_nothing():
    assert INS_MOD._scope_cross_lines([]) == []


def test_scope_files_lines_accumulate_671():
    # Line 671: ``lines += [...]`` (augmented append) — every file becomes a bullet.
    files = [{"path": "a.js", "language": "js", "loc": 5, "churn": 2,
              "has_test": True},
             {"path": "b.js", "language": "js", "loc": 6, "churn": 1,
              "has_test": True}]
    lines = INS_MOD._scope_files_lines(files)
    body = "\n".join(lines)
    assert "`a.js`" in body and "`b.js`" in body, body


def test_scope_all_python_lines_structure_703():
    # Lines 703-705 (augmented appends building the all-python block).
    out = "\n".join(INS_MOD._scope_all_python_lines())
    assert "100% of this repo (all Python)" in out, out


# --------------------------------------------------------------------------
# argparse defaults via register_parsers (lines 735, 760, 770, 773, 775,
# 792-794, 804, 888-890)
# --------------------------------------------------------------------------

def _build_parser():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    INS_MOD.register_parsers(sub)
    return parser


def test_grade_min_score_default_zero_735():
    # Line 735: grade --min-score default 0.
    args = _build_parser().parse_args(["grade"])
    assert args.min_score == 0


def test_duplication_min_statements_default_five_760():
    # Line 760: duplication --min-statements default 5.
    args = _build_parser().parse_args(["duplication"])
    assert args.min_statements == 5


def test_mutants_max_mutants_default_thirty_773():
    # Line 773: mutants --max-mutants default 30 (the very cap this file is past).
    args = _build_parser().parse_args(["mutants", "--module", "app/x.py"])
    assert args.max_mutants == 30


def test_mutants_timeout_default_120_775():
    # Line 775: mutants --timeout default 120.
    args = _build_parser().parse_args(["mutants", "--module", "app/x.py"])
    assert args.timeout == 120


def test_mutants_json_default_false_770():
    # Line 770: mutants --json default False (store_true).
    args = _build_parser().parse_args(["mutants", "--module", "app/x.py"])
    assert args.json is False


def test_brief_depth_breadth_maxideas_defaults_792_794():
    # Lines 792-794: brief --depth 2, --breadth 4, --max-ideas 40.
    args = _build_parser().parse_args(["brief"])
    assert args.depth == 2 and args.breadth == 4 and args.max_ideas == 40


def test_brief_max_steps_default_25_804():
    # Line 804: brief --max-steps default 25.
    args = _build_parser().parse_args(["brief"])
    assert args.max_steps == 25


def test_explain_depth_breadth_maxideas_defaults_888_890():
    # Lines 888-890: explain --depth 2, --breadth 4, --max-ideas 40.
    args = _build_parser().parse_args(["explain"])
    assert args.depth == 2 and args.breadth == 4 and args.max_ideas == 40


# --------------------------------------------------------------------------
# cmd_objectives / _objective_reachability (lines 339, 348, 325-349)
# --------------------------------------------------------------------------

def _objectives_mods(registered, fmap):
    fd = _FakeModule("app.engine.facet_develop", FACET_OBJECTIVE_MAP=fmap)
    oc = _FakeModule("app.engine.objective_compiler",
                     available_objectives=lambda: registered)
    return {"app.engine.facet_develop": fd,
            "app.engine.objective_compiler": oc}


def test_objective_reachability_intersection_315():
    # Line 315: reachable == mapped values ∩ registered (a mapped-but-retired
    # objective is NOT reachable).
    with _inject(**_objectives_mods(["a", "b"], {"f1": "a", "f2": "gone"})):
        registered, reachable = INS_MOD._objective_reachability()
    assert registered == ["a", "b"] and reachable == {"a"}, (registered, reachable)


def test_cmd_objectives_text_counts_348(capsys):
    # Lines 345/348: ``n - m`` not-yet-wired count in the summary line.
    with _inject(**_objectives_mods(["a", "b", "c"], {"f": "a"})):
        rc = INS_MOD.cmd_objectives(_ns(json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "3 objectives, 1 reachable" in out and "2 not yet wired" in out, out


def test_cmd_objectives_json_reachable_flag_339(capsys):
    # Line 333/339: JSON shape lists unreachable objectives and counts.
    with _inject(**_objectives_mods(["a", "b"], {"f": "a"})):
        INS_MOD.cmd_objectives(_ns(json=True))
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["reachable"] == ["a"]
    assert data["unreachable"] == ["b"]
    assert data["reachable_count"] == 1 and data["unreachable_count"] == 1


def test_cmd_objectives_json_indent_two_336(capsys):
    # Line 336: ``json.dumps(..., indent=2)`` in cmd_objectives.
    with _inject(**_objectives_mods(["a"], {})):
        INS_MOD.cmd_objectives(_ns(json=True))
    out = capsys.readouterr().out
    assert out.splitlines()[1].startswith('  "') and not out.splitlines()[1].startswith('   "'), out


# --------------------------------------------------------------------------
# getattr(args, X, False/True) DEFAULTS — exercised by OMITTING the attribute
# so the seeded default flip changes the branch taken (lines 91, 119, 136,
# 138, 148, 168, 222, 234, 325).
# --------------------------------------------------------------------------

def _brief_develop_stub(result):
    return {"app.engine.brief_develop": _FakeModule(
        "app.engine.brief_develop",
        develop_brief=lambda *a, **k: result,
        render_brief_develop_markdown=lambda r: "DEVMD")}


def test_brief_develop_apply_default_false_91():
    # Line 91: ``not getattr(args, "apply", False)`` — with NO apply attr the
    # default False → ``not False`` → the dry-run hint prints (flip to True hides it).
    result = types.SimpleNamespace(to_dict=lambda: {})
    args = argparse.Namespace(target="", branch="b.0", subject="", objective="",
                              depth=2, breadth=4, max_ideas=40, max_steps=25,
                              no_verify=False, json=False)
    with _inject(**_brief_develop_stub(result)):
        rc, txt = _cap(INS_MOD._brief_develop, args, Path("."), "b.0")
    assert "Dry run" in txt, txt


def test_brief_build_save_default_false_119():
    # Line 119: ``getattr(args, "save", False)`` — with NO save attr the default
    # False → no baseline note (flip to True would save unexpectedly).
    brief = types.SimpleNamespace(branch_path="b.0", to_dict=lambda: {})
    args = argparse.Namespace(target="", branch="b.0", subject="", objective="",
                              depth=2, breadth=4, max_ideas=40, json=False)
    with _inject(**_brief_build_mods(brief)):
        rc, txt = _cap(INS_MOD._brief_build, args, Path("."), "b.0")
    assert "Evidence baseline saved" not in txt, txt


def test_cmd_brief_check_default_false_136():
    # Line 136: ``getattr(args, "check", False)`` — NO check attr → default False,
    # so we do NOT enter the check path (would otherwise need a branch).
    brief = types.SimpleNamespace(branch_path="b.0", to_dict=lambda: {})
    args = argparse.Namespace(target="", branch="b.0", subject="", objective="",
                              depth=2, breadth=4, max_ideas=40, json=False)
    with _inject(**_brief_build_mods(brief)):
        rc, txt = _cap(INS_MOD.cmd_brief, args)
    # Default-False check → build path ran (BRIEFMD), not the check path.
    assert rc == 0 and "BRIEFMD" in txt, (rc, txt)


def test_cmd_brief_develop_default_false_138():
    # Line 138: ``getattr(args, "develop", False)`` — NO develop attr → build path.
    brief = types.SimpleNamespace(branch_path="b.0", to_dict=lambda: {})
    args = argparse.Namespace(target="", branch="b.0", subject="", objective="",
                              depth=2, breadth=4, max_ideas=40, json=False)
    with _inject(**_brief_build_mods(brief)):
        rc, txt = _cap(INS_MOD.cmd_brief, args)
    assert rc == 0 and "BRIEFMD" in txt, (rc, txt)


def test_cmd_dream_curate_default_false_148():
    # Line 148: ``curate=getattr(args, "curate", False)`` — NO curate attr → the
    # default False is forwarded to dream() (flip to True would curate).
    cap = {}

    def dream(t, curate=False, learn_gates=False):
        cap["curate"] = curate
        return types.SimpleNamespace(digest_path="", to_dict=lambda: {})

    dm = _FakeModule("app.engine.dream", dream=dream,
                     render_dream_markdown=lambda r: "DREAMMD")
    args = argparse.Namespace(target="", json=False)
    with _inject(**{"app.engine.dream": dm}):
        INS_MOD.cmd_dream(args)
    assert cap["curate"] is False, cap


def test_cmd_outcomes_init_default_false_168():
    # Line 168: ``getattr(args, "init", False)`` — NO init attr → default False,
    # so evaluate() runs (not init_rubric()).
    rep = types.SimpleNamespace(passed=True, to_dict=lambda: {})
    args = argparse.Namespace(target="", json=False)
    with _inject(**_outcomes_mods(rep)):
        rc, txt = _cap(INS_MOD.cmd_outcomes, args)
    assert rc == 0 and "OUTMD" in txt and "Starter rubric" not in txt, (rc, txt)


def _grade_mods(h, old=None, capture=None):
    def save(root, hh):
        if capture is not None:
            capture["saved"] = True

    hs = _FakeModule("app.engine.health_score",
                     grade=lambda r: h,
                     load_grade_snapshot=lambda r: old,
                     render_grade_diff_markdown=lambda o, n: "DIFFMD",
                     render_grade_markdown=lambda hh: "GRADEMD",
                     save_grade_snapshot=save)
    return {"app.engine.health_score": hs}


def test_cmd_grade_diff_default_false_222():
    # Line 222: ``getattr(args, "diff", False)`` — NO diff attr → default False,
    # so the plain markdown renders (not the diff path).
    h = types.SimpleNamespace(score=90, to_dict=lambda: {})
    args = argparse.Namespace(target="", json=False, save=False, min_score=0)
    with _inject(**_grade_mods(h, old=types.SimpleNamespace(score=80))):
        rc, txt = _cap(INS_MOD.cmd_grade, args)
    assert "GRADEMD" in txt and "DIFFMD" not in txt, txt


def test_cmd_grade_save_default_false_234():
    # Line 234: ``getattr(args, "save", False)`` — NO save attr → no snapshot saved.
    h = types.SimpleNamespace(score=90, to_dict=lambda: {})
    cap = {}
    args = argparse.Namespace(target="", json=False, diff=False, min_score=0)
    with _inject(**_grade_mods(h, capture=cap)):
        rc, txt = _cap(INS_MOD.cmd_grade, args)
    assert "saved" not in cap and "Snapshot saved" not in txt, (cap, txt)


def test_cmd_objectives_json_default_false_325():
    # Line 325: ``getattr(args, "json", False)`` — NO json attr → text table path.
    args = argparse.Namespace()
    with _inject(**_objectives_mods(["a", "b"], {"f": "a"})):
        rc, txt = _cap(INS_MOD.cmd_objectives, args)
    assert rc == 0 and "OBJECTIVE" in txt and "REACH" in txt, txt


# --------------------------------------------------------------------------
# cmd_grade --min-score gate (line 238: ``and`` + boundary ``<``)
# --------------------------------------------------------------------------

def test_cmd_grade_min_score_gate_fails_below_238():
    # Line 238: ``min_score and h.score < args.min_score`` — score below the bar
    # returns 1 (kills both the ``and`` flip and the ``<`` boundary flip).
    h = types.SimpleNamespace(score=50, to_dict=lambda: {})
    args = argparse.Namespace(target="", json=False, diff=False, save=False,
                              min_score=60)
    with _inject(**_grade_mods(h)):
        rc, _ = _cap(INS_MOD.cmd_grade, args)
    assert rc == 1, rc


def test_cmd_grade_min_score_gate_passes_at_boundary_238():
    # Line 238 boundary: score EQUAL to min_score must NOT fail (``<`` not ``<=``).
    h = types.SimpleNamespace(score=60, to_dict=lambda: {})
    args = argparse.Namespace(target="", json=False, diff=False, save=False,
                              min_score=60)
    with _inject(**_grade_mods(h)):
        rc, _ = _cap(INS_MOD.cmd_grade, args)
    assert rc == 0, rc


def test_cmd_grade_min_score_zero_disables_gate_238():
    # Line 238: ``min_score and ...`` — min_score 0 short-circuits the whole gate
    # (a low score still returns 0). Kills the ``and`` -> ``or`` flip.
    h = types.SimpleNamespace(score=1, to_dict=lambda: {})
    args = argparse.Namespace(target="", json=False, diff=False, save=False,
                              min_score=0)
    with _inject(**_grade_mods(h)):
        rc, _ = _cap(INS_MOD.cmd_grade, args)
    assert rc == 0, rc


# --------------------------------------------------------------------------
# JSON indent=2 on the remaining commands (lines 230, 508, 721)
# --------------------------------------------------------------------------

def test_cmd_grade_json_indent_two_230():
    # Line 230: ``json.dumps(h.to_dict(), indent=2)`` in cmd_grade.
    h = types.SimpleNamespace(score=90, to_dict=lambda: {"a": 1})
    args = argparse.Namespace(target="", json=True, diff=False, save=False,
                              min_score=0)
    with _inject(**_grade_mods(h)):
        rc, txt = _cap(INS_MOD.cmd_grade, args)
    assert txt.splitlines()[1].startswith('  "') and not txt.splitlines()[1].startswith('   "'), txt


def test_cmd_trackrecord_json_indent_two_508(tmp_path):
    # Line 508: ``json.dumps(rec, indent=2)`` in cmd_trackrecord.
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text(
        '{"totals": {"applied": 2, "rolled_back": 0}}', encoding="utf-8")
    args = argparse.Namespace(target=str(tmp_path), json=True)
    with _inject(**_mem_stub({"operators_tracked": 0})):
        rc, txt = _cap(INS_MOD.cmd_trackrecord, args)
    assert txt.splitlines()[1].startswith('  "') and not txt.splitlines()[1].startswith('   "'), txt


def test_cmd_scope_json_indent_two_721(tmp_path):
    # Line 721: ``json.dumps(rep, indent=2)`` in cmd_scope.
    prof = _profile_stub(out_of_scope_ratio=0.4, language_breakdown={"js": 2})
    args = argparse.Namespace(target=str(tmp_path), json=True)
    with _inject(**_scope_report_mods(prof, facts=[_fact()])):
        rc, txt = _cap(INS_MOD.cmd_scope, args)
    assert txt.splitlines()[1].startswith('  "') and not txt.splitlines()[1].startswith('   "'), txt


# --------------------------------------------------------------------------
# cmd_changelog --out mkdir (line 206: parents/exist_ok True)
# --------------------------------------------------------------------------

def test_cmd_changelog_out_creates_parent_dirs_206(tmp_path):
    # Line 206: ``mkdir(parents=True, exist_ok=True)`` — writing into a NESTED,
    # not-yet-existing directory must succeed (parents=True). A flip to
    # parents=False would raise FileNotFoundError.
    cl = _FakeModule("app.reporting.changelog",
                     build_changelog=lambda t: "CHANGELOG-MD")
    out = tmp_path / "deep" / "nested" / "CHANGELOG.md"
    args = argparse.Namespace(target=str(tmp_path), out=str(out))
    with _inject(**{"app.reporting.changelog": cl}):
        rc, txt = _cap(INS_MOD.cmd_changelog, args)
    assert rc == 0 and out.read_text(encoding="utf-8") == "CHANGELOG-MD"
    assert "Written to" in txt, txt


def test_cmd_changelog_out_exist_ok_206(tmp_path):
    # Line 206: ``exist_ok=True`` — an ALREADY-existing parent dir must not raise.
    cl = _FakeModule("app.reporting.changelog",
                     build_changelog=lambda t: "CL")
    subdir = tmp_path / "exists"
    subdir.mkdir()
    out = subdir / "CHANGELOG.md"
    args = argparse.Namespace(target=str(tmp_path), out=str(out))
    with _inject(**{"app.reporting.changelog": cl}):
        rc, _ = _cap(INS_MOD.cmd_changelog, args)
    assert rc == 0 and out.exists()


# --------------------------------------------------------------------------
# cmd_objectives width default (line 339: max(..., default=9))
# --------------------------------------------------------------------------

def test_cmd_objectives_empty_registry_width_default_339(capsys):
    # Line 339: ``max((len(n) for n in registered), default=9)`` — with an EMPTY
    # registry the default width 9 is used; the header ``OBJECTIVE`` (9 chars)
    # plus two spaces then ``REACH`` must align exactly at column 11.
    with _inject(**_objectives_mods([], {})):
        INS_MOD.cmd_objectives(_ns(json=False))
    out = capsys.readouterr().out
    header = out.splitlines()[0]
    assert header == "OBJECTIVE  REACH", repr(header)
    assert out.splitlines()[1] == "---------  -----", repr(out.splitlines()[1])


# --------------------------------------------------------------------------
# _scope_profile light kwarg (line 530: profile(light=True))
# --------------------------------------------------------------------------

def test_scope_profile_calls_light_true_530(tmp_path):
    # Line 530: ``ProjectProfiler(...).profile(light=True)`` — the light flag must
    # be forwarded as True (a flip to False would request a heavy profile).
    cap = {}

    class Prof:
        def __init__(self, root):
            pass

        def profile(self, light=False):
            cap["light"] = light
            return _profile_stub()

    pp = _FakeModule("app.tools.project_profile", ProjectProfiler=Prof)
    with _inject(**{"app.tools.project_profile": pp}):
        INS_MOD._scope_profile(tmp_path)
    assert cap["light"] is True, cap


# --------------------------------------------------------------------------
# _scope_file_entry debt default + scope boundaries (lines 553, 554, 600, 609)
# --------------------------------------------------------------------------

def test_scope_file_entry_debt_default_zero_553():
    # Line 553: ``int(getattr(fact, "debt_markers", 0) or 0)`` — a fact WITHOUT a
    # debt_markers attr defaults to 0, so no debt key (kills the default flip).
    fact = types.SimpleNamespace(path="a.js", language="js", loc=5, churn=2)
    entry = INS_MOD._scope_file_entry(fact, set())
    assert "debt_markers" not in entry, entry


def test_scope_file_entry_debt_one_included_554():
    # Line 554 boundary: debt==1 (>0) IS included (kills ``> 0`` -> ``>= 0``? no —
    # this is the ``debt > 0`` guard; 1 must be present).
    entry = INS_MOD._scope_file_entry(_fact(debt=1), set())
    assert entry.get("debt_markers") == 1, entry


def test_scope_report_all_python_when_breakdown_empty_600(tmp_path):
    # Line 600: ``out_of_scope_ratio > 0 and language_breakdown`` — a positive
    # ratio but EMPTY breakdown → all_python True (kills the ``and`` -> ``or`` flip).
    prof = _profile_stub(out_of_scope_ratio=0.3, language_breakdown={})
    with _inject(**_scope_report_mods(prof)):
        rep = INS_MOD._scope_report(tmp_path)
    assert rep["all_python"] is True, rep


def test_scope_report_out_of_scope_pct_distinguishes_100_vs_101_609(tmp_path):
    # Line 609: ``round(out_of_scope_ratio * 100)`` — ratio 0.6 rounds to 60 with
    # *100 but to 61 with *101 (0.6*101 = 60.6 -> 61). Kills the 100 -> 101 flip.
    prof = _profile_stub(analyzed_ratio=0.4, out_of_scope_ratio=0.6,
                         language_breakdown={"js": 2})
    with _inject(**_scope_report_mods(prof, facts=[_fact()])):
        rep = INS_MOD._scope_report(tmp_path)
    assert rep["out_of_scope_pct"] == 60, rep


# --------------------------------------------------------------------------
# _trackrecord assembly (lines 435, 439) — drive via the public reader
# --------------------------------------------------------------------------

def test_trackrecord_landed_positive_has_record_435(tmp_path):
    # Line 435: ``landed > 0 or bool(by_type)`` — landed>0, empty memory.
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text(
        '{"totals": {"applied": 4, "rolled_back": 1}}', encoding="utf-8")
    with _inject(**_mem_stub({"operators_tracked": 7})):
        rec = INS_MOD._trackrecord(tmp_path)
    assert rec["has_record"] is True
    assert rec["verified_fixes"] == 4 and rec["rolled_back"] == 1
    assert rec["operators_tracked"] == 7


def test_trackrecord_empty_no_record_435(tmp_path):
    # Line 435 (both sides false): no proof file, empty memory → has_record False.
    with _inject(**_mem_stub({})):
        rec = INS_MOD._trackrecord(tmp_path)
    assert rec["has_record"] is False and rec["verified_fixes"] == 0


def test_trackrecord_operators_tracked_missing_defaults_zero_439(tmp_path):
    # Line 439: ``int(mem.get("operators_tracked", 0) or 0)`` — missing → 0, but a
    # by_type row still yields a record.
    with _inject(**_mem_stub(
            {"most_reliable": [{"key": "a", "success_rate": 0.5, "samples": 2}]})):
        rec = INS_MOD._trackrecord(tmp_path)
    assert rec["operators_tracked"] == 0 and rec["has_record"] is True


# --------------------------------------------------------------------------
# argparse: --module is required (line 770)
# --------------------------------------------------------------------------

def test_mutants_module_required_770():
    # Line 770: ``required=True`` on --module — omitting it must error out
    # (SystemExit), not silently default. Kills the True -> False flip.
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["mutants"])


# --------------------------------------------------------------------------
# _brief_develop forwarded kwargs (lines 78, 79, 80, 81, 83) — capture what
# cli_insight passes to develop_brief so each default/operator flip is observable.
# --------------------------------------------------------------------------

def _develop_capture_mods(cap):
    def develop_brief(target, branch_path="", subject="", max_steps=25,
                      verify=True, apply=False, depth=2, breadth=4, max_ideas=40,
                      objective_focus=""):
        cap.update(subject=subject, max_steps=max_steps, verify=verify,
                   apply=apply, objective_focus=objective_focus)
        return types.SimpleNamespace(to_dict=lambda: {})

    return {"app.engine.brief_develop": _FakeModule(
        "app.engine.brief_develop", develop_brief=develop_brief,
        render_brief_develop_markdown=lambda r: "DEVMD")}


def test_brief_develop_subject_forwarded_78():
    # Line 78: ``subject=getattr(args, "subject", "") or ""`` — a real subject must
    # reach develop_brief (kills the ``or`` -> ``and`` flip that would blank it).
    cap = {}
    args = argparse.Namespace(target="", branch="b.0", subject="MOD.py",
                              objective="", depth=2, breadth=4, max_ideas=40,
                              max_steps=25, no_verify=False, apply=False,
                              json=False)
    with _inject(**_develop_capture_mods(cap)):
        _cap(INS_MOD._brief_develop, args, Path("."), "b.0")
    assert cap["subject"] == "MOD.py", cap


def test_brief_develop_max_steps_default_25_79():
    # Line 79: ``getattr(args, "max_steps", 25)`` — NO max_steps attr → default 25.
    cap = {}
    args = argparse.Namespace(target="", branch="b.0", subject="", objective="",
                              depth=2, breadth=4, max_ideas=40, no_verify=False,
                              apply=False, json=False)
    with _inject(**_develop_capture_mods(cap)):
        _cap(INS_MOD._brief_develop, args, Path("."), "b.0")
    assert cap["max_steps"] == 25, cap


def test_brief_develop_verify_no_verify_default_false_80():
    # Line 80: ``verify=not getattr(args, "no_verify", False)`` — NO no_verify attr
    # → default False → verify=True (a flip to True default would disable verify).
    cap = {}
    args = argparse.Namespace(target="", branch="b.0", subject="", objective="",
                              depth=2, breadth=4, max_ideas=40, max_steps=25,
                              apply=False, json=False)
    with _inject(**_develop_capture_mods(cap)):
        _cap(INS_MOD._brief_develop, args, Path("."), "b.0")
    assert cap["verify"] is True, cap


def test_brief_develop_apply_kwarg_default_false_81():
    # Line 81: ``apply=getattr(args, "apply", False)`` — NO apply attr → False.
    cap = {}
    args = argparse.Namespace(target="", branch="b.0", subject="", objective="",
                              depth=2, breadth=4, max_ideas=40, max_steps=25,
                              no_verify=False, json=False)
    with _inject(**_develop_capture_mods(cap)):
        _cap(INS_MOD._brief_develop, args, Path("."), "b.0")
    assert cap["apply"] is False, cap


def test_brief_develop_objective_focus_forwarded_83():
    # Line 83: ``objective_focus=args.objective or ""`` — a real objective reaches
    # develop_brief (kills the ``or`` -> ``and`` flip that would blank it).
    cap = {}
    args = argparse.Namespace(target="", branch="b.0", subject="",
                              objective="speed", depth=2, breadth=4, max_ideas=40,
                              max_steps=25, no_verify=False, apply=False,
                              json=False)
    with _inject(**_develop_capture_mods(cap)):
        _cap(INS_MOD._brief_develop, args, Path("."), "b.0")
    assert cap["objective_focus"] == "speed", cap


# --------------------------------------------------------------------------
# _brief_build forwarded objective + subject (lines 109, 111)
# --------------------------------------------------------------------------

def _build_capture_mods(cap):
    class IPE:
        def __init__(self, *a, **k):
            pass

        def run(self, objective=None):
            cap["objective"] = objective
            return types.SimpleNamespace(ideas=[])

    def build_brief(report, branch_path="", subject=""):
        cap["subject"] = subject
        return types.SimpleNamespace(branch_path=branch_path, to_dict=lambda: {})

    ib = _FakeModule("app.engine.idea_brief", build_brief=build_brief,
                     render_brief_markdown=lambda b: "BRIEFMD",
                     save_brief=lambda b, t: "/tmp/x.json")
    ip = _FakeModule("app.engine.idea_permutation", IdeaPermutationEngine=IPE)
    return {"app.engine.idea_brief": ib, "app.engine.idea_permutation": ip}


def test_brief_build_objective_empty_becomes_none_109():
    # Line 109: ``run(objective=args.objective or None)`` — empty objective → None.
    cap = {}
    args = argparse.Namespace(target="", branch="b.0", subject="", objective="",
                              depth=2, breadth=4, max_ideas=40, save=False,
                              json=False)
    with _inject(**_build_capture_mods(cap)):
        _cap(INS_MOD._brief_build, args, Path("."), "b.0")
    assert cap["objective"] is None, cap


def test_brief_build_objective_passed_through_109():
    # Line 109 (the ``or`` truthy side): a real objective is forwarded verbatim.
    cap = {}
    args = argparse.Namespace(target="", branch="b.0", subject="",
                              objective="theme", depth=2, breadth=4, max_ideas=40,
                              save=False, json=False)
    with _inject(**_build_capture_mods(cap)):
        _cap(INS_MOD._brief_build, args, Path("."), "b.0")
    assert cap["objective"] == "theme", cap


def test_brief_build_subject_forwarded_111():
    # Line 111: ``subject=getattr(args, "subject", "") or ""`` — a real subject
    # reaches build_brief (kills the ``or`` -> ``and`` flip).
    cap = {}
    args = argparse.Namespace(target="", branch="b.0", subject="app/m.py",
                              objective="", depth=2, breadth=4, max_ideas=40,
                              save=False, json=False)
    with _inject(**_build_capture_mods(cap)):
        _cap(INS_MOD._brief_build, args, Path("."), "b.0")
    assert cap["subject"] == "app/m.py", cap


# --------------------------------------------------------------------------
# cmd_explain branch + success return (lines 28, 46)
# --------------------------------------------------------------------------

def test_explain_explicit_branch_forwarded_28():
    # Line 28: ``getattr(args, "branch", "") or ""`` — a truthy branch is kept (the
    # ``or`` -> ``and`` flip would blank it and fall into the --top path instead).
    captured = {}
    exp = types.SimpleNamespace(to_dict=lambda: {})
    mods = _explain_mods([_idea(0.9, "top")], exp)
    mods["app.engine.idea_explain"].explain_idea = (
        lambda report, branch: captured.setdefault("branch", branch) or exp
    )
    with _inject(**mods):
        INS_MOD.cmd_explain(_explain_args(branch="chosen"))
    # The explicit branch "chosen" must be what explain_idea received, NOT "top".
    assert captured["branch"] == "chosen", captured


def test_explain_success_returns_zero_46():
    # Line 46: ``return 0`` — a successful explain returns exactly 0 (kills both the
    # 0 -> 1 number flip and the value -> None return flip).
    exp = types.SimpleNamespace(to_dict=lambda: {})
    with _inject(**_explain_mods([_idea(0.5, "a")], exp)):
        rc, txt = _cap(INS_MOD.cmd_explain, _explain_args(branch="a"))
    assert rc == 0 and "EXPMD" in txt, (rc, txt)


def test_explain_branch_not_found_returns_one_28():
    # Line 28 cross-check: an explicit unknown branch reaches explain_idea (which
    # returns None) → rc 1. If ``or`` flipped to ``and``, branch would blank and the
    # --top path would explain a real idea → rc 0, so this distinguishes the flip.
    with _inject(**_explain_mods([_idea(0.9, "top")], None)):
        rc, txt = _cap(INS_MOD.cmd_explain, _explain_args(branch="missing"))
    assert rc == 1 and "No idea found at branch" in txt, (rc, txt)


# --------------------------------------------------------------------------
# cmd_grade min_score default 0 (line 238 number) + scope ratio boundary (600)
# --------------------------------------------------------------------------

def test_cmd_grade_min_score_default_zero_disables_gate_238():
    # Line 238: ``getattr(args, "min_score", 0)`` — NO min_score attr → default 0
    # short-circuits the gate (and never touches ``args.min_score``). A flip of the
    # default to 1 would evaluate ``args.min_score`` and raise AttributeError.
    h = types.SimpleNamespace(score=5, to_dict=lambda: {})
    args = argparse.Namespace(target="", json=False, diff=False, save=False)
    with _inject(**_grade_mods(h)):
        rc, _ = _cap(INS_MOD.cmd_grade, args)
    assert rc == 0, rc


def test_scope_report_ratio_zero_is_all_python_600(tmp_path):
    # Line 600: ``out_of_scope_ratio > 0`` — ratio EXACTLY 0 (with a non-empty
    # breakdown) → all_python True. A flip to ``>= 0`` would make it False.
    prof = _profile_stub(out_of_scope_ratio=0.0, language_breakdown={"js": 2})
    with _inject(**_scope_report_mods(prof, facts=[_fact()])):
        rep = INS_MOD._scope_report(tmp_path)
    assert rep["all_python"] is True, rep


# --------------------------------------------------------------------------
# Command success returns ``return 0`` (lines 93, 194, 258, 276, 298, 337,
# 511, 724) — assert the exact 0 so the 0->1 and value->None flips die.
# --------------------------------------------------------------------------

def test_brief_develop_success_returns_zero_93():
    # Line 93: _brief_develop returns 0 on the happy path.
    result = types.SimpleNamespace(to_dict=lambda: {})
    args = argparse.Namespace(target="", branch="b.0", subject="", objective="",
                              depth=2, breadth=4, max_ideas=40, max_steps=25,
                              no_verify=False, apply=True, json=False)
    with _inject(**_brief_develop_stub(result)):
        rc, _ = _cap(INS_MOD._brief_develop, args, Path("."), "b.0")
    assert rc == 0, rc


def test_cmd_changelog_success_returns_zero_194(tmp_path):
    # Line 194: cmd_changelog returns 0.
    cl = _FakeModule("app.reporting.changelog", build_changelog=lambda t: "CL")
    args = argparse.Namespace(target=str(tmp_path), out="")
    with _inject(**{"app.reporting.changelog": cl}):
        rc, txt = _cap(INS_MOD.cmd_changelog, args)
    assert rc == 0 and "CL" in txt, (rc, txt)


def test_cmd_recipes_success_returns_zero_258():
    # Line 258: cmd_recipes returns 0.
    rec = _FakeModule("app.execution.recipes", RECIPES={}, COMPOSITES={},
                      render_recipes_markdown=lambda: "RECMD")
    with _inject(**{"app.execution.recipes": rec}):
        rc, txt = _cap(INS_MOD.cmd_recipes, _ns(json=False))
    assert rc == 0 and "RECMD" in txt, (rc, txt)


def test_cmd_duplication_success_returns_zero_276():
    # Line 276: cmd_duplication returns 0.
    dd = _FakeModule("app.engine.dedup", find_duplicates=lambda *a, **k: [],
                     render_duplicates_markdown=lambda b: "DUPMD")
    args = argparse.Namespace(target="", min_statements=5, json=False)
    with _inject(**{"app.engine.dedup": dd}):
        rc, txt = _cap(INS_MOD.cmd_duplication, args)
    assert rc == 0 and "DUPMD" in txt, (rc, txt)


def test_cmd_mutants_markdown_returns_zero_298():
    # Line 298: cmd_mutants non-JSON path returns 0.
    result = types.SimpleNamespace(to_dict=lambda: {})
    mt = _FakeModule("app.engine.mutation_tester",
                     mutation_score=lambda *a, **k: result,
                     render_mutation_markdown=lambda r: "MUTMD")
    args = argparse.Namespace(target="", module="app/x.py", max_mutants=30,
                              timeout=120, json=False)
    with _inject(**{"app.engine.mutation_tester": mt}):
        rc, txt = _cap(INS_MOD.cmd_mutants, args)
    assert rc == 0 and "MUTMD" in txt, (rc, txt)


def test_cmd_objectives_text_returns_zero_337():
    # Line 337: cmd_objectives JSON path returns 0.
    with _inject(**_objectives_mods(["a"], {"f": "a"})):
        rc, _ = _cap(INS_MOD.cmd_objectives, _ns(json=True))
    assert rc == 0, rc


def test_cmd_trackrecord_returns_zero_511(tmp_path):
    # Line 511: cmd_trackrecord returns 0.
    args = argparse.Namespace(target=str(tmp_path), json=False)
    with _inject(**_mem_stub({})):
        rc, txt = _cap(INS_MOD.cmd_trackrecord, args)
    assert rc == 0 and "track record" in txt, (rc, txt)


def test_cmd_scope_returns_zero_724(tmp_path):
    # Line 724: cmd_scope returns 0.
    prof = _profile_stub(out_of_scope_ratio=0.4, language_breakdown={"js": 2})
    args = argparse.Namespace(target=str(tmp_path), json=False)
    with _inject(**_scope_report_mods(prof, facts=[_fact()])):
        rc, _ = _cap(INS_MOD.cmd_scope, args)
    assert rc == 0, rc


# --------------------------------------------------------------------------
# cmd_objectives membership (lines 328, 343: ``name in reachable``)
# --------------------------------------------------------------------------

def test_cmd_objectives_json_membership_328(capsys):
    # Line 328: ``"reachable": name in reachable`` — a reachable objective is
    # flagged True, an unreachable one False (kills ``in`` -> ``not in``).
    with _inject(**_objectives_mods(["a", "b"], {"f": "a"})):
        INS_MOD.cmd_objectives(_ns(json=True))
    data = json.loads(capsys.readouterr().out)
    flags = {o["name"]: o["reachable"] for o in data["objectives"]}
    assert flags == {"a": True, "b": False}, flags


def test_cmd_objectives_text_membership_flag_343(capsys):
    # Line 343: ``"REACHABLE" if name in reachable else "unreachable"`` — the text
    # table flags 'a' REACHABLE and 'b' unreachable (kills ``in`` -> ``not in``).
    with _inject(**_objectives_mods(["a", "b"], {"f": "a"})):
        INS_MOD.cmd_objectives(_ns(json=False))
    out = capsys.readouterr().out
    rows = {ln.split()[0]: ln for ln in out.splitlines() if ln.startswith(("a ", "b "))}
    assert "REACHABLE" in rows["a"] and "unreachable" in rows["b"], rows


# --------------------------------------------------------------------------
# _trackrecord has_record landed boundary (line 435: ``landed > 0``)
# --------------------------------------------------------------------------

def test_trackrecord_landed_exactly_one_has_record_435(tmp_path):
    # Line 435: ``landed > 0`` — landed EXACTLY 1 (with empty by_type) must set
    # has_record True. A flip to ``landed > 1`` would make 1 a no-record.
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text(
        '{"totals": {"applied": 1, "rolled_back": 0}}', encoding="utf-8")
    with _inject(**_mem_stub({"operators_tracked": 0})):
        rec = INS_MOD._trackrecord(tmp_path)
    assert rec["verified_fixes"] == 1 and rec["has_record"] is True, rec


# --------------------------------------------------------------------------
# render_trackrecord pct rounding (line 478: ``round(success_rate * 100)``)
# --------------------------------------------------------------------------

def test_render_trackrecord_pct_distinguishes_100_vs_101_478():
    # Line 478: ``round(success_rate * 100)`` — 0.51 → 51% with *100 but 52% with
    # *101 (0.51*101 = 51.51 -> 52). Kills the 100 -> 101 flip.
    out = INS_MOD.render_trackrecord_markdown(
        {"has_record": True, "verified_fixes": 1, "rolled_back": 0,
         "by_type": [{"key": "a", "success_rate": 0.51, "samples": 2}]})
    assert "51% landed" in out and "52% landed" not in out, out


# --------------------------------------------------------------------------
# _scope_files test_files default + return (lines 563, 564)
# --------------------------------------------------------------------------

def test_scope_files_uses_test_files_for_has_test_563(tmp_path):
    # Line 563: ``getattr(profile, "test_files", []) or []`` — a profile's
    # test_files drive the has_test flag (a stem named by a test file is tested).
    prof = _profile_stub(test_files=["tests/test_foo.py"])
    with _inject(**_scope_report_mods(prof, facts=[_fact(path="foo.js")])):
        out = INS_MOD._scope_files(tmp_path, prof)
    assert out and out[0]["has_test"] is True, out


def test_scope_files_returns_entries_564(tmp_path):
    # Line 564: the list comprehension returns one entry per scanned fact (the
    # ``return [...]`` -> None flip would yield None).
    prof = _profile_stub(test_files=[])
    facts = [_fact(path="a.js"), _fact(path="b.go", language="go")]
    with _inject(**_scope_report_mods(prof, facts=facts)):
        out = INS_MOD._scope_files(tmp_path, prof)
    assert [e["path"] for e in out] == ["a.js", "b.go"], out


# --------------------------------------------------------------------------
# render_scope_markdown assembly (lines 700, 703, 704, 705, 711)
# --------------------------------------------------------------------------

def test_render_scope_all_python_branch_700():
    # Line 700: all_python True → the all-Python reassurance, returned (not None).
    out = INS_MOD.render_scope_markdown({"all_python": True})
    assert out == "\n".join(INS_MOD._scope_all_python_lines())
    assert "all Python" in out, out


def test_render_scope_includes_breakdown_section_703():
    # Line 703: ``lines += _scope_breakdown_lines(...)`` — the breakdown section is
    # appended (a += -> -= flip would corrupt/drop it).
    rep = {"all_python": False, "analyzed_pct": 60, "out_of_scope_pct": 40,
           "language_breakdown": [{"language": "go", "files": 2}],
           "files": [], "cross_links": []}
    out = INS_MOD.render_scope_markdown(rep)
    assert "Outside analysis scope" in out and "go — 2 files" in out, out


def test_render_scope_includes_files_section_704():
    # Line 704: ``lines += _scope_files_lines(...)`` — the files section appears.
    rep = {"all_python": False, "analyzed_pct": 60, "out_of_scope_pct": 40,
           "language_breakdown": [],
           "files": [{"path": "a.js", "language": "js", "loc": 5, "churn": 2,
                      "has_test": True}],
           "cross_links": []}
    out = INS_MOD.render_scope_markdown(rep)
    assert "most-active out-of-scope files" in out and "`a.js`" in out, out


def test_render_scope_includes_cross_section_705():
    # Line 705: ``lines += _scope_cross_lines(rep.get("cross_links") or [])`` — the
    # cross-language coupling section appears; ``or []`` guards a missing key.
    rep = {"all_python": False, "analyzed_pct": 60, "out_of_scope_pct": 40,
           "language_breakdown": [], "files": [],
           "cross_links": [{"py": "a.py", "other": "b.go", "language": "go",
                            "cochanges": 2}]}
    out = INS_MOD.render_scope_markdown(rep)
    assert "Cross-language coupling" in out and "`a.py`" in out, out


def test_render_scope_cross_links_missing_key_705():
    # Line 705: ``rep.get("cross_links") or []`` — a rep WITHOUT cross_links must
    # not raise (the ``or []`` fallback). Kills the ``or`` -> ``and`` flip, which
    # would pass None into _scope_cross_lines and break iteration.
    rep = {"all_python": False, "analyzed_pct": 60, "out_of_scope_pct": 40,
           "language_breakdown": [], "files": []}
    out = INS_MOD.render_scope_markdown(rep)
    assert "Apex names its own limits" in out, out


def test_render_scope_polyglot_returns_joined_711():
    # Line 711: the polyglot branch returns the joined string (not None), ending
    # with the "names its own limits" footer.
    rep = {"all_python": False, "analyzed_pct": 70, "out_of_scope_pct": 30,
           "language_breakdown": [], "files": [], "cross_links": []}
    out = INS_MOD.render_scope_markdown(rep)
    assert isinstance(out, str) and out.endswith("no model in the loop._"), out
