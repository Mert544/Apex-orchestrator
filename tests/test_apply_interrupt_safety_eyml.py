"""Falsifiable tests for apply-time interrupt safety — the fix for the audit's
crash-window finding (observed live on the interrupted ``pyparsing`` campaign):
``apply_rename`` writes the planned files and only THEN verifies; a
KeyboardInterrupt/SIGTERM during the (minutes-long) verify used to propagate
straight out, leaving the target tree MODIFIED with no rollback and no record.

The fix is two-layered, and each layer is pinned red-first here:

* a ``BaseException`` guard around the write→verify window rolls the move back
  byte-exactly (created files deleted) and re-raises — a cancelled run never
  leaves a silently modified tree;
* an intent journal (``.apex/pending-apply.json``: every planned file's
  pre-apply text, ``null`` for created ones) lands on disk BEFORE the first
  tree write and is cleared when the move settles — so even a hard kill
  (SIGKILL/OOM), which no in-process guard can catch, leaves an honest,
  reconcilable record of exactly what was in flight.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.execution import cross_file_rename as cfr
from app.execution.cross_file_rename import RenamePlan, apply_rename


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "core.py").write_text(
        "def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import f\n\n\ndef test_f():\n    assert f() == 1\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _plan(rel: str, original: str, new: str,
          creates: dict[str, str] | None = None) -> RenamePlan:
    plan = RenamePlan(old=rel, new="edit")
    plan.originals[rel] = original
    plan.new_contents[rel] = new
    plan.edits_by_file[rel] = 1
    for crel, ctext in (creates or {}).items():
        plan.new_contents[crel] = ctext
        plan.edits_by_file[crel] = 1
    return plan


def test_interrupt_mid_verify_rolls_back_and_reraises(tmp_path, monkeypatch):
    # The pyparsing shape: Ctrl-C lands while the (slow) verify runs. The move
    # must be rolled back byte-exactly — including deleting a created file —
    # and the interrupt must still propagate to the caller.
    _project(tmp_path)
    original = (tmp_path / "app" / "core.py").read_text(encoding="utf-8")

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cfr, "run_full_suite_verification", interrupted)
    plan = _plan("app/core.py", original, "def f():\n    return 2\n",
                 creates={"app/new_helper.py": "X = 1\n"})
    with pytest.raises(KeyboardInterrupt):
        apply_rename(tmp_path, plan, verify=True)

    assert (tmp_path / "app" / "core.py").read_text(encoding="utf-8") == original
    assert not (tmp_path / "app" / "new_helper.py").exists()
    assert not (tmp_path / ".apex" / "pending-apply.json").exists()


def test_interrupt_mid_scoped_verify_rolls_back(tmp_path, monkeypatch):
    # Same guard on the impact-scoped path.
    _project(tmp_path)
    original = (tmp_path / "app" / "core.py").read_text(encoding="utf-8")

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cfr, "_verify_impact_scope", interrupted)
    plan = _plan("app/core.py", original, "def f():\n    return 2\n")
    with pytest.raises(KeyboardInterrupt):
        apply_rename(tmp_path, plan, verify=True, impact_scope=True)

    assert (tmp_path / "app" / "core.py").read_text(encoding="utf-8") == original
    assert not (tmp_path / ".apex" / "pending-apply.json").exists()


def test_journal_exists_during_verify_and_clears_on_settle(tmp_path, monkeypatch):
    # The intent journal must be ON DISK while the verify runs (that is the
    # whole point: a hard kill in that window leaves the record) and gone once
    # the move settles.
    _project(tmp_path)
    original = (tmp_path / "app" / "core.py").read_text(encoding="utf-8")
    seen: dict = {}

    def spying(root, out, **kwargs):
        journal = Path(root) / ".apex" / "pending-apply.json"
        seen["existed"] = journal.exists()
        if journal.exists():
            seen["payload"] = json.loads(journal.read_text(encoding="utf-8"))
        out["verified"] = True
        out["rolled_back"] = False
        return True

    monkeypatch.setattr(cfr, "run_full_suite_verification", spying)
    plan = _plan("app/core.py", original, "def f():\n    return 1  # tidy\n")
    res = apply_rename(tmp_path, plan, verify=True)

    assert res["applied"] is True
    assert seen["existed"] is True, "journal must exist while verify runs"
    assert seen["payload"]["schema"] == "apex-pending-apply/1"
    assert seen["payload"]["changed"] == {"app/core.py": original}
    assert not (tmp_path / ".apex" / "pending-apply.json").exists()


def test_journal_records_created_files_as_null_originals(tmp_path):
    # Unit pin of the journal shape: a created file has no original (null), so
    # a reconcile pass knows to DELETE it rather than restore text.
    _project(tmp_path)
    plan = _plan("app/core.py", "def f():\n    return 1\n",
                 "def f():\n    return 1  # tidy\n",
                 creates={"app/new_helper.py": "X = 1\n"})
    journal = cfr._write_pending_journal(tmp_path, plan, ["app/new_helper.py"])
    payload = json.loads(journal.read_text(encoding="utf-8"))
    assert payload["created"] == ["app/new_helper.py"]
    assert payload["changed"]["app/new_helper.py"] is None
    assert payload["changed"]["app/core.py"] == "def f():\n    return 1\n"
    cfr._clear_pending_journal(journal)
    assert not journal.exists()


def test_no_verify_apply_still_clears_the_journal(tmp_path):
    # verify=False settles by contract (kept, unverified) — the journal must
    # not linger and cry wolf about a move that finished.
    _project(tmp_path)
    original = (tmp_path / "app" / "core.py").read_text(encoding="utf-8")
    plan = _plan("app/core.py", original, "def f():\n    return 1  # tidy\n")
    res = apply_rename(tmp_path, plan, verify=False)
    assert res["applied"] is True
    assert not (tmp_path / ".apex" / "pending-apply.json").exists()
