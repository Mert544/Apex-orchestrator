"""Byte-identical characterization proof for the cmd_maintain refactor.

Loads the ORIGINAL pre-refactor app/cli_autonomy.py (captured from git HEAD into
a fixture string below) and the CURRENT refactored module side by side, drives
cmd_maintain on both with an identical battery of arg combinations and identical
fakes, and asserts stdout/stderr/exit-code are byte-for-byte equal for every
case. cmd_maintain imports its collaborators lazily, so all of them are patched
at their source modules — no real engine runs, nothing touches a real repo.

Determinism only: no time/random/order assertions.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

import app.cli_autonomy as refactored

_ORIG_SNAPSHOT = Path(__file__).with_name("_cli_autonomy_orig_snapshot.py")


def _load_original():
    spec = importlib.util.spec_from_file_location(
        "_cli_autonomy_orig_for_byteident", _ORIG_SNAPSHOT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


original = _load_original()


def _ns(tmp_path: Path, **over) -> argparse.Namespace:
    base = dict(
        target=str(tmp_path), objective="", depth=1, breadth=3, max_ideas=12,
        top=0, mode="supervised", no_verify=True, commit=False, max_apply=0,
        json=False, out="", dry_run=False, recipe="", proof="",
    )
    base.update(over)
    return argparse.Namespace(**base)


class _FakeEngine:
    last_profile = "PROFILE-SENTINEL"

    def __init__(self, **kw):
        self.kw = kw

    def run(self, objective=None):
        return {"objective": objective}


class _FakePlugins:
    def load_all(self):
        pass

    def idea_operators(self):
        return []


class _FakePlan:
    pass


def _make_bridge(dry_preview, apply_summary):
    calls = []

    class _FakeBridge:
        def plan_tree(self, report, mode="supervised", top=None, project_root=""):
            calls.append(("plan_tree", mode, top, project_root))
            return _FakePlan()

        def dry_run_plan(self, plan, project_root):
            return dry_preview

        def apply_plan(self, plan, project_root, mode="supervised", verify=True,
                       max_apply=None, commit=False):
            calls.append(("apply_plan", mode, verify, max_apply, commit))
            return apply_summary

    return _FakeBridge(), calls


def _patch(monkeypatch, *, dry_preview=None, apply_summary=None,
           filter_result=None, filter_raises=False):
    """Patch every lazily-imported collaborator at its source module so the same
    fakes serve BOTH the original and refactored cmd_maintain."""
    monkeypatch.setattr("app.engine.idea_permutation.IdeaPermutationEngine",
                        _FakeEngine)
    monkeypatch.setattr("app.plugins.registry.PluginRegistry",
                        lambda *a, **k: _FakePlugins())

    bridge, calls = _make_bridge(dry_preview, apply_summary)
    monkeypatch.setattr("app.engine.idea_action_bridge.IdeaActionBridge",
                        lambda *a, **k: bridge)
    monkeypatch.setattr(
        "app.engine.idea_action_bridge.render_maintenance_markdown",
        lambda summary, target, objective="": f"# Maintenance Report (obj={objective!r})")

    def _filter(plan, recipe):
        if filter_raises:
            raise ValueError(f"unknown recipe `{recipe}`")
        return filter_result
    monkeypatch.setattr("app.execution.recipes.filter_plan", _filter)

    monkeypatch.setattr("app.engine.idea_memory.IdeaMemory.learn_from",
                        staticmethod(lambda summary, target: None))

    class _Trends:
        def __init__(self, root):
            pass

        def record(self, profile):
            pass

    monkeypatch.setattr("app.engine.signal_trends.SignalTrends", _Trends)
    monkeypatch.setattr("app.engine.proof_of_fix.build_proof",
                        lambda summary, root, objective="": {"proof": True, "obj": objective})
    monkeypatch.setattr(
        "app.engine.proof_of_fix.write_proof",
        lambda proof, root, out=None: f"{out or str(Path(root) / '.apex' / 'proof-of-fix.json')}")
    return calls


def _run(fn, ns):
    """Invoke a cmd_maintain, capturing (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(ns)
    return rc, out.getvalue(), err.getvalue()


def _preview() -> dict:
    return {
        "applicable": 1,
        "total_executable": 2,
        "results": [
            {"applicable": True, "branch": "root/secure/0", "action": "refactor",
             "transform_type": "harden", "files": ["app/svc.py", ""],
             "diff": "- bad\n+ good\n   "},
            {"applicable": False, "branch": "root/x", "action": "skip",
             "transform_type": "noop", "files": [], "diff": ""},
        ],
    }


# Battery of (label, dry_preview, apply_summary, filter_result, filter_raises, overrides)
_CASES = [
    ("report_apply_results", None, {"results": [{"applied": True}], "applied": 1,
                                    "commit": False, "rolled_back": 0}, None, False,
     dict(mode="report")),
    ("apply_no_results", None, {"results": [], "applied": 0}, None, False, {}),
    ("apply_json", None, {"results": [{"applied": True}], "applied": 1}, None, False,
     dict(json=True)),
    ("apply_out_file", None, {"results": [], "applied": 0}, None, False,
     dict(out="OUTFILE")),
    ("apply_out_and_json", None, {"results": [{"applied": True}], "applied": 3},
     None, False, dict(out="OUTFILE", json=True)),
    ("apply_forwards_flags", None, {"results": [{"applied": True}], "applied": 1},
     None, False, dict(mode="autonomous", commit=True, max_apply=5, no_verify=True)),
    ("apply_objective", None, {"results": [{"applied": True}], "applied": 1},
     None, False, dict(objective="harden-security")),
    ("apply_proof_path", None, {"results": [{"applied": True}], "applied": 1},
     None, False, dict(proof="custom/proof.json")),
    ("recipe_scopes", None, {"results": []}, 2, False, dict(recipe="harden", mode="report")),
    ("recipe_scopes_apply", None, {"results": [{"applied": True}], "applied": 1}, 0,
     False, dict(recipe="modernize")),
    ("recipe_unknown", None, None, None, True, dict(recipe="bogus")),
    ("recipe_unknown_json", None, None, None, True, dict(recipe="bogus", json=True)),
    ("dry_run_md", _preview(), None, None, False, dict(dry_run=True)),
    ("dry_run_json", _preview(), None, None, False, dict(dry_run=True, json=True)),
    ("dry_run_md_recipe", _preview(), None, 1, False,
     dict(dry_run=True, recipe="harden")),
    ("dry_run_empty", {"applicable": 0, "total_executable": 0, "results": []},
     None, None, False, dict(dry_run=True)),
    ("no_verify_false", None, {"results": [{"applied": True}], "applied": 1}, None,
     False, dict(no_verify=False)),
    ("max_apply_zero", None, {"results": [{"applied": True}], "applied": 1}, None,
     False, dict(max_apply=0)),
]


@pytest.mark.parametrize("case", _CASES, ids=[c[0] for c in _CASES])
def test_byte_identical(case, tmp_path, monkeypatch):
    label, dry_preview, apply_summary, filter_result, filter_raises, over = case

    # Both sides target the SAME --out path: stdout echoes that path, so using
    # one path keeps the comparison about behavior, not the harness's tag. The
    # written content is itself proven byte-identical in test_out_files_*.
    def build_ns(tag):
        ov = dict(over)
        if ov.get("out") == "OUTFILE":
            ov["out"] = str(tmp_path / "report.md")
        return _ns(tmp_path, **ov)

    # Original
    calls_o = _patch(monkeypatch, dry_preview=dry_preview, apply_summary=apply_summary,
                     filter_result=filter_result, filter_raises=filter_raises)
    rc_o, out_o, err_o = _run(original.cmd_maintain, build_ns("orig"))

    # Refactored
    calls_r = _patch(monkeypatch, dry_preview=dry_preview, apply_summary=apply_summary,
                     filter_result=filter_result, filter_raises=filter_raises)
    rc_r, out_r, err_r = _run(refactored.cmd_maintain, build_ns("refac"))

    assert rc_o == rc_r, f"{label}: exit code differs"
    assert out_o == out_r, f"{label}: stdout differs"
    assert err_o == err_r, f"{label}: stderr differs"

    # Collaborator call shape (mode/verify/max_apply/commit forwarding) matches.
    assert calls_o == calls_r, f"{label}: collaborator calls differ"

    # If stdout is pure JSON, it must parse to the same object (defensive; the
    # apply path can append a trailing report/proof line after the JSON, which
    # is already covered by the exact stdout equality above).
    stripped = out_o.strip()
    if over.get("json") and stripped.startswith(("{", "[")):
        try:
            parsed_o = json.loads(stripped)
        except json.JSONDecodeError:
            parsed_o = None
        if parsed_o is not None:
            assert parsed_o == json.loads(out_r.strip())


def test_out_files_byte_identical(tmp_path, monkeypatch):
    """The Markdown written to --out is itself byte-identical across versions."""
    summary = {"results": [{"applied": True}], "applied": 1}
    of_o = tmp_path / "o.md"
    of_r = tmp_path / "r.md"

    _patch(monkeypatch, apply_summary=summary)
    original.cmd_maintain(_ns(tmp_path, out=str(of_o), objective="x"))
    _patch(monkeypatch, apply_summary=summary)
    refactored.cmd_maintain(_ns(tmp_path, out=str(of_r), objective="x"))

    assert of_o.read_bytes() == of_r.read_bytes()
