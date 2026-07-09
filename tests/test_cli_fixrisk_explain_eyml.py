"""The ``apex fix-risk --explain`` flag: a per-signal risk breakdown for one
``(--action, --module)`` candidate, surfaced through the EXISTING ``fix-risk``
CLI surface (no new top-level verb) — see ``app/cli_insight.py::cmd_fixrisk``.

Deterministic, stdlib-only, LLM-free. Fixtures write a fake proof-of-fix JSON
to the real on-disk location the loader reads, matching the house style of
``tests/test_cli_trackrecord.py`` / ``tests/test_fix_risk_model_eyml.py``.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

import app.cli_insight as cli_insight
from app.cli_insight import cmd_fixrisk
from app.engine.proof_of_fix import SCHEMA


def _write_proof(root: Path, fixes: list[dict]) -> None:
    apex_dir = root / ".apex"
    apex_dir.mkdir(parents=True, exist_ok=True)
    proof = {"schema": SCHEMA, "schema_version": "1.0",
              "generated_at": "2026-01-01T00:00:00+00:00", "fixes": fixes}
    (apex_dir / "p.json").write_text(json.dumps(proof), encoding="utf-8")


def _fix(action: str, module: str, outcome: str) -> dict:
    return {"finding": {"action": action, "target": module}, "outcome": outcome}


def _run(args: argparse.Namespace) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_fixrisk(args)
    return rc, buf.getvalue()


def _namespace(target: Path, explain: bool = False, action: str = "", module: str = "") -> argparse.Namespace:
    return argparse.Namespace(target=str(target), explain=explain, action=action, module=module)


# --- deterministic rendering --------------------------------------------------


def test_cli_fixrisk_explain_flag_deterministic(tmp_path: Path):
    """Two invocations of ``--explain --action X --module Y`` on the same
    fixture root produce byte-identical stdout."""
    fixes = [_fix("act", "app/m.py", "applied") for _ in range(3)]
    _write_proof(tmp_path, fixes)

    rc1, out1 = _run(_namespace(tmp_path, explain=True, action="act", module="app/m.py"))
    rc2, out2 = _run(_namespace(tmp_path, explain=True, action="act", module="app/m.py"))
    assert rc1 == 0
    assert rc2 == 0
    assert out1 == out2
    assert "Fix-Risk Explanation" in out1
    # The explanation scores in recency-decayed mode while the aggregate
    # `apex fix-risk` report scores flat — the output must DISCLOSE that, or
    # a reader comparing the two surfaces meets two unexplained numbers.
    assert "Mode: recency-decayed" in out1


def test_cli_fixrisk_explain_no_history_is_honest_empty(tmp_path: Path):
    """No ``.apex`` dir at all: the explanation states plainly there is no
    proof history, and the command still exits ``0`` (read-only report)."""
    rc, out = _run(_namespace(tmp_path, explain=True, action="act", module="app/m.py"))
    assert rc == 0
    assert "No proof history" in out


# --- required-args guard -----------------------------------------------------


def test_cli_fixrisk_explain_requires_action_module(tmp_path: Path):
    """``--explain`` alone (no ``--action``/``--module``) is a deterministic
    usage error: non-zero exit, no traceback, no crash."""
    rc, out = _run(_namespace(tmp_path, explain=True))
    assert rc == 2
    assert out.strip()


def test_cli_fixrisk_explain_requires_module_when_only_action_given(tmp_path: Path):
    """Half of the pair supplied is still an error."""
    rc, out = _run(_namespace(tmp_path, explain=True, action="act"))
    assert rc == 2


def test_cli_fixrisk_explain_requires_action_when_only_module_given(tmp_path: Path):
    """The other half missing is likewise an error."""
    rc, out = _run(_namespace(tmp_path, explain=True, module="app/m.py"))
    assert rc == 2


# --- default (non-explain) path is unaffected --------------------------------


def test_cli_fixrisk_default_path_unchanged(tmp_path: Path):
    """Without ``--explain`` the command still renders the aggregate report,
    exactly as before this flag existed."""
    rc, out = _run(_namespace(tmp_path))
    assert rc == 0
    assert "# Fix-Risk Model" in out


# --- parser wiring: reuses the existing `fix-risk` subcommand ---------------


def test_fixrisk_subparser_exposes_explain_action_module_flags():
    """The flags are wired onto the EXISTING ``fix-risk`` subcommand (via
    ``register_parsers``), not a new top-level verb — mirrors the precedent
    in ``tests/test_cli_trackrecord.py``."""
    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    cli_insight.register_parsers(sub)
    assert "fix-risk" in sub.choices
    assert sub.choices["fix-risk"].get_default("func") is cmd_fixrisk

    ns = parser.parse_args(
        ["fix-risk", "--explain", "--action", "act", "--module", "app/m.py"]
    )
    assert ns.explain is True
    assert ns.action == "act"
    assert ns.module == "app/m.py"
    assert ns.func is cmd_fixrisk
