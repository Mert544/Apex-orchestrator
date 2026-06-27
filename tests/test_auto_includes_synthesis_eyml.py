"""``apex auto`` (and bare ``apex``) AUTONOMOUSLY includes the applicable
synthesis opt-ins — so the marketed one-command entry surfaces Apex's full
development value without the user naming any flag.

Today ``cmd_auto`` planned with NO synthesis kwargs, so ``auto`` reached only the
roadmap smell-fixes plus the three default synthesis families — never
modernize / dedup / cover-gaps / etc. This file pins the new, tiered + disclosed
+ honest wiring:

  - AUTONOMOUS (cheap): ``apex auto`` on a project with a modernizable module
    surfaces a ``modernize`` action with NO flag. The grounding still filters to
    applicable targets, so this only surfaces real, landable work (honest).
  - DISCLOSED (expensive): the pytest-cost opt-ins (cover-gaps, tdd-implement,
    strengthen-tests, wire-exports, generate-usage-doc) do NOT appear without
    ``--deep`` and DO with it; without ``--deep`` a one-line disclosure announces
    they are available, so the cost is opt-in AND visible (never silent).
  - HONEST COUNT-CAP: the recommend count and the act apply share one story —
    recommend discloses the per-run cap when there is more work than the cap,
    and the act path prints "applying N of M this run; re-run for the rest".
  - CLEAN NO-OP: a project with nothing applicable surfaces no synthesis action
    and recommends without writing anything.
  - APPLY-GATING / ROLLBACK UNCHANGED: ``--apply`` on a clean git tree still
    routes through the verified, auto-rolled-back guarded loop; only WHICH
    objectives are offered changed, not the verify/rollback path.

All fixtures are tiny isolated ``tmp_path`` projects with no time/random, so the
same project always yields the same plan (determinism preserved).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
from pathlib import Path

import app.cli_autonomy as m
from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_permutation import IdeaPermutationEngine


# --------------------------------------------------------------------------- #
# Helpers.                                                                     #
# --------------------------------------------------------------------------- #
def _build_auto_parser() -> argparse.ArgumentParser:
    """The REAL auto argparser, wired exactly as ``app.cli.main`` wires it — so
    ``--deep`` is exercised through the genuine parser, not a hand-built ns."""
    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    m.register_parsers(sub)
    return parser


def _parse_auto(target: Path, *extra: str) -> argparse.Namespace:
    parser = _build_auto_parser()
    return parser.parse_args(["auto", "--target", str(target), *extra])


def _run_auto(target: Path, *extra: str) -> tuple[int, str]:
    """Run ``cmd_auto`` end-to-end against ``target``; return (rc, stdout)."""
    args = _parse_auto(target, *extra)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = m.cmd_auto(args)
    return rc, buf.getvalue()


def _run_auto_json(target: Path, *extra: str) -> tuple[int, dict]:
    rc, out = _run_auto(target, "--json", *extra)
    return rc, json.loads(out)


def _report(target: Path):
    return IdeaPermutationEngine(
        config={"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4},
        project_root=str(target),
    ).run(objective=None)


def _executable_actions(plan, action_type: str) -> list[str]:
    """The targets of the EXECUTABLE steps of one synthesis objective in a plan."""
    return [s.target for s in plan.steps
            if s.executable and s.action_type == action_type]


# --------------------------------------------------------------------------- #
# Fixtures: tiny isolated projects (mirrors test_ideate_auto_synthesis_eyml).  #
# --------------------------------------------------------------------------- #
def _modernizable_project(tmp_path: Path) -> Path:
    """A module carrying stale idioms (``== None`` + empty ``dict()``) the cheap
    ``modernize`` objective rewrites — already tested, so cover-gaps won't fire."""
    root = tmp_path / "mod"
    root.mkdir()
    (root / "stale.py").write_text(
        'def greet(name):\n    if name == None:\n        return dict()\n'
        '    return f"hi {name}"\n')
    (root / "tests").mkdir()
    (root / "tests" / "test_stale.py").write_text(
        "from stale import greet\n\n\ndef test_greet():\n"
        "    assert greet('x') == 'hi x'\n")
    return root


