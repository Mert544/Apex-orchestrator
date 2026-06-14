"""The `apex trackrecord` subcommand: Apex's PROVEN, test-verified fix history
on the repo it sits in — the "proven, over time" story.

Grounded in the two artifacts Apex already keeps:
  - ``.apex/idea-memory.json`` — per-fix-type landing rates (IdeaMemory.summary).
  - ``.apex/proof-of-fix.json`` — the evidence trail of applied, verified fixes.

Deterministic, stdlib-only, LLM-free. The fixtures here write both ledgers into
a tmp ``.apex`` and assert the rendered report and its --json mirror.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

from app.cli_insight import cmd_trackrecord
from app.engine.idea_memory import IdeaMemory


def _run(target: Path, json_out: bool = False) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_trackrecord(argparse.Namespace(target=str(target), json=json_out))
    return rc, buf.getvalue()


def _write_memory(root: Path) -> None:
    """A synthetic memory ledger: sort_imports lands every time (reliable),
    harden never lands (risky) — exactly the shape IdeaMemory.summary surfaces."""
    mem = IdeaMemory()
    results = []
    for _ in range(50):
        results.append({"operator": "sort_imports", "applied": True})
    for _ in range(3):
        results.append({"operator": "harden", "rolled_back": True})
    for _ in range(4):  # a mixed middle band
        results.append({"operator": "rename", "applied": True})
    for _ in range(4):
        results.append({"operator": "rename", "rolled_back": True})
    mem.record_outcomes({"results": results})
    mem.save(str(root))


def _write_proof(root: Path, applied: int = 7, rolled_back: int = 1) -> None:
    fixes = [
        {"outcome": "applied", "finding": {"target": f"app/m{i}.py"}}
        for i in range(applied)
    ]
    fixes += [
        {"outcome": "rolled_back", "finding": {"target": f"app/r{i}.py"}}
        for i in range(rolled_back)
    ]
    proof = {
        "schema": "apex-proof-of-fix",
        "generated_at": "2026-06-14T00:00:00+00:00",
        "totals": {"applied": applied, "rolled_back": rolled_back, "blocked": 0},
        "fixes": fixes,
    }
    (root / ".apex").mkdir(parents=True, exist_ok=True)
    (root / ".apex" / "proof-of-fix.json").write_text(
        json.dumps(proof, indent=2), encoding="utf-8")


# --- fresh repo: the empty path --------------------------------------------

def test_fresh_repo_prints_no_track_record(tmp_path):
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "no track record yet" in out
    assert "apex maintain" in out


def test_fresh_repo_json_is_valid_and_empty(tmp_path):
    rc, out = _run(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert data["has_record"] is False
    assert data["verified_fixes"] == 0
    assert data["by_type"] == []


# --- populated repo: the proven story ---------------------------------------

def test_headline_counts_verified_fixes(tmp_path):
    _write_proof(tmp_path, applied=7, rolled_back=1)
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "7 fixes" in out
    assert "test-verified" in out
    # The rolled-back attempts are reported as the safety net, not as failure.
    assert "rolled back" in out


def test_singular_fix_wording(tmp_path):
    _write_proof(tmp_path, applied=1, rolled_back=0)
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "1 fix" in out
    assert "1 fixes" not in out


def test_by_fix_type_shows_landing_rates(tmp_path):
    _write_memory(tmp_path)
    _write_proof(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "By fix type" in out
    assert "sort_imports" in out
    assert "100% landed over 50 samples" in out
    assert "harden" in out
    assert "0% landed over 3 samples" in out
    # The reliable lead, the risky carry the warning.
    assert "reliable — lead with this" in out
    assert "risky — expect blocks/rollbacks" in out


def test_memory_only_repo_has_a_record(tmp_path):
    # IdeaMemory present but no proof-of-fix: still a track record (rates exist).
    _write_memory(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "no track record yet" not in out
    assert "sort_imports" in out


def test_proof_only_repo_has_a_record(tmp_path):
    _write_proof(tmp_path, applied=3, rolled_back=0)
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "3 fixes" in out
    # No memory => no per-type section, but the headline still lands.
    assert "By fix type" not in out


# --- determinism, JSON, ordering, exit code ---------------------------------

def test_json_is_valid_and_grounded(tmp_path):
    _write_memory(tmp_path)
    _write_proof(tmp_path, applied=7, rolled_back=1)
    rc, out = _run(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert data["has_record"] is True
    assert data["verified_fixes"] == 7
    assert data["rolled_back"] == 1
    keys = [row["key"] for row in data["by_type"]]
    assert "sort_imports" in keys
    assert "harden" in keys


def test_by_type_sorted_success_desc_then_key(tmp_path):
    _write_memory(tmp_path)
    rc, out = _run(tmp_path, json_out=True)
    data = json.loads(out)
    ordering = [(-r["success_rate"], r["key"]) for r in data["by_type"]]
    assert ordering == sorted(ordering)
    # sort_imports (100%) leads; harden (0%) trails.
    assert data["by_type"][0]["key"] == "sort_imports"
    assert data["by_type"][-1]["key"] == "harden"


def test_deterministic_byte_for_byte(tmp_path):
    _write_memory(tmp_path)
    _write_proof(tmp_path)
    _, out1 = _run(tmp_path)
    _, out2 = _run(tmp_path)
    assert out1 == out2
    _, j1 = _run(tmp_path, json_out=True)
    _, j2 = _run(tmp_path, json_out=True)
    assert j1 == j2


def test_corrupt_proof_does_not_crash(tmp_path):
    (tmp_path / ".apex").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".apex" / "proof-of-fix.json").write_text("{not json", encoding="utf-8")
    rc, out = _run(tmp_path)
    assert rc == 0
    # Unreadable proof collapses to empty: fresh-repo wording.
    assert "no track record yet" in out


def test_returns_zero_on_all_paths(tmp_path):
    assert _run(tmp_path)[0] == 0
    _write_proof(tmp_path)
    assert _run(tmp_path)[0] == 0
    _write_memory(tmp_path)
    assert _run(tmp_path)[0] == 0
    assert _run(tmp_path, json_out=True)[0] == 0


def test_registered_via_parser():
    import app.cli_insight as cli_insight

    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    cli_insight.register_parsers(sub)
    assert "trackrecord" in sub.choices
    assert sub.choices["trackrecord"].get_default("func") is cmd_trackrecord
