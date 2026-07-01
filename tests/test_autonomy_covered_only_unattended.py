"""UNATTENDED runs force covered-only verification; ``--allow-weak`` is an
ATTENDED-only, risk-explicit opt-out.

The regression this pins (rank 9 — the second minimal autonomy-ENABLER, after
the register-time soundness lock): once the hands-off ``--evolve`` loop / daemon
is wired, a green suite that merely IMPORTS a module (WEAK / uncovered) must NEVER
be allowed to land a Tier-1 behaviour-change move unattended — that is exactly
where unattended autonomy becomes a SILENT regression. So:

  * UNATTENDED (``APEX_DAEMON`` set OR ``--evolve N`` active) ⇒ ``covered_only``
    is forced True UNCONDITIONALLY, and ``--allow-weak`` is REFUSED (ignored);
  * ATTENDED (both absent) ⇒ ``--allow-weak`` still relaxes to land weak moves
    (unchanged), and the DEFAULT attended gate is BYTE-IDENTICAL to the literal
    pre-change expression ``not getattr(args, "allow_weak", False)``.

Pure/deterministic: :meth:`AutonomyPolicy.resolve_covered_only` takes
``unattended`` as a plain bool (no I/O); the CLI helpers read only the env +
parsed flags (no clock/random). The end-to-end act-path test SPIES the
``covered_only`` fed to ``apply_plan`` — nothing real is planned/applied and no
repo is touched.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import app.cli_autonomy as m
import app.engine.evolution as evolution_mod
from app.policies.autonomy_policy import AutonomyDecision, AutonomyPolicy


# --------------------------------------------------------------------------- #
# AutonomyPolicy.resolve_covered_only — the pure single source of truth.       #
# --------------------------------------------------------------------------- #
def test_resolve_attended_honours_allow_weak():
    # ATTENDED: covered-only unless --allow-weak opts back into land-everything.
    assert AutonomyPolicy.resolve_covered_only(allow_weak=False, unattended=False) is True
    assert AutonomyPolicy.resolve_covered_only(allow_weak=True, unattended=False) is False


def test_resolve_unattended_forces_covered_only_ignoring_allow_weak():
    # UNATTENDED: covered-only is forced True REGARDLESS of --allow-weak.
    assert AutonomyPolicy.resolve_covered_only(allow_weak=False, unattended=True) is True
    assert AutonomyPolicy.resolve_covered_only(allow_weak=True, unattended=True) is True


def test_resolve_attended_matches_prechange_expression():
    """Non-tautological byte-identity anchor: the ATTENDED result equals the
    LITERAL pre-change gate ``not allow_weak`` for BOTH flag values, so the
    attended path is byte-for-byte what it computed before this feature."""
    for allow_weak in (False, True):
        assert (
            AutonomyPolicy.resolve_covered_only(allow_weak=allow_weak, unattended=False)
            == (not allow_weak)
        )


# --------------------------------------------------------------------------- #
# _auto_unattended — env (APEX_DAEMON) OR --evolve N>=1 detection.              #
# --------------------------------------------------------------------------- #
def _ns(**over) -> argparse.Namespace:
    base = dict(allow_weak=False, evolve=0)
    base.update(over)
    return argparse.Namespace(**base)


def test_unattended_false_when_attended(monkeypatch):
    monkeypatch.delenv("APEX_DAEMON", raising=False)
    assert m._auto_unattended(_ns()) is False


def test_unattended_true_when_daemon_env_set(monkeypatch):
    monkeypatch.setenv("APEX_DAEMON", "1")
    assert m._auto_unattended(_ns()) is True


def test_unattended_true_when_evolve_active(monkeypatch):
    monkeypatch.delenv("APEX_DAEMON", raising=False)
    assert m._auto_unattended(_ns(evolve=3)) is True
    # --evolve 0 (the default single-pass) is NOT unattended.
    assert m._auto_unattended(_ns(evolve=0)) is False


def test_unattended_missing_evolve_attr_is_attended(monkeypatch):
    """A namespace WITHOUT ``evolve`` (defensive ``getattr`` default) and no env
    reads as attended — never raising."""
    monkeypatch.delenv("APEX_DAEMON", raising=False)
    assert m._auto_unattended(argparse.Namespace(allow_weak=True)) is False


def test_unattended_empty_env_value_is_attended(monkeypatch):
    """An empty ``APEX_DAEMON`` (falsy) does not trip the guard — only a set,
    non-empty value marks the daemon context."""
    monkeypatch.setenv("APEX_DAEMON", "")
    assert m._auto_unattended(_ns()) is False


# --------------------------------------------------------------------------- #
# _auto_covered_only — the CLI helper wiring the policy to the parsed flags.    #
# --------------------------------------------------------------------------- #
def test_covered_only_attended_default_true(monkeypatch):
    monkeypatch.delenv("APEX_DAEMON", raising=False)
    assert m._auto_covered_only(_ns()) is True


def test_covered_only_attended_allow_weak_false(monkeypatch):
    monkeypatch.delenv("APEX_DAEMON", raising=False)
    assert m._auto_covered_only(_ns(allow_weak=True)) is False


def test_covered_only_unattended_daemon_refuses_allow_weak(monkeypatch):
    monkeypatch.setenv("APEX_DAEMON", "1")
    # --allow-weak is REFUSED under the daemon: still covered-only.
    assert m._auto_covered_only(_ns(allow_weak=True)) is True


def test_covered_only_unattended_evolve_refuses_allow_weak(monkeypatch):
    monkeypatch.delenv("APEX_DAEMON", raising=False)
    assert m._auto_covered_only(_ns(allow_weak=True, evolve=2)) is True


def test_covered_only_attended_matches_prechange_expression(monkeypatch):
    """The attended CLI helper equals the literal pre-change expression for both
    flag values — the byte-identity proof at the call-site layer."""
    monkeypatch.delenv("APEX_DAEMON", raising=False)
    for allow_weak in (False, True):
        args = _ns(allow_weak=allow_weak)
        assert m._auto_covered_only(args) == (not getattr(args, "allow_weak", False))


# --------------------------------------------------------------------------- #
# End-to-end through the act path: the covered_only fed to apply_plan.          #
# --------------------------------------------------------------------------- #
def _act_ns(tmp_path: Path, **over) -> argparse.Namespace:
    base = dict(
        goal="", target=str(tmp_path), apply=True, allow_weak=False,
        recommend=False, mode=None, commit=False, deep=False, no_verify=False,
        max_apply=0, evolve=0, json=False, out="")
    base.update(over)
    return argparse.Namespace(**base)


def _spy_covered_only(monkeypatch, tmp_path: Path) -> dict:
    """Stub everything cmd_auto's act path touches and capture the
    ``covered_only`` value handed to ``apply_plan``. No real plan/apply/repo."""
    captured: dict = {}

    class _Plan:
        objective = "auto"
        project_root = str(tmp_path)
        mode = "supervised"
        steps: list = []
        stats = {"executable_steps": 1, "total_steps": 1}

    def _fake_plan(self, report, mode="report", project_root="", **kw):
        return _Plan()

    def _fake_apply(self, plan, root_, mode="supervised", verify=True,
                    max_apply=None, commit=False, covered_only=False):
        captured["covered_only"] = covered_only
        return {"results": [{"applied": True}], "applied": 1}

    from app.engine.idea_action_bridge import IdeaActionBridge

    monkeypatch.setattr(IdeaActionBridge, "plan_roadmap", _fake_plan)
    monkeypatch.setattr(IdeaActionBridge, "apply_plan", _fake_apply)
    monkeypatch.setattr(
        "app.engine.idea_action_bridge.render_maintenance_markdown",
        lambda summary, target, objective="": "# Maintenance")
    monkeypatch.setattr(m, "_working_tree_clean", lambda target: True)
    # Force the act decision so the act path runs regardless of the fixture.
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
                        lambda proof, root_: str(Path(root_) / ".apex" / "p.json"))
    # A minimal engine/roadmap/shape so the narrative prelude doesn't do real work.
    monkeypatch.setattr("app.engine.idea_permutation.IdeaPermutationEngine",
                        lambda *a, **k: type("E", (), {
                            "last_profile": None,
                            "run": lambda self, objective=None: {}})())
    monkeypatch.setattr("app.plugins.registry.PluginRegistry",
                        lambda *a, **k: type("PR", (), {
                            "load_all": lambda self: None,
                            "idea_operators": lambda self: []})())
    monkeypatch.setattr("app.engine.idea_roadmap.RoadmapSynthesizer",
                        lambda *a, **k: type("R", (), {
                            "build": lambda self, report: type("RM", (), {
                                "quick_wins": []})()})())
    monkeypatch.setattr("app.engine.idea_tree_shape.analyze_tree_shape",
                        lambda report: type("SH", (), {
                            "observations": [], "heaviest_module": "",
                            "heaviest_loc": 0, "total_ideas": 1,
                            "distinct_subjects": 1})())
    return captured


def test_act_attended_default_feeds_covered_only_true(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("APEX_DAEMON", raising=False)
    captured = _spy_covered_only(monkeypatch, tmp_path)
    rc = m.cmd_auto(_act_ns(tmp_path))
    capsys.readouterr()
    assert rc == 0
    assert captured["covered_only"] is True


def test_act_attended_allow_weak_feeds_covered_only_false(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("APEX_DAEMON", raising=False)
    captured = _spy_covered_only(monkeypatch, tmp_path)
    rc = m.cmd_auto(_act_ns(tmp_path, allow_weak=True))
    capsys.readouterr()
    assert rc == 0
    # ATTENDED --allow-weak still relaxes the gate (unchanged behaviour).
    assert captured["covered_only"] is False


def test_act_unattended_daemon_forces_covered_only_despite_allow_weak(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APEX_DAEMON", "1")
    captured = _spy_covered_only(monkeypatch, tmp_path)
    # Even with --allow-weak, the daemon context refuses it: covered-only forced.
    rc = m.cmd_auto(_act_ns(tmp_path, allow_weak=True))
    capsys.readouterr()
    assert rc == 0
    assert captured["covered_only"] is True


# --------------------------------------------------------------------------- #
# END-TO-END through the --evolve / EvolutionLoop path (the gap the isolation  #
# tests above MISSED). `cmd_auto --evolve N` short-circuits into `cmd_evolve` → #
# a real `EvolutionLoop.run()` BEFORE the act path ever runs; the loop is       #
# inherently UNATTENDED, so the `covered_only` it feeds `apply_plan` MUST be     #
# forced True even with `--allow-weak`. We drive the REAL loop (not a spy sub-   #
# class) and stub only its measurement + the `apply_plan` it calls, so this      #
# proves the WIRING end-to-end: revert the fix (drop the kwarg / the resolve)    #
# and `covered_only` falls back to the `apply_plan` default (False) → these fail.#
# --------------------------------------------------------------------------- #
def _spy_evolve_apply_plan(monkeypatch, tmp_path: Path) -> dict:
    """Neutralise everything a real ``EvolutionLoop.run()`` touches — its
    measurement, roadmap snapshot/diff, memory persistence and ``record_run`` —
    and capture the ``covered_only`` handed to the ONE ``apply_plan`` the loop
    calls per cycle. Nothing real is planned/applied and no repo is written.

    A single applied fix on the FIRST cycle then a fixpoint keeps ``run()`` to
    one ``apply_plan`` call (applied>0 → not a fixpoint on cycle 1; applied==0 on
    cycle 2 → stop), so the captured value is unambiguous for a ``--evolve 2`` run.
    """
    captured: dict = {}
    calls = {"n": 0}

    from app.engine.idea_action_bridge import IdeaActionBridge

    def _fake_plan(self, report, mode="report", project_root="", **kw):
        return type("P", (), {"executable_steps": lambda self: [],
                              "stats": {"executable_steps": 0}})()

    def _fake_apply(self, plan, root_, mode="supervised", verify=True,
                    max_apply=None, commit=False, covered_only=False, **kw):
        calls["n"] += 1
        captured["covered_only"] = covered_only
        # First cycle applies one fix; later cycles apply nothing → fixpoint stop.
        applied = 1 if calls["n"] == 1 else 0
        return {"applied": applied, "rolled_back": 0, "blocked": 0, "committed": 0}

    monkeypatch.setattr(IdeaActionBridge, "plan_roadmap", _fake_plan)
    monkeypatch.setattr(IdeaActionBridge, "apply_plan", _fake_apply)
    # The loop's measurement + build_report: return a trivial snapshot, no engine.
    monkeypatch.setattr(evolution_mod.EvolutionLoop, "_build_report",
                        lambda self: type("R", (), {"stats": {}})())
    monkeypatch.setattr(evolution_mod.EvolutionLoop, "_measure",
                        lambda self, report: {"security_findings": 0, "mean_roi": 0.0,
                                              "executable_fixes": 0, "total_ideas": 0,
                                              "_roadmap": object()})
    monkeypatch.setattr("app.engine.roadmap_history.roadmap_to_snapshot",
                        lambda rm: {})
    monkeypatch.setattr("app.engine.roadmap_history.diff_roadmaps",
                        lambda before, after: type("D", (), {
                            "to_dict": lambda self: {}})())
    monkeypatch.setattr("app.engine.idea_memory.IdeaMemory.load",
                        staticmethod(lambda root_: type("Mem", (), {
                            "record_outcomes": lambda self, s: None,
                            "save": lambda self, root__: None})()))
    monkeypatch.setattr(evolution_mod, "record_run",
                        lambda result, root_: Path(root_))
    return captured


def _evolve_e2e_ns(tmp_path: Path, **over) -> argparse.Namespace:
    base = dict(target=str(tmp_path), max_cycles=2, max_apply=5, mode=None,
                commit=False, no_verify=True, dry_run=False, history=False,
                objective="", json=True, out="", allow_weak=False)
    base.update(over)
    return argparse.Namespace(**base)


def test_cmd_evolve_forces_covered_only_true(tmp_path, monkeypatch, capsys):
    # `apex evolve` drives EvolutionLoop.run() → apply_plan; the loop is
    # unattended, so covered_only is forced True end-to-end.
    monkeypatch.delenv("APEX_DAEMON", raising=False)
    captured = _spy_evolve_apply_plan(monkeypatch, tmp_path)
    rc = m.cmd_evolve(_evolve_e2e_ns(tmp_path))
    capsys.readouterr()
    assert rc == 0
    assert captured["covered_only"] is True


def test_cmd_evolve_forces_covered_only_true_even_with_allow_weak(
        tmp_path, monkeypatch, capsys):
    # An unattended evolve REFUSES --allow-weak (the evolve subparser exposes no
    # such flag, but a namespace carrying it must still be forced covered-only).
    monkeypatch.delenv("APEX_DAEMON", raising=False)
    captured = _spy_evolve_apply_plan(monkeypatch, tmp_path)
    rc = m.cmd_evolve(_evolve_e2e_ns(tmp_path, allow_weak=True))
    capsys.readouterr()
    assert rc == 0
    assert captured["covered_only"] is True


def test_cmd_auto_evolve_forces_covered_only_true_end_to_end(
        tmp_path, monkeypatch, capsys):
    # THE gap the isolation suite missed: `apex auto --evolve 2` short-circuits
    # through _auto_evolve_delegate → cmd_evolve → EvolutionLoop BEFORE _auto_act,
    # so the ONLY place covered-only can be forced on this path is the loop wiring.
    # Driven end-to-end (real delegate + real loop), apply_plan gets covered_only=True.
    monkeypatch.delenv("APEX_DAEMON", raising=False)
    captured = _spy_evolve_apply_plan(monkeypatch, tmp_path)
    rc = m.cmd_auto(_evolve_e2e_ns(tmp_path, evolve=2))
    capsys.readouterr()
    assert rc == 0
    assert captured["covered_only"] is True


def test_cmd_auto_evolve_forces_covered_only_true_even_with_allow_weak(
        tmp_path, monkeypatch, capsys):
    # `apex auto --evolve 2 --allow-weak`: the evolve loop is unattended, so
    # --allow-weak is REFUSED end-to-end — the exact hole in commit e17bcf5.
    monkeypatch.delenv("APEX_DAEMON", raising=False)
    captured = _spy_evolve_apply_plan(monkeypatch, tmp_path)
    rc = m.cmd_auto(_evolve_e2e_ns(tmp_path, evolve=2, allow_weak=True))
    capsys.readouterr()
    assert rc == 0
    assert captured["covered_only"] is True


# --------------------------------------------------------------------------- #
# The daemon-to-CLI wire: ApexDaemon's per-cycle subprocess env is what makes  #
# ``APEX_DAEMON`` visible to the child ``apex auto --apply`` in the first      #
# place. The isolation tests above set the env var directly, which proves the  #
# CLI-side logic but NOT that the daemon actually exports it. This closes that  #
# gap end-to-end: take the REAL ``ApexDaemon._build_env()`` output (the exact   #
# dict the daemon hands to ``subprocess.run``), apply it as the process env,    #
# and drive ``cmd_auto`` through it — proving the wire, not just the endpoints. #
# Reverting the ``env=`` plumbing in ``ApexDaemon._run_apex``/``_build_env``     #
# makes these fail (the daemon-produced env would no longer carry the var).     #
# --------------------------------------------------------------------------- #
def test_daemon_built_env_marks_unattended(tmp_path, monkeypatch):
    """``_auto_unattended`` reads True from the EXACT value
    ``ApexDaemon._build_env()`` stamps — the daemon's own output, not a
    hand-written stand-in. Sourced from the real subprocess-env dict the
    daemon builds, then applied to the process env the way the OS would hand
    it to the child ``apex auto --apply``."""
    from app.daemon import ApexDaemon

    monkeypatch.delenv("APEX_DAEMON", raising=False)
    d = ApexDaemon(goal="", target=str(tmp_path), pid_file=str(tmp_path / "d.pid"))
    daemon_env = d._build_env()
    assert daemon_env.get("APEX_DAEMON") == "1"

    # What the OS does when spawning the child with `env=daemon_env`: the
    # child process's os.environ IS that dict's contents.
    monkeypatch.setenv("APEX_DAEMON", daemon_env["APEX_DAEMON"])
    assert m._auto_unattended(_ns()) is True


def test_daemon_built_env_drives_covered_only_end_to_end(tmp_path, monkeypatch, capsys):
    """Full wire: daemon-produced env ⇒ ``cmd_auto`` (as the daemon's child
    process would run it) feeds ``covered_only=True`` to ``apply_plan`` even
    with ``--allow-weak`` — the daemon subprocess can never silently land an
    uncovered move. Proves the fix rather than re-asserting the policy."""
    from app.daemon import ApexDaemon

    monkeypatch.delenv("APEX_DAEMON", raising=False)
    d = ApexDaemon(goal="", target=str(tmp_path), pid_file=str(tmp_path / "d.pid"))
    daemon_env = d._build_env()

    monkeypatch.setenv("APEX_DAEMON", daemon_env["APEX_DAEMON"])
    captured = _spy_covered_only(monkeypatch, tmp_path)
    rc = m.cmd_auto(_act_ns(tmp_path, allow_weak=True))
    capsys.readouterr()
    assert rc == 0
    assert captured["covered_only"] is True


def test_daemon_env_without_the_fix_would_be_attended(tmp_path, monkeypatch):
    """Non-tautological control: the UNPATCHED parent env (what the daemon's
    subprocess saw BEFORE this fix, i.e. no ``env=`` override at all) reads as
    ATTENDED — proving the assertions above genuinely depend on
    ``ApexDaemon._build_env()`` doing the stamping, not on ambient state."""
    monkeypatch.delenv("APEX_DAEMON", raising=False)
    assert m._auto_unattended(_ns()) is False