def _cover_gaps_only_project(tmp_path: Path) -> Path:
    """ONLY an EXPENSIVE (cover-gaps) opportunity: an untested module with a
    public callable, written idiomatically so NO cheap objective qualifies."""
    root = tmp_path / "gappy"
    root.mkdir()
    (root / "plain.py").write_text("def area(w, h):\n    return w * h\n")
    return root


def _clean_project(tmp_path: Path) -> Path:
    """Nothing applicable: an idiomatic, already-tested module — no smell, no
    synthesis opportunity at all."""
    root = tmp_path / "clean"
    root.mkdir()
    (root / "ok.py").write_text("def add(a, b):\n    return a + b\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_ok.py").write_text(
        "from ok import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    return root


def _git_init(root: Path) -> None:
    """Commit the fixture so the tree is clean — the precondition for ``apex
    auto`` to act autonomously (it won't auto-edit a tree it can't help undo)."""
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
                ["git", "config", "user.name", "t"], ["git", "add", "-A"],
                ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=root, capture_output=True)


# --------------------------------------------------------------------------- #
# RECOGNITION: --deep parses and defaults off; cheap opt-ins are always on.    #
# --------------------------------------------------------------------------- #
def test_deep_flag_parses_and_defaults_off(tmp_path: Path) -> None:
    """``--deep`` PARSES through the real auto argparser and defaults False, so a
    plain ``apex auto`` never silently pays the expensive (pytest) grounding."""
    assert _parse_auto(tmp_path).deep is False
    assert _parse_auto(tmp_path, "--deep").deep is True


def test_synthesis_kwargs_tiering_is_deterministic(tmp_path: Path) -> None:
    """``_auto_synthesis_kwargs`` is a pure function of the flags: the cheap
    opt-ins are ALWAYS enabled (autonomous), and the expensive ones are added
    ONLY under ``--deep`` — and the same flags always yield the same set."""
    cheap = m._auto_synthesis_kwargs(_parse_auto(tmp_path))
    assert cheap == {"modernize": True, "dedup_total_return": True,
                     "dedup_parameterized": True}
    assert cheap == m._auto_synthesis_kwargs(_parse_auto(tmp_path))  # deterministic
    deep = m._auto_synthesis_kwargs(_parse_auto(tmp_path, "--deep"))
    assert deep == {name: True for name in
                    (*m._AUTO_CHEAP_SYNTHESIS, *m._AUTO_DEEP_SYNTHESIS)}
    # The expensive set is exactly the five pytest-cost objectives.
    assert set(m._AUTO_DEEP_SYNTHESIS) == {
        "cover_gaps", "tdd_implement", "strengthen_tests", "wire_exports",
        "generate_usage_doc"}


# --------------------------------------------------------------------------- #
# AUTONOMOUS (cheap): a modernizable module surfaces a modernize action — no    #
# flag — and only because the grounding qualifies it (honest by construction).  #
# --------------------------------------------------------------------------- #
def test_auto_surfaces_modernize_without_any_flag(tmp_path: Path) -> None:
    """The cheap ``modernize`` opt-in is offered by a bare ``apex auto``: the
    scout plan (the SAME kwargs the act path uses) carries a ``modernize`` step
    for the stale module — with NO flag named by the user."""
    root = _modernizable_project(tmp_path)
    report = _report(root)
    bridge = IdeaActionBridge()
    # What a DEFAULT (today's) auto would have planned: no modernize.
    plain = bridge.plan_roadmap(report, mode="report", project_root=str(root))
    assert _executable_actions(plain, "modernize") == []
    # What the NEW auto plans autonomously: the cheap opt-ins surface modernize.
    auto = bridge.plan_roadmap(report, mode="report", project_root=str(root),
                               **m._auto_synthesis_kwargs(_parse_auto(root)))
    assert _executable_actions(auto, "modernize") == ["stale.py"]
    # The recommend count the user sees reflects that added, landable work.
    assert auto.stats.get("executable_steps", 0) == \
        plain.stats.get("executable_steps", 0) + 1


