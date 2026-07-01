"""`apex maintain --dry-run` must HONOR --proof / --out — as a clearly-marked
PREVIEW, never a real proof.

Field-tested defect: `_maintain_dry_run` returned before the out/proof writers
were reached, so `apex maintain --proof X --dry-run` wrote NOTHING and printed
NO warning (silent drop). The fix routes the diffs the dry-run already computes
into a PREVIEW artifact stamped ``mode: dry-run-preview`` / ``applied: false`` /
``verified: false`` on every record, so a buyer/auditor can never confuse it with
an applied+verified proof-of-fix.

cmd_maintain imports its collaborators lazily, so engine/bridge/plugins are all
patched at their source modules — no real engine runs, nothing touches a real
repo. Determinism only: no time/random/order assertions.
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
    pass


def _preview() -> dict:
    return {
        "applicable": 1,
        "total_executable": 2,
        "results": [
            {"applicable": True, "branch": "root/secure/0", "action": "refactor",
             "target": "app/svc.py", "transform_type": "harden",
             "files": ["app/svc.py", ""], "diff": "- bad\n+ good\n"},
            {"applicable": False, "branch": "root/x", "action": "skip",
             "target": "app/y.py", "transform_type": "noop", "files": [],
             "diff": ""},
        ],
    }


class _FakeBridge:
    def plan_tree(self, report, mode="supervised", top=None, project_root=""):
        return _FakePlan()

    def dry_run_plan(self, plan, project_root):
        return _preview()

    def apply_plan(self, plan, project_root, mode="supervised", verify=True,
                   max_apply=None, commit=False, covered_only=False):
        return {"results": [{"applied": True}], "applied": 1,
                "rolled_back": 0, "commit": False}


def _patch(monkeypatch):
    monkeypatch.setattr("app.engine.idea_permutation.IdeaPermutationEngine",
                        _FakeEngine)
    monkeypatch.setattr("app.plugins.registry.PluginRegistry",
                        lambda *a, **k: _FakePlugins())
    bridge = _FakeBridge()
    monkeypatch.setattr("app.engine.idea_action_bridge.IdeaActionBridge",
                        lambda *a, **k: bridge)
    monkeypatch.setattr(
        "app.engine.idea_action_bridge.render_maintenance_markdown",
        lambda summary, target, objective="": "# Maintenance Report")
    monkeypatch.setattr("app.engine.idea_memory.IdeaMemory.learn_from",
                        staticmethod(lambda summary, target: None))

    class _Trends:
        def __init__(self, root):
            pass

        def record(self, profile):
            pass

    monkeypatch.setattr("app.engine.signal_trends.SignalTrends", _Trends)
    # The REAL proof builder/writer — used only on a non-dry-run apply. If a
    # dry-run ever routed through these, this sentinel would leak into the file
    # and the dry-run assertions below would catch it.
    monkeypatch.setattr(
        "app.engine.proof_of_fix.build_proof",
        lambda summary, root, objective="": {"schema": "REAL-PROOF",
                                              "applied_real": True})
    monkeypatch.setattr(
        "app.engine.proof_of_fix.write_proof",
        lambda proof, root, out=None: _write_real_proof(proof, root, out))
    return bridge


def _write_real_proof(proof, root, out=None):
    path = Path(out) if out else Path(root) / ".apex" / "proof-of-fix.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------- #
# 1. --dry-run --proof X writes X, marked preview / not-applied / not-verified #
# --------------------------------------------------------------------------- #
def test_dry_run_proof_writes_marked_preview(tmp_path, capsys, monkeypatch):
    _patch(monkeypatch)
    proof = tmp_path / "out" / "p.json"
    rc = cmd_maintain(_ns(tmp_path, dry_run=True, proof=str(proof)))
    out = capsys.readouterr().out
    assert rc == 0
    assert proof.exists(), "--proof was silently dropped under --dry-run"

    data = json.loads(proof.read_text())
    # Unmistakably NOT a real proof: top-level markers.
    assert data["mode"] == "dry-run-preview"
    assert data["applied"] is False
    assert data["verified"] is False
    assert data["schema"] != "REAL-PROOF"  # the real proof builder was NOT used
    assert "NOT a proof-of-fix" in data["note"]
    # EVERY planned-change record carries the not-a-proof markers.
    assert data["planned_changes"]
    for rec in data["planned_changes"]:
        assert rec["applied"] is False
        assert rec["verified"] is False
    # The planned diff is carried through (the receipts the user asked for).
    applicable = [r for r in data["planned_changes"] if r["applicable"]]
    assert applicable and "+ good" in applicable[0]["diff"]

    # The flag is NEVER silently dropped: stdout says so explicitly.
    assert "--proof is a PREVIEW under --dry-run" in out
    assert "not applied, not verified" in out


def test_dry_run_out_writes_marked_preview(tmp_path, capsys, monkeypatch):
    _patch(monkeypatch)
    out_path = tmp_path / "sub" / "preview.json"
    rc = cmd_maintain(_ns(tmp_path, dry_run=True, out=str(out_path)))
    out = capsys.readouterr().out
    assert rc == 0
    assert out_path.exists(), "--out was silently dropped under --dry-run"
    data = json.loads(out_path.read_text())
    assert data["mode"] == "dry-run-preview"
    assert data["applied"] is False and data["verified"] is False
    assert "Dry-run PREVIEW (not applied, not verified)" in out


# --------------------------------------------------------------------------- #
# 2. --dry-run WITHOUT --proof/--out writes nothing new (byte-identical)       #
# --------------------------------------------------------------------------- #
def test_dry_run_without_flags_writes_nothing_new(tmp_path, capsys, monkeypatch):
    _patch(monkeypatch)
    before = {p.name for p in tmp_path.rglob("*")}
    rc = cmd_maintain(_ns(tmp_path, dry_run=True))
    out = capsys.readouterr().out
    assert rc == 0
    after = {p.name for p in tmp_path.rglob("*")}
    assert before == after, "a bare dry-run created files — not byte-identical"
    # And no preview/proof chatter leaks into stdout on a bare dry-run.
    assert "PREVIEW" not in out
    assert "proof" not in out.lower()


def test_dry_run_json_without_flags_byte_identical(tmp_path, capsys, monkeypatch):
    """The --json console payload is exactly the bridge preview, unchanged."""
    _patch(monkeypatch)
    rc = cmd_maintain(_ns(tmp_path, dry_run=True, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload == _preview()
    # No artifact written either.
    assert not list(tmp_path.rglob("*.json"))


# --------------------------------------------------------------------------- #
# 3. A real (non-dry-run) maintain still writes its normal proof, unchanged    #
# --------------------------------------------------------------------------- #
def test_real_maintain_writes_real_proof_unchanged(tmp_path, capsys, monkeypatch):
    _patch(monkeypatch)
    proof = tmp_path / "real.json"
    rc = cmd_maintain(_ns(tmp_path, proof=str(proof)))  # dry_run=False
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(proof.read_text())
    # The REAL proof builder/writer ran (not the preview path).
    assert data["schema"] == "REAL-PROOF"
    assert data["applied_real"] is True
    assert "mode" not in data or data.get("mode") != "dry-run-preview"
    assert "Proof-of-fix evidence written to" in out


# --------------------------------------------------------------------------- #
# 4. Determinism: same input → byte-identical preview artifact                 #
# --------------------------------------------------------------------------- #
def test_dry_run_preview_is_deterministic(tmp_path, monkeypatch):
    _patch(monkeypatch)
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    cmd_maintain(_ns(tmp_path, dry_run=True, proof=str(a)))
    cmd_maintain(_ns(tmp_path, dry_run=True, proof=str(b)))
    assert a.read_bytes() == b.read_bytes()


def test_dry_run_empty_plan_writes_marked_empty_preview(tmp_path, monkeypatch):
    """Edge: an all-advisory plan (no executable steps) still honors --proof with
    a marked, empty-changeset preview rather than silently dropping the flag."""
    bridge = _patch(monkeypatch)
    bridge.dry_run_plan = lambda plan, project_root: {
        "applicable": 0, "total_executable": 0, "results": []}
    proof = tmp_path / "empty.json"
    rc = cmd_maintain(_ns(tmp_path, dry_run=True, proof=str(proof)))
    assert rc == 0
    data = json.loads(proof.read_text())
    assert data["mode"] == "dry-run-preview"
    assert data["applied"] is False and data["verified"] is False
    assert data["planned_changes"] == []
    assert data["totals"]["executable"] == 0
