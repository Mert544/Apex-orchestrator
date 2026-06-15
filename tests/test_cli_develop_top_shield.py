"""`apex develop --top --shield`: the constructive upgrade to the false-green
guard. When the #1 runnable recommendation's target is exercised by NO test, a
green suite would be a FALSE green. ``--shield`` turns "block" into "make safe":
Apex writes a deterministic characterization-test STUB naming the target's real
symbols + import path (recommend-only — the user fills in the assertion), so the
NEXT run's green is real. It does NOT auto-apply the fix in the same run.

These tests:
  - reuse the `_develop_top` / `cmd_develop` wiring and the monkeypatch helpers
    from the sibling develop-top suite (fixed one-step plan, stubbed
    `apply_plan` / `module_referenced_by_suite` — never spawns pytest);
  - assert the stub is written, names the target's symbols, is deterministic, and
    leaves the original source untouched (rc 0);
  - assert an existing characterization test is skipped with a message (no
    clobber);
  - PIN the no-shield uncovered path byte-identical to today (block + rc 2).

No time/random/order asserts; nothing here runs the real pytest suite.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli_autonomy import (
    _develop_top,
    _shield_stub_path,
    _write_shield_stub,
    cmd_develop,
)
from app.models.idea import ActionPlan, ActionStep


# --------------------------------------------------------------------------- #
# helpers (mirrors tests/test_cli_develop_top.py)                              #
# --------------------------------------------------------------------------- #
def _ns(**over) -> argparse.Namespace:
    base = dict(
        target="", objective="", goal="", all_objectives=False, grade=False,
        history=False, from_dream=False, playbook=False, apply=False, top=True,
        force=False, shield=False, max_steps=5, no_verify=True, fast=True,
        json=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


def _uncovered_project(tmp_path: Path) -> Path:
    """A project whose `app/lonely.py` is referenced by NO test."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "lonely.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "tests" / "test_other.py").write_text(
        "def test_trivial():\n    assert True\n"
    )
    return tmp_path


def _step(target: str = "app/lonely.py", **over) -> ActionStep:
    base = dict(
        branch_path="x.a.b", title="Test → Document: app/lonely.py", operator="doc",
        subject="app/lonely.py", action_type="add_docstring", target=target,
        description="Add docstrings to app/lonely.py", executable=True, value=0.67,
        patch_preview={"diff": "--- a/app/lonely.py\n+++ b/app/lonely.py\n",
                       "added": 1, "removed": 0, "reparses": True,
                       "impact": "", "covered": True, "applied": False},
    )
    base.update(over)
    return ActionStep(**base)


def _force_plan(monkeypatch, step: ActionStep):
    """Make plan_roadmap return a fixed one-step plan (deterministic selection)."""
    from app.engine.idea_action_bridge import IdeaActionBridge

    def fake_plan(self, report, *a, **k):
        return ActionPlan(objective="dead-params", project_root="", steps=[step])

    monkeypatch.setattr(IdeaActionBridge, "plan_roadmap", fake_plan)


def _stub_apply(monkeypatch):
    """Stub apply_plan so the guarded loop never spawns pytest; record the call."""
    calls: list = []

    def fake_apply(self, plan, root, mode="supervised", verify=True,
                   max_apply=None, commit=False):
        calls.append({"steps": len(plan.steps), "max_apply": max_apply})
        return {"results": [{"applied": True, "rolled_back": False,
                             "verified": None}], "applied": 1, "rolled_back": 0}

    from app.engine.idea_action_bridge import IdeaActionBridge
    monkeypatch.setattr(IdeaActionBridge, "apply_plan", fake_apply)
    return calls


def _uncovered(monkeypatch):
    monkeypatch.setattr(
        "app.engine.verification_strength.module_referenced_by_suite",
        lambda r, p: False,
    )