def test_auto_recommend_count_reflects_cheap_synthesis(tmp_path: Path) -> None:
    """End-to-end through ``cmd_auto`` (recommend path on a non-git tree): the
    ``applicable`` count INCLUDES the autonomously-offered modernize work."""
    root = _modernizable_project(tmp_path)
    base = IdeaActionBridge().plan_roadmap(
        _report(root), mode="report", project_root=str(root)
    ).stats.get("executable_steps", 0)
    rc, payload = _run_auto_json(root)
    assert rc == 0 and payload["applied"] is False
    assert payload["applicable"] == base + 1  # the modernize step is counted


# --------------------------------------------------------------------------- #
# DISCLOSED (expensive): hidden without --deep, surfaced WITH it; the           #
# availability is announced so the cost stays opt-in AND visible.               #
# --------------------------------------------------------------------------- #
def test_expensive_optins_hidden_without_deep_surface_with_deep(tmp_path: Path) -> None:
    """A project whose ONLY opportunity is the EXPENSIVE cover-gaps objective:
    it is INVISIBLE to a bare ``apex auto`` and surfaces ONLY under ``--deep`` —
    so the pytest-cost work is opt-in, not silently run on every invocation."""
    root = _cover_gaps_only_project(tmp_path)
    report = _report(root)
    bridge = IdeaActionBridge()
    without = bridge.plan_roadmap(report, mode="report", project_root=str(root),
                                  **m._auto_synthesis_kwargs(_parse_auto(root)))
    assert _executable_actions(without, "cover_gaps") == []
    with_deep = bridge.plan_roadmap(
        report, mode="report", project_root=str(root),
        **m._auto_synthesis_kwargs(_parse_auto(root, "--deep")))
    assert _executable_actions(with_deep, "cover_gaps") == ["plain.py"]


def test_deep_disclosure_shown_without_deep_and_hidden_with_deep(tmp_path: Path) -> None:
    """Without ``--deep`` a bare ``apex auto`` prints the one-line disclosure that
    deeper (pytest-cost) synthesis is available; with ``--deep`` there is nothing
    left to disclose, so the line is gone."""
    root = _modernizable_project(tmp_path)
    rc, out = _run_auto(root)
    assert rc == 0
    assert "`--deep`" in out and "runs pytest during grounding" in out
    # The five expensive objectives are named so the user knows what they'd add.
    for name in ("cover-gaps", "tdd-implement", "strengthen-tests",
                 "wire-exports", "generate-usage-doc"):
        assert name in out
    rc2, out2 = _run_auto(root, "--deep")
    assert rc2 == 0 and "add `--deep` to include it" not in out2


# --------------------------------------------------------------------------- #
# HONEST COUNT-CAP: recommend discloses the cap; act prints "N of M".          #
# --------------------------------------------------------------------------- #
def test_recommend_discloses_cap_when_more_than_cap(tmp_path: Path, monkeypatch) -> None:
    """When more fixes are applicable than a single run will apply, the recommend
    path discloses the per-run cap so the uncapped count is never mistaken for
    "all in one run" — the bug this fix closes."""
    root = _modernizable_project(tmp_path)

    # Force a large applicable count via the scout, leaving the policy to decline
    # (non-git tree) so we land in the recommend path.
    class _Scout:
        stats = {"executable_steps": 20}

    real = IdeaActionBridge.plan_roadmap

    def _fake(self, report, mode="report", project_root="", **kw):
        if mode == "report" and not kw.get("draft"):
            return _Scout()
        return real(self, report, mode=mode, project_root=project_root, **kw)

    monkeypatch.setattr(IdeaActionBridge, "plan_roadmap", _fake)
    rc, out = _run_auto(root)
    assert rc == 0
    assert "I can safely apply **20**" in out
    assert "this run would apply up to 8" in out
    assert "re-run to continue" in out


