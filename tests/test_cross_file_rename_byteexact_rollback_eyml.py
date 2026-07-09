"""Byte-exact rollback for ``app.execution.cross_file_rename`` (L3 — Eller).

Companion to ``tests/test_tree_snapshot_byteexact_eyml.py``: the per-move
rollback path (``_rollback``) and the pending-apply journal
(``_write_pending_journal``) must ALSO restore/record a CRLF/BOM original
losslessly, not the universal-newline-normalized ``plan.originals`` text.

The APPLY side (writing the NEW transformed content) intentionally stays
text-mode — only restoring ORIGINALS must be byte-exact, per the approved
design. Journal round-trip uses the additive ``changed_b64`` field (base64 of
the raw captured bytes); the pre-existing ``changed`` (text) key is left
exactly as before so a naive reader still degrades to today's behaviour.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from app.execution import cross_file_rename as cfr
from app.execution.cross_file_rename import RenamePlan, apply_rename


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import f\n\n\ndef test_f():\n    assert f() == 1\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _crlf_plan(tmp_path: Path) -> tuple[RenamePlan, bytes]:
    rel = "app/core.py"
    original_bytes = b"def f():\r\n    return 1\r\n"
    (tmp_path / "app" / "core.py").write_bytes(original_bytes)
    # plan.originals carries the universal-newline TEXT form, exactly as every
    # real planner records it today (Path.read_text default) — the LF-
    # normalized string is what byte-exact rollback must NOT fall back to.
    original_text = original_bytes.decode("utf-8")
    plan = RenamePlan(old="f", new="edit")
    plan.originals[rel] = original_text.replace("\r\n", "\n")
    plan.new_contents[rel] = "def f():\n    return 2\n"
    plan.edits_by_file[rel] = 1
    return plan, original_bytes


def test_journal_records_crlf_originals_losslessly(tmp_path):
    _project(tmp_path)
    plan, original_bytes = _crlf_plan(tmp_path)
    raw_originals = cfr._capture_raw_originals(tmp_path, plan, [])

    journal = cfr._write_pending_journal(tmp_path, plan, [], raw_originals)
    payload = json.loads(journal.read_text(encoding="utf-8"))

    assert "changed_b64" in payload
    decoded = base64.b64decode(payload["changed_b64"]["app/core.py"])
    assert decoded == original_bytes
    # The plain-text sibling key is still populated (never removed).
    assert payload["changed"]["app/core.py"] == plan.originals["app/core.py"]
    assert payload["schema"] == "apex-pending-apply/1"
    cfr._clear_pending_journal(journal)


def test_rollback_restores_crlf_bytes_exactly(tmp_path, monkeypatch):
    _project(tmp_path)
    plan, original_bytes = _crlf_plan(tmp_path)

    def failing(*args, **kwargs):
        return False

    monkeypatch.setattr(cfr, "run_full_suite_verification", failing)
    res = apply_rename(tmp_path, plan, verify=True)

    assert res["applied"] is False
    assert res["rolled_back"] is True
    assert (tmp_path / "app" / "core.py").read_bytes() == original_bytes


def test_rollback_crlf_under_impact_scope_and_covered_only(tmp_path, monkeypatch):
    _project(tmp_path)
    plan, original_bytes = _crlf_plan(tmp_path)

    def scoped_red(*args, **kwargs):
        return False, {"scoped": True, "tests": ["tests/test_core.py"],
                        "deselected": [], "passed": False}

    monkeypatch.setattr(cfr, "_verify_scoped", scoped_red)
    res = apply_rename(tmp_path, plan, verify=True, impact_scope=True)

    assert res["applied"] is False
    assert res["rolled_back"] is True
    assert (tmp_path / "app" / "core.py").read_bytes() == original_bytes


def test_rollback_crlf_withheld_uncovered_path(tmp_path, monkeypatch):
    # Guards the _withhold_uncovered rollback call site specifically: a green
    # suite that can't vouch for the change at its tier still restores CRLF
    # bytes exactly, not LF-normalized text.
    _project(tmp_path)
    plan, original_bytes = _crlf_plan(tmp_path)

    def green(root, out, **kwargs):
        out["verified"] = True
        out["rolled_back"] = False
        out["coverage"] = "none"
        return True

    monkeypatch.setattr(cfr, "run_full_suite_verification", green)
    res = apply_rename(tmp_path, plan, verify=True, covered_only=True, tier=1)

    assert res.get("withheld_uncovered") is True
    assert res["rolled_back"] is True
    assert (tmp_path / "app" / "core.py").read_bytes() == original_bytes