# --------------------------------------------------------------------------- #
# _shield_stub_path — pure, deterministic naming                              #
# --------------------------------------------------------------------------- #
def test_shield_stub_path_is_deterministic_and_named_for_module():
    step = _step(target="app/lonely.py")
    p1 = _shield_stub_path(step)
    p2 = _shield_stub_path(step)
    assert p1 == p2 == "tests/test_lonely_characterization.py"


def test_shield_stub_path_slugifies_non_identifier_chars():
    step = _step(target="app/sub-pkg/odd name.py")
    assert _shield_stub_path(step) == "tests/test_odd_name_characterization.py"


def test_shield_stub_path_falls_back_to_module_when_empty():
    step = _step(target="", subject="")
    assert _shield_stub_path(step) == "tests/test_module_characterization.py"


# --------------------------------------------------------------------------- #
# _write_shield_stub — writes once, never clobbers                            #
# --------------------------------------------------------------------------- #
def test_write_shield_stub_creates_file_naming_symbols(tmp_path):
    _uncovered_project(tmp_path)
    step = _step(target="app/lonely.py")
    rel, written = _write_shield_stub(str(tmp_path), step)
    assert written is True
    assert rel == "tests/test_lonely_characterization.py"
    text = (tmp_path / rel).read_text()
    # Reused the bridge generator: names the real import path + subject.
    assert "import app.lonely" in text
    assert "app/lonely.py" in text
    assert "def test_" in text


def test_write_shield_stub_does_not_clobber_existing(tmp_path):
    _uncovered_project(tmp_path)
    step = _step(target="app/lonely.py")
    dest = tmp_path / "tests" / "test_lonely_characterization.py"
    dest.write_text("# hand-written, do not touch\n")
    rel, written = _write_shield_stub(str(tmp_path), step)
    assert written is False
    assert rel == "tests/test_lonely_characterization.py"
    assert dest.read_text() == "# hand-written, do not touch\n"  # untouched


# --------------------------------------------------------------------------- #
# --top --shield on an uncovered target: write the stub, rc 0, source intact   #
# --------------------------------------------------------------------------- #
def test_shield_writes_stub_rc0_source_untouched(tmp_path, monkeypatch, capsys):
    _uncovered_project(tmp_path)
    step = _step(target="app/lonely.py")
    _force_plan(monkeypatch, step)
    calls = _stub_apply(monkeypatch)
    _uncovered(monkeypatch)

    before = (tmp_path / "app" / "lonely.py").read_text()
    rc = cmd_develop(_ns(target=str(tmp_path), shield=True))
    out = capsys.readouterr().out

    assert rc == 0
    stub = tmp_path / "tests" / "test_lonely_characterization.py"
    assert stub.exists()  # the stub was written
    body = stub.read_text()
    assert "import app.lonely" in body  # names the real symbols / import path
    assert "Wrote a characterization-test stub" in out
    assert "app/lonely.py" in out
    assert "apex develop --top --apply" in out
    # the point: do NOT apply the fix in the shield run, source untouched
    assert calls == []
    assert (tmp_path / "app" / "lonely.py").read_text() == before


def test_shield_run_is_deterministic(tmp_path, monkeypatch):
    _uncovered_project(tmp_path)
    step = _step(target="app/lonely.py")
    _force_plan(monkeypatch, step)
    _stub_apply(monkeypatch)
    _uncovered(monkeypatch)

    cmd_develop(_ns(target=str(tmp_path), shield=True))
    first = (tmp_path / "tests" / "test_lonely_characterization.py").read_text()
    # re-running finds the stub already there; the body never changes.
    cmd_develop(_ns(target=str(tmp_path), shield=True))
    second = (tmp_path / "tests" / "test_lonely_characterization.py").read_text()
    assert first == second  # same input → same stub (no time/random)