def test_recommend_no_cap_clause_when_within_cap(tmp_path: Path) -> None:
    """When the applicable count is within the per-run cap, NO cap clause is
    shown (it would be misleading) — the count stands alone."""
    root = _modernizable_project(tmp_path)
    rc, out = _run_auto(root)  # this fixture's count (≈7) is < the default cap 8
    assert rc == 0
    assert "I can safely apply" in out
    assert "re-run to continue" not in out


def test_recommend_cap_matches_explicit_max_apply(tmp_path: Path, monkeypatch) -> None:
    """The disclosed cap honors ``--max-apply`` — the same value the act path
    feeds ``apply_plan`` — so recommend and act tell ONE consistent story."""
    root = _modernizable_project(tmp_path)

    class _Scout:
        stats = {"executable_steps": 20}

    real = IdeaActionBridge.plan_roadmap

    def _fake(self, report, mode="report", project_root="", **kw):
        if mode == "report" and not kw.get("draft"):
            return _Scout()
        return real(self, report, mode=mode, project_root=project_root, **kw)

    monkeypatch.setattr(IdeaActionBridge, "plan_roadmap", _fake)
    rc, out = _run_auto(root, "--max-apply", "3")
    assert rc == 0
    assert "this run would apply up to 3" in out


def test_act_discloses_n_of_m_cap(tmp_path: Path, monkeypatch) -> None:
    """The act path discloses "applying N of M this run; re-run for the rest"
    when the plan carries more applicable steps than the per-run cap — the same
    M the recommend path reports, so the cap is honest on BOTH sides."""
    from app.policies.autonomy_policy import AutonomyDecision

    root = _modernizable_project(tmp_path)

    class _Plan:
        objective = "auto"
        project_root = str(root)
        mode = "supervised"
        steps: list = []
        stats = {"executable_steps": 25, "total_steps": 25}

    def _fake_plan(self, report, mode="report", project_root="", **kw):
        return _Plan()

    # Apply nothing for real, but report a non-empty results list so the act
    # path runs its full disclosure block (the apply/rollback path is unchanged).
    def _fake_apply(self, plan, root_, mode="supervised", verify=True,
                    max_apply=None, commit=False, covered_only=False):
        return {"results": [{"applied": True}], "applied": 1}

    monkeypatch.setattr(IdeaActionBridge, "plan_roadmap", _fake_plan)
    monkeypatch.setattr(IdeaActionBridge, "apply_plan", _fake_apply)
    monkeypatch.setattr(
        "app.engine.idea_action_bridge.render_maintenance_markdown",
        lambda summary, target, objective="": "# Maintenance")
    monkeypatch.setattr(m, "_working_tree_clean", lambda target: True)
    monkeypatch.setattr(
        "app.policies.autonomy_policy.AutonomyPolicy",
        lambda *a, **k: type("P", (), {
            "decide": lambda self, **kw: AutonomyDecision(
                True, "supervised", "clean tree + fixes")})())
    monkeypatch.setattr("app.engine.idea_memory.IdeaMemory.learn_from",
                        staticmethod(lambda summary, target: None))
    monkeypatch.setattr("app.engine.signal_trends.SignalTrends",
                        lambda root_: type("S", (), {
                            "record": lambda self, p: None})())
    monkeypatch.setattr("app.engine.proof_of_fix.build_proof",
                        lambda summary, root_, objective="": {"p": True})
    monkeypatch.setattr("app.engine.proof_of_fix.write_proof",
                        lambda proof, root_: "/x/proof.json")

    rc, out = _run_auto(root, "--apply", "--max-apply", "8")
    assert rc == 0
    assert "Applying 8 of 25 this run" in out
    assert "re-run for the rest" in out


