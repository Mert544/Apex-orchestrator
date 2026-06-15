"""Deterministic coverage for cmd_maintain's recipe-scoping, dry-run preview
(JSON + diff loop) and proof-of-fix branches in app/cli_autonomy.py.

cmd_maintain imports its collaborators lazily, so the engine, action bridge,
recipe filter, idea-memory, signal trends and proof-of-fix are all patched at
their source modules. No real engine runs, no real apply/verify, nothing
touches a real repo. No time/random/order assertions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli_autonomy import cmd_maintain


def _ns(tmp_path: Path, **over) -> argparse.Namespace:
    base = dict(
        target=str(tmp_path), objective="", depth=1, breadth=3, max_ideas=12,
        top=0, mode="supervised", no_verify=True, commit=False, max_apply=0,
        json=False, out="", dry_run=False, recipe="", proof="",
    )
    base.update(over)
    return argparse.Namespace(**base)


class _FakeEngine:
    last_profile = None

    def __init__(self, **kw):
        pass

    def run(self, objective=None):
        return {"objective": objective}


class _FakePlugins:
    def load_all(self):
        pass

    def idea_operators(self):
        return []


class _FakePlan:
    """A stand-in plan object; the bridge fakes accept/return it directly."""


class _FakeBridge:
    _dry_preview: dict = {}
    _apply_summary: dict = {"results": []}
    applied: list = []

    def plan_tree(self, report, mode="supervised", top=None, project_root=""):
        return _FakePlan()

    def dry_run_plan(self, plan, project_root):
        return self._dry_preview

    def apply_plan(self, plan, project_root, mode="supervised", verify=True,
                   max_apply=None, commit=False):
        type(self).applied.append((mode, verify, max_apply, commit))
        return self._apply_summary


def _patch(monkeypatch, *, dry_preview=None, apply_summary=None,
           filter_result=None, filter_raises=False):
    monkeypatch.setattr("app.engine.idea_permutation.IdeaPermutationEngine",
                        _FakeEngine)
    monkeypatch.setattr("app.plugins.registry.PluginRegistry",
                        lambda *a, **k: _FakePlugins())

    bridge = _FakeBridge()
    if dry_preview is not None:
        type(bridge)._dry_preview = dry_preview
    if apply_summary is not None:
        type(bridge)._apply_summary = apply_summary
    type(bridge).applied = []
    monkeypatch.setattr("app.engine.idea_action_bridge.IdeaActionBridge",
                        lambda *a, **k: bridge)
    monkeypatch.setattr(
        "app.engine.idea_action_bridge.render_maintenance_markdown",
        lambda summary, target, objective="": "# Maintenance Report")

    if filter_result is not None or filter_raises:
        def _filter(plan, recipe):
            if filter_raises:
                raise ValueError(f"unknown recipe `{recipe}`")
            return filter_result
        monkeypatch.setattr("app.execution.recipes.filter_plan", _filter)

    # learn/record/proof sinks
    monkeypatch.setattr("app.engine.idea_memory.IdeaMemory.learn_from",
                        staticmethod(lambda summary, target: None))

    class _Trends:
        def __init__(self, root):
            pass

        def record(self, profile):
            pass

    monkeypatch.setattr("app.engine.signal_trends.SignalTrends", _Trends)
    monkeypatch.setattr("app.engine.proof_of_fix.build_proof",
                        lambda summary, root, objective="": {"proof": True})
    monkeypatch.setattr(
        "app.engine.proof_of_fix.write_proof",
        lambda proof, root, out=None: str(Path(root) / ".apex" / "proof.json"))
    return bridge


# --------------------------------------------------------------------------- #
# --recipe scoping                                                            #
# --------------------------------------------------------------------------- #
def test_maintain_recipe_filter_scopes_and_reports(tmp_path, capsys, monkeypatch):
    _patch(monkeypatch, apply_summary={"results": []}, filter_result=2)
    rc = cmd_maintain(_ns(tmp_path, recipe="harden", mode="report"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "scoped to recipe `harden`" in out
    assert "2 executable step(s) in scope" in out


def test_maintain_recipe_unknown_fails_loudly(tmp_path, capsys, monkeypatch):
    _patch(monkeypatch, filter_raises=True)
    rc = cmd_maintain(_ns(tmp_path, recipe="bogus"))
    out = capsys.readouterr().out
    assert rc == 1
    assert "unknown recipe `bogus`" in out


# --------------------------------------------------------------------------- #
# --dry-run preview (markdown diff loop + JSON)                               #
# --------------------------------------------------------------------------- #
def _preview() -> dict:
    return {
        "applicable": 1,
        "total_executable": 2,
        "results": [
            {"applicable": True, "branch": "root/secure/0", "action": "refactor",
             "transform_type": "harden", "files": ["app/svc.py", ""],
             "diff": "- bad\n+ good\n"},
            {"applicable": False, "branch": "root/x", "action": "skip",
             "transform_type": "noop", "files": [], "diff": ""},
        ],
    }


def test_maintain_dry_run_markdown_emits_diff_block(tmp_path, capsys, monkeypatch):
    _patch(monkeypatch, dry_preview=_preview())
    rc = cmd_maintain(_ns(tmp_path, dry_run=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry run" in out
    assert "1 of 2 executable steps would change files" in out
    assert "`root/secure/0` refactor → harden (app/svc.py)" in out
    assert "```diff" in out
    assert "+ good" in out
    # the non-applicable step is skipped in the listing
    assert "root/x" not in out


def test_maintain_dry_run_json(tmp_path, capsys, monkeypatch):
    preview = _preview()
    _patch(monkeypatch, dry_preview=preview)
    rc = cmd_maintain(_ns(tmp_path, dry_run=True, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload == preview


# --------------------------------------------------------------------------- #
# Apply path — proof-of-fix written only when there are results.              #
# --------------------------------------------------------------------------- #
def test_maintain_apply_writes_proof_when_results(tmp_path, capsys, monkeypatch):
    summary = {"results": [{"applied": True}], "applied": 1, "commit": False,
               "rolled_back": 0}
    _patch(monkeypatch, apply_summary=summary)
    rc = cmd_maintain(_ns(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Proof-of-fix evidence written to" in out


def test_maintain_apply_no_results_skips_proof(tmp_path, capsys, monkeypatch):
    _patch(monkeypatch, apply_summary={"results": [], "applied": 0})
    rc = cmd_maintain(_ns(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Proof-of-fix" not in out


def test_maintain_apply_json_summary(tmp_path, capsys, monkeypatch):
    summary = {"results": [{"applied": True}], "applied": 1}
    _patch(monkeypatch, apply_summary=summary)
    rc = cmd_maintain(_ns(tmp_path, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["applied"] == 1


def test_maintain_apply_writes_out_file(tmp_path, capsys, monkeypatch):
    _patch(monkeypatch, apply_summary={"results": [], "applied": 0})
    out_file = tmp_path / "sub" / "report.md"
    rc = cmd_maintain(_ns(tmp_path, out=str(out_file)))
    out = capsys.readouterr().out
    assert rc == 0
    assert out_file.exists()
    assert "Maintenance Report" in out_file.read_text()
    assert "[maintain] Report written to" in out


def test_maintain_apply_forwards_max_apply_and_commit(tmp_path, capsys, monkeypatch):
    summary = {"results": [{"applied": True}], "applied": 1}
    bridge = _patch(monkeypatch, apply_summary=summary)
    rc = cmd_maintain(_ns(tmp_path, mode="autonomous", commit=True, max_apply=5,
                          no_verify=True))
    assert rc == 0
    mode, verify, max_apply, commit = bridge.applied[-1]
    assert mode == "autonomous"
    assert verify is False  # --no-verify
    assert max_apply == 5
    assert commit is True
