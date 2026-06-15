"""Residual defensive coverage for `apex deps` and `apex gate` baseline I/O.

Complements test_cli_deps.py / test_cli_gate_baseline.py by reaching the last
uncovered defensive arms:

  * `cmd_deps` degrades to an EMPTY audit (rc 0, clean report) when the underlying
    `audit_dependencies` raises — the "never crash" contract;
  * `_gate_load_baseline` returns None on a CORRUPT baseline file (unreadable
    bytes / non-dict JSON), and `--baseline` then treats it as missing (rc 2).

Deterministic, stdlib-only, LLM-free. The single forced failure is injected via
monkeypatch on the module seam, never the OS or network.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

import app.cli_reporting as cli_reporting
from app.cli_reporting import (
    _gate_load_baseline,
    _gate_save_baseline,
    cmd_deps,
)


# --------------------------------------------------------------------------- #
# cmd_deps defensive degrade-to-empty (lines 820-825)
# --------------------------------------------------------------------------- #

def _deps_ns(target: Path, *, json_out: bool = False, strict: bool = False):
    return argparse.Namespace(target=str(target), json=json_out, strict=strict)


def _run_deps(target: Path, *, json_out: bool = False, strict: bool = False):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_deps(_deps_ns(target, json_out=json_out, strict=strict))
    return rc, buf.getvalue()


def test_cmd_deps_degrades_to_empty_when_audit_raises(tmp_path, monkeypatch):
    def boom(root):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(cli_reporting, "audit_dependencies", boom, raising=False)
    # cmd_deps imports audit_dependencies locally from app.engine.dependency_audit,
    # so patch there too.
    import app.engine.dependency_audit as dep_mod

    monkeypatch.setattr(dep_mod, "audit_dependencies", boom)

    rc, out = _run_deps(tmp_path)
    assert rc == 0
    # an empty audit renders the clean "no dependency issues" line.
    assert "no dependency issues found" in out.lower()


def test_cmd_deps_degraded_empty_json_shape(tmp_path, monkeypatch):
    import app.engine.dependency_audit as dep_mod

    monkeypatch.setattr(
        dep_mod, "audit_dependencies",
        lambda root: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    rc, out = _run_deps(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert data == {
        "declared": [],
        "imported_third_party": [],
        "unused": [],
        "undeclared": [],
        "unpinned": [],
    }


def test_cmd_deps_degraded_empty_passes_strict(tmp_path, monkeypatch):
    # No findings (empty audit) -> --strict still returns 0.
    import app.engine.dependency_audit as dep_mod

    monkeypatch.setattr(
        dep_mod, "audit_dependencies",
        lambda root: (_ for _ in ()).throw(ValueError("boom")),
    )
    rc, _ = _run_deps(tmp_path, strict=True)
    assert rc == 0


# --------------------------------------------------------------------------- #
# _gate_load_baseline: corrupt baseline -> None (lines 611-612)
# --------------------------------------------------------------------------- #

def test_gate_load_baseline_missing_returns_none(tmp_path):
    assert _gate_load_baseline(tmp_path) is None


def test_gate_load_baseline_corrupt_json_returns_none(tmp_path):
    path = tmp_path / ".apex" / "gate-baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not json", encoding="utf-8")
    # json.loads raises -> the except arm returns None (defensive).
    assert _gate_load_baseline(tmp_path) is None


def test_gate_load_baseline_non_dict_json_returns_none(tmp_path):
    path = tmp_path / ".apex" / "gate-baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")
    # valid JSON but not a dict -> None.
    assert _gate_load_baseline(tmp_path) is None


def test_gate_load_baseline_valid_roundtrips(tmp_path):
    metrics = {
        "score": 91,
        "letter": "A",
        "security_modules": 0,
        "bug_modules": 0,
        "out_of_scope_pct": 0.0,
    }
    _gate_save_baseline(tmp_path, metrics)
    loaded = _gate_load_baseline(tmp_path)
    assert loaded == metrics


# --------------------------------------------------------------------------- #
# cmd_gate: a corrupt baseline reads as "missing" -> rc 2
# --------------------------------------------------------------------------- #

_GATE_DEFAULTS = dict(
    min_score=0,
    max_security=0,
    max_bugs=0,
    max_out_of_scope=-1,
    save_baseline=False,
    baseline=False,
    tolerance=0,
)


def _gate_ns(target: Path, *, json_out: bool = False, **overrides):
    kwargs = {**_GATE_DEFAULTS, **overrides}
    return argparse.Namespace(target=str(target), json=json_out, **kwargs)


def _run_gate(target: Path, *, json_out: bool = False, **overrides):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli_reporting.cmd_gate(_gate_ns(target, json_out=json_out, **overrides))
    return rc, buf.getvalue()


def test_gate_corrupt_baseline_treated_as_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli_reporting, "_gate_metrics",
        lambda root: {
            "score": 90, "letter": "A", "security_modules": 0,
            "bug_modules": 0, "out_of_scope_pct": 0.0,
        },
    )
    path = tmp_path / ".apex" / "gate-baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{corrupt", encoding="utf-8")

    rc, out = _run_gate(tmp_path, baseline=True)
    assert rc == 2
    assert "no baseline saved" in out