# --------------------------------------------------------------------------- #
# CLEAN NO-OP: nothing applicable -> no synthesis action, nothing written.     #
# --------------------------------------------------------------------------- #
def test_clean_project_is_a_no_op(tmp_path: Path) -> None:
    """A project with nothing applicable surfaces NO synthesis action (cheap or
    expensive) and recommends without writing — the autonomous opt-ins never
    invent work that the grounding does not qualify (honest empty path)."""
    root = _clean_project(tmp_path)
    before = (root / "ok.py").read_text()
    report = _report(root)
    bridge = IdeaActionBridge()
    deep = bridge.plan_roadmap(
        report, mode="report", project_root=str(root),
        **m._auto_synthesis_kwargs(_parse_auto(root, "--deep")))
    for name in (*m._AUTO_CHEAP_SYNTHESIS, *m._AUTO_DEEP_SYNTHESIS):
        assert _executable_actions(deep, name) == []
    rc, payload = _run_auto_json(root)
    assert rc == 0 and payload["applied"] is False
    assert (root / "ok.py").read_text() == before  # recommend wrote nothing


# --------------------------------------------------------------------------- #
# APPLY-GATING / ROLLBACK: only WHICH objectives are offered changed, not the   #
# verified, auto-rolled-back guarded apply path.                                #
# --------------------------------------------------------------------------- #
def test_apply_gating_still_holds_with_synthesis(tmp_path: Path) -> None:
    """``apex auto --apply --allow-weak`` on a CLEAN git tree still routes through
    the verified, auto-rolled-back guarded loop: a real (security) fix lands and is
    verified, exactly as before — proving the synthesis opt-ins changed only the
    OFFERED objective set, never the apply/verify/rollback path. ``--allow-weak``
    is needed because the yaml fix is on a module no test exercises (the SAFE
    covered-only sweep withholds it by default)."""
    root = tmp_path / "g"
    root.mkdir()
    (root / "cfg.py").write_text(
        "import yaml\ndef load(s):\n    return yaml.load(s)\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    _git_init(root)
    rc, out = _run_auto(root, "--apply", "--allow-weak", "--max-apply", "3")
    assert rc == 0
    assert "applying autonomously" in out.lower()
    # The yaml.load -> safe_load hardening landed and was verified.
    assert "yaml.safe_load" in (root / "cfg.py").read_text()


def test_apply_rollback_on_failing_verify_restores_tree(tmp_path: Path, monkeypatch) -> None:
    """If verification fails after a patch, the guarded loop rolls back and the
    file is restored — the never-fake-green invariant is intact regardless of
    which (synthesis) objectives ``auto`` now offers. Exercised on the maintenance
    apply path (a yaml.load hardening) with a forced-RED suite."""
    from app.policies.autonomy_policy import AutonomyDecision
    from app.skills.execution.run_tests import RunTestsSkill, TestRunSummary

    root = tmp_path / "rb"
    root.mkdir()
    (root / "cfg.py").write_text(
        "import yaml\ndef load(s):\n    return yaml.load(s)\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    _git_init(root)
    before = (root / "cfg.py").read_text()

    # Force a RED suite (a real command that "fails") after the patch so the
    # guarded maintenance apply must roll back; the apply path itself (NOT
    # stubbed) does the snapshot restore — the path the synthesis change leaves
    # untouched.
    monkeypatch.setattr(
        RunTestsSkill, "run",
        lambda self, project_root, commands=None: TestRunSummary(
            project_root=str(project_root),
            commands=[["python", "-m", "pytest", "-q"]], ok=False))
    monkeypatch.setattr(m, "_working_tree_clean", lambda target: True)
    monkeypatch.setattr(
        "app.policies.autonomy_policy.AutonomyPolicy",
        lambda *a, **k: type("P", (), {
            "decide": lambda self, **kw: AutonomyDecision(
                True, "supervised", "clean tree")})())

    rc, _out = _run_auto(root, "--apply", "--max-apply", "3")
    assert rc == 0
    # The hardening was rolled back on the red suite: the file is unchanged.
    assert (root / "cfg.py").read_text() == before
    assert "yaml.safe_load" not in (root / "cfg.py").read_text()
