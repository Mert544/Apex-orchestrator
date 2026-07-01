"""The `apex proof` subcommand: make the proof-of-fix evidence VISIBLE.

Apex already *computes* a full proof-of-fix bundle per maintain run
(``.apex/proof-of-fix.json``) plus an archived history (``proof-<hash>.json``),
a tamper-evident ``proof_hash`` and an aggregate track record — but nothing ever
rendered it for a human. `apex proof` loads and prints exactly those artifacts;
it invents no analysis and never mutates anything.

These tests write a synthetic ``.apex/proof-of-fix.json`` (schema
``apex-proof-of-fix``) with a mix of outcomes and assert the rendered report,
its --json mirror, the tamper hash (equal to ``proof_of_fix.proof_hash``
computed directly, proving reuse not re-hashing), byte-for-byte determinism, and
that every path exits 0. Deterministic, stdlib-only, LLM-free.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

from app.cli_insight import cmd_proof, render_proof_markdown
from app.engine import proof_of_fix


def _run(target: Path, json_out: bool = False) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_proof(argparse.Namespace(target=str(target), json=json_out))
    return rc, buf.getvalue()


def _applied_fix(target: str, level: str = "function", commit: bool = True) -> dict:
    fix = {
        "finding": {"label": "dead-code", "action": "remove_unused", "target": target},
        "outcome": "applied",
        "verification": {"performed": True, "strength": {"level": level}},
        "rollback": {"occurred": False, "reason": ""},
    }
    if commit:
        fix["commit_hash"] = "abc1234"
    return fix


def _rolled_back_fix(target: str, reason: str) -> dict:
    return {
        "finding": {"label": "risky", "action": "harden", "target": target},
        "outcome": "rolled_back",
        "verification": {"performed": True},
        "rollback": {"occurred": True, "reason": reason},
    }


def _blocked_fix(target: str, reason: str) -> dict:
    return {
        "finding": {"label": "unsafe", "action": "rewrite", "target": target},
        "outcome": "blocked",
        "verification": {"performed": False},
        "rollback": {"occurred": False, "reason": ""},
        "blocked_reason": reason,
    }


def _withheld_fix(target: str, reason: str) -> dict:
    # An applied fix a commit gate (fence) held back for human review: on disk,
    # NOT committed — proof_of_fix._disclose_withhold's exact shape.
    fix = _applied_fix(target, level="module", commit=False)
    fix["committed"] = False
    fix["commit_withheld"] = True
    fix["fenced"] = True
    fix["withheld_reason"] = reason
    return fix


def _proof(fixes: list[dict], objective: str = "clean up dead code",
           mode: str = "maintain") -> dict:
    applied = sum(1 for f in fixes if f["outcome"] == "applied")
    rolled = sum(1 for f in fixes if f["outcome"] == "rolled_back")
    blocked = sum(1 for f in fixes if f["outcome"] == "blocked")
    return {
        "schema": "apex-proof-of-fix",
        "schema_version": 1,
        "generated_at": "2026-06-14T00:00:00+00:00",
        "objective": objective,
        "mode": mode,
        "verify": True,
        "totals": {"applied": applied, "rolled_back": rolled, "blocked": blocked},
        "fixes": fixes,
    }


def _write_proof(root: Path, fixes: list[dict], **kw) -> dict:
    proof = _proof(fixes, **kw)
    (root / ".apex").mkdir(parents=True, exist_ok=True)
    (root / ".apex" / "proof-of-fix.json").write_text(
        json.dumps(proof, indent=2), encoding="utf-8")
    return proof


def _write_archive(root: Path, proof: dict) -> None:
    """Drop a proof beside the latest pointer as an archived proof-<hash>.json,
    named the way proof_of_fix._archive_name derives it (content hash)."""
    digest = proof_of_fix.proof_hash(proof).split(":", 1)[-1]
    (root / ".apex").mkdir(parents=True, exist_ok=True)
    (root / ".apex" / f"proof-{digest}.json").write_text(
        json.dumps(proof, indent=2), encoding="utf-8")


# --- empty state ------------------------------------------------------------

def test_empty_state_no_proof(tmp_path):
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "No proof-of-fix evidence yet" in out
    assert "apex maintain" in out


def test_empty_state_json(tmp_path):
    rc, out = _run(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert data["has_proof"] is False
    assert data["moves"] == []
    # A zeroed track record shape, not a missing key.
    assert data["track_record"]["proofs"] == 0


# --- the moves table --------------------------------------------------------

def test_renders_moves_table(tmp_path):
    _write_proof(tmp_path, [
        _applied_fix("app/x.py"),
        _rolled_back_fix("app/r.py", "suite went red: test_foo"),
        _blocked_fix("app/b.py", "unsafe to rewrite"),
    ])
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "## Moves (this run)" in out
    assert "| Outcome | Finding" in out
    assert "applied" in out
    assert "rolled_back" in out
    assert "blocked" in out
    assert "app/x.py" in out
    assert "app/r.py" in out
    assert "app/b.py" in out
    assert "Totals: 1 applied, 1 rolled back, 1 blocked." in out


def test_applied_shows_coverage_and_reason(tmp_path):
    _write_proof(tmp_path, [
        _applied_fix("app/x.py", level="function"),
        _rolled_back_fix("app/r.py", "regression in test_bar"),
        _blocked_fix("app/b.py", "flagged: needs human review"),
    ])
    rc, out = _run(tmp_path)
    assert rc == 0
    # applied fix surfaces its recorded coverage level verbatim.
    assert "function" in out
    # rolled_back surfaces its rollback reason; blocked its blocked_reason.
    assert "regression in test_bar" in out
    assert "flagged: needs human review" in out


def test_coverage_none_not_dressed_up(tmp_path):
    # A green suite that never touched the module reads "none" — NOT upgraded to
    # look verified. Honest proof: an unverified move never renders as verified.
    _write_proof(tmp_path, [_applied_fix("app/x.py", level="none")])
    rc, out = _run(tmp_path)
    assert rc == 0
    row = [ln for ln in out.splitlines() if "app/x.py" in ln][0]
    assert "| none |" in row
    assert "function" not in row


def test_withheld_move_disclosed(tmp_path):
    _write_proof(tmp_path, [
        _withheld_fix("app/w.py", "pending human review"),
    ])
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "withheld" in out
    assert "pending human review" in out
    # A withheld fix is applied on disk but NOT committed — the reader must see
    # that, never a bare "yes".
    row = [ln for ln in out.splitlines() if "app/w.py" in ln][0]
    assert "no" in row
    assert "fence" in row


# --- tamper evidence --------------------------------------------------------

def test_tamper_hash_line(tmp_path):
    proof = _write_proof(tmp_path, [
        _applied_fix("app/x.py"),
        _blocked_fix("app/b.py", "unsafe"),
    ])
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "## Tamper evidence" in out
    assert "sha256:" in out
    # The rendered hash equals proof_of_fix.proof_hash computed directly:
    # the command REUSES the seal, it does not re-hash.
    expected = proof_of_fix.proof_hash(proof)
    assert f"proof_hash: {expected}" in out
    assert "verdict:" in out


# --- track record -----------------------------------------------------------

def test_track_record_section(tmp_path):
    # Latest proof + one archived proof with DISTINCT content (distinct hash →
    # distinct filename → counted as a second proof in the history).
    latest = _write_proof(tmp_path, [
        _applied_fix("app/x.py"),
        _applied_fix("app/y.py"),
    ])
    archived = _proof(
        [_applied_fix("app/z.py"), _rolled_back_fix("app/r.py", "red")],
        objective="older run",
    )
    archived["generated_at"] = "2026-06-01T00:00:00+00:00"
    _write_archive(tmp_path, archived)
    assert proof_of_fix.proof_hash(archived) != proof_of_fix.proof_hash(latest)

    rc, out = _run(tmp_path)
    assert rc == 0
    assert "## Track record (all runs on this repo)" in out
    assert "Proofs: 2" in out
    # A by-action row for the actions cited (remove_unused / harden).
    assert "remove_unused" in out
    assert "harden" in out


def test_track_record_json_shape(tmp_path):
    _write_proof(tmp_path, [_applied_fix("app/x.py")])
    rc, out = _run(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert data["has_proof"] is True
    assert data["track_record"]["proofs"] == 1
    assert data["track_record"]["fixes"] == 1
    assert data["moves"][0]["outcome"] == "applied"


# --- determinism, resilience, exit code -------------------------------------

def test_deterministic_byte_for_byte(tmp_path):
    _write_proof(tmp_path, [
        _applied_fix("app/x.py"),
        _rolled_back_fix("app/r.py", "red"),
    ])
    _, a1 = _run(tmp_path)
    _, a2 = _run(tmp_path)
    assert a1 == a2
    _, j1 = _run(tmp_path, json_out=True)
    _, j2 = _run(tmp_path, json_out=True)
    assert j1 == j2


def test_generated_at_displayed_not_regenerated(tmp_path):
    # The one time-bearing field is carried verbatim, never used to order or
    # regenerate — so the rendered record is stable. (It lives in --json.)
    _write_proof(tmp_path, [_applied_fix("app/x.py")])
    _, out = _run(tmp_path, json_out=True)
    data = json.loads(out)
    assert data["generated_at"] == "2026-06-14T00:00:00+00:00"


def test_corrupt_proof_does_not_crash(tmp_path):
    (tmp_path / ".apex").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".apex" / "proof-of-fix.json").write_text("{not json", encoding="utf-8")
    rc, out = _run(tmp_path)
    assert rc == 0
    # Unreadable proof AND no history collapses to the honest empty state.
    assert "No proof-of-fix evidence yet" in out


def test_returns_zero_on_all_paths(tmp_path):
    assert _run(tmp_path)[0] == 0
    _write_proof(tmp_path, [_applied_fix("app/x.py")])
    assert _run(tmp_path)[0] == 0
    assert _run(tmp_path, json_out=True)[0] == 0


def test_render_empty_state_pure():
    # The renderer is a pure function of the record dict — empty in, honest out.
    md = render_proof_markdown({"has_proof": False, "moves": [], "track_record": {}})
    assert "No proof-of-fix evidence yet" in md
    assert md.startswith("# Apex proof of fix")


# --- parser registration / dispatch identity --------------------------------

def test_registered_via_parser():
    import app.cli_insight as cli_insight

    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    cli_insight.register_parsers(sub)
    assert "proof" in sub.choices
    assert sub.choices["proof"].get_default("func") is cmd_proof