def test_shield_json_reports_written(tmp_path, monkeypatch, capsys):
    _uncovered_project(tmp_path)
    step = _step(target="app/lonely.py")
    _force_plan(monkeypatch, step)
    _stub_apply(monkeypatch)
    _uncovered(monkeypatch)

    rc = cmd_develop(_ns(target=str(tmp_path), shield=True, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["covered"] is False
    assert payload["applied"] is False
    assert payload["reason"] == "shield-stub-written"
    assert payload["shield"]["written"] is True
    assert payload["shield"]["stub_path"] == "tests/test_lonely_characterization.py"


# --------------------------------------------------------------------------- #
# --shield with an existing characterization test: skip with a message         #
# --------------------------------------------------------------------------- #
def test_shield_skips_existing_test_with_message(tmp_path, monkeypatch, capsys):
    _uncovered_project(tmp_path)
    step = _step(target="app/lonely.py")
    _force_plan(monkeypatch, step)
    _stub_apply(monkeypatch)
    _uncovered(monkeypatch)

    existing = tmp_path / "tests" / "test_lonely_characterization.py"
    existing.write_text("# already written by a human\n")

    rc = cmd_develop(_ns(target=str(tmp_path), shield=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "already exists" in out
    assert existing.read_text() == "# already written by a human\n"  # not clobbered


def test_shield_skips_existing_json(tmp_path, monkeypatch, capsys):
    _uncovered_project(tmp_path)
    step = _step(target="app/lonely.py")
    _force_plan(monkeypatch, step)
    _stub_apply(monkeypatch)
    _uncovered(monkeypatch)

    (tmp_path / "tests" / "test_lonely_characterization.py").write_text("# human\n")

    rc = cmd_develop(_ns(target=str(tmp_path), shield=True, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["reason"] == "shield-stub-exists"
    assert payload["shield"]["written"] is False


# --------------------------------------------------------------------------- #
# WITHOUT --shield: the uncovered path is byte-identical to today              #
# --------------------------------------------------------------------------- #
def test_no_shield_block_path_unchanged(tmp_path, monkeypatch, capsys):
    """The --apply uncovered path keeps blocking with rc 2 (no --shield)."""
    _uncovered_project(tmp_path)
    step = _step(target="app/lonely.py")
    _force_plan(monkeypatch, step)
    calls = _stub_apply(monkeypatch)
    _uncovered(monkeypatch)

    before = (tmp_path / "app" / "lonely.py").read_text()
    rc = cmd_develop(_ns(target=str(tmp_path), apply=True, shield=False))
    out = capsys.readouterr().out

    assert rc == 2  # blocked, non-zero so CI notices
    assert "FALSE green" in out
    assert calls == []  # nothing applied
    # no characterization stub written when --shield is absent
    assert not (tmp_path / "tests" / "test_lonely_characterization.py").exists()
    assert (tmp_path / "app" / "lonely.py").read_text() == before


def test_no_shield_uncovered_output_byte_identical(tmp_path, monkeypatch, capsys):
    """Pin the no-shield uncovered --apply output to the legacy guard text."""
    _uncovered_project(tmp_path)
    step = _step(target="app/lonely.py")
    _force_plan(monkeypatch, step)
    _stub_apply(monkeypatch)
    _uncovered(monkeypatch)

    rc = _develop_top(_ns(target=str(tmp_path), apply=True, shield=False), tmp_path)
    out = capsys.readouterr().out
    assert rc == 2
    # the exact legacy guard sentence — unchanged by the --shield addition
    assert (
        "⚠️ Your tests don't exercise `app/lonely.py`. Applying this and "
        "getting a green suite would be a FALSE green — the suite can't see "
        "the change. Add a test first, or re-run with --force to apply anyway."
    ) in out


def test_no_shield_dry_run_uncovered_still_warns(tmp_path, monkeypatch, capsys):
    """Default dry run on an uncovered target keeps its heads-up + rc 0."""
    _uncovered_project(tmp_path)
    step = _step(target="app/lonely.py")
    _force_plan(monkeypatch, step)
    _uncovered(monkeypatch)

    rc = cmd_develop(_ns(target=str(tmp_path), shield=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "no test exercises this module" in out
    assert "re-run with --apply to land it." in out
    assert not (tmp_path / "tests" / "test_lonely_characterization.py").exists()
