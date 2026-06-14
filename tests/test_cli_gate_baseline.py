"""`apex gate` BASELINE (regression) mode: "did THIS change make it worse?".

Absolute thresholds (tested in test_cli_gate.py) answer "is this repo good
enough?". Baseline mode answers the more useful CI question: does the current
state REGRESS against a saved snapshot? The contract under test:

  * `--save-baseline` snapshots the current `_gate_metrics` to
    `.apex/gate-baseline.json` (deterministic JSON, sorted keys) and exits 0;
  * `--baseline` with NO saved file -> clear message + a NON-zero rc (2) so a
    misconfigured CI is visible, not silently green;
  * a baseline equal to current -> PASSED (no regressions, rc 0);
  * a higher-scoring baseline (current dropped) -> REGRESSED, rc 1;
  * more security / bug modules than baseline -> rc 1;
  * `--tolerance N` absorbs a small score drop;
  * the comparison is deterministic and `--json` carries a `baseline` block;
  * baseline mode composes with the absolute checks (fail on EITHER).

Deterministic, stdlib-only, LLM-free. We monkeypatch `_gate_metrics` (the single
metric source) to force a deterministic current reading, mirroring how
test_cli_gate.py monkeypatches the profiler.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

import app.cli_reporting as cli_reporting
from app.cli_reporting import cmd_gate

# Mirror the parser defaults so a Namespace is a faithful bare gate plus the
# additive baseline flags (all opt-in / off by default).
_DEFAULTS = dict(
    min_score=0,
    max_security=0,
    max_bugs=0,
    max_out_of_scope=-1,
    save_baseline=False,
    baseline=False,
    tolerance=0,
)


def _ns(target: Path, *, json_out: bool = False, **overrides) -> argparse.Namespace:
    kwargs = {**_DEFAULTS, **overrides}
    return argparse.Namespace(target=str(target), json=json_out, **kwargs)


def _run(target: Path, *, json_out: bool = False, **overrides) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_gate(_ns(target, json_out=json_out, **overrides))
    return rc, buf.getvalue()


def _patch_metrics(monkeypatch, metrics: dict) -> None:
    """Force `cmd_gate`'s single metric source to return ``metrics``.

    Mirrors test_cli_gate.py's profiler patch, but at the `_gate_metrics` seam so
    the test fully controls every gated number (score + counts + out-of-scope).
    """
    monkeypatch.setattr(cli_reporting, "_gate_metrics", lambda root: dict(metrics))


def _clean_metrics(**overrides) -> dict:
    base = dict(
        score=90,
        letter="A",
        security_modules=0,
        bug_modules=0,
        out_of_scope_pct=0.0,
    )
    base.update(overrides)
    return base


def _baseline_path(root: Path) -> Path:
    return root / ".apex" / "gate-baseline.json"


# --- --save-baseline ---------------------------------------------------------

def test_save_baseline_writes_file_and_returns_zero(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics(score=88))
    rc, out = _run(tmp_path, save_baseline=True)
    assert rc == 0
    path = _baseline_path(tmp_path)
    assert path.is_file()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["score"] == 88
    assert saved["security_modules"] == 0
    assert "Saved gate baseline" in out


def test_save_baseline_creates_apex_dir(tmp_path, monkeypatch):
    assert not (tmp_path / ".apex").exists()
    _patch_metrics(monkeypatch, _clean_metrics())
    rc, _ = _run(tmp_path, save_baseline=True)
    assert rc == 0
    assert (tmp_path / ".apex").is_dir()


def test_save_baseline_json_is_sorted_and_deterministic(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics(score=77))
    _run(tmp_path, save_baseline=True)
    text1 = _baseline_path(tmp_path).read_text(encoding="utf-8")
    _run(tmp_path, save_baseline=True)
    text2 = _baseline_path(tmp_path).read_text(encoding="utf-8")
    assert text1 == text2
    # sorted keys: score is alphabetically after security_modules... assert the
    # parsed keys come back sorted in the serialized form.
    keys = [line.split(":")[0].strip().strip('"')
            for line in text1.splitlines() if ":" in line]
    assert keys == sorted(keys)
    assert text1.endswith("\n")


def test_save_baseline_json_flag_shape(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics(score=80))
    rc, out = _run(tmp_path, save_baseline=True, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert data["saved"] is True
    assert data["path"].endswith("gate-baseline.json")
    assert data["metrics"]["score"] == 80


# --- --baseline with no saved file -> rc 2 -----------------------------------

def test_baseline_missing_prints_message_and_returns_nonzero(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics())
    rc, out = _run(tmp_path, baseline=True)
    assert rc == 2
    assert "no baseline saved" in out
    assert "--save-baseline" in out


def test_baseline_missing_json_carries_flag(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics())
    rc, out = _run(tmp_path, baseline=True, json_out=True)
    assert rc == 2
    data = json.loads(out)
    assert data["baseline_missing"] is True
    assert "no baseline saved" in data["error"]


# --- baseline == current -> PASSED, rc 0 -------------------------------------

def test_baseline_equal_to_current_passes(tmp_path, monkeypatch):
    metrics = _clean_metrics(score=90)
    _patch_metrics(monkeypatch, metrics)
    # snapshot then immediately compare against the same metrics
    _run(tmp_path, save_baseline=True)
    rc, out = _run(tmp_path, baseline=True)
    assert rc == 0
    assert "GATE PASSED (no regressions)" in out
    assert "REGRESSED" not in out
    # every comparison reads SAME
    assert out.count("[SAME]") >= 4


# --- score regression -> rc 1 ------------------------------------------------

def test_score_drop_is_a_regression(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics(score=90))
    _run(tmp_path, save_baseline=True)
    # now the project got worse
    _patch_metrics(monkeypatch, _clean_metrics(score=70))
    rc, out = _run(tmp_path, baseline=True)
    assert rc == 1
    assert "[REGRESSED] score" in out
    assert "90 -> 70" in out
    assert "GATE FAILED (1 regression(s))" in out


def test_score_improvement_is_not_a_regression(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics(score=70))
    _run(tmp_path, save_baseline=True)
    _patch_metrics(monkeypatch, _clean_metrics(score=95))
    rc, out = _run(tmp_path, baseline=True)
    assert rc == 0
    assert "[IMPROVED] score" in out
    assert "GATE PASSED (no regressions)" in out


# --- security / bug count regressions ----------------------------------------

def test_security_module_increase_is_a_regression(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics(security_modules=0))
    _run(tmp_path, save_baseline=True)
    _patch_metrics(monkeypatch, _clean_metrics(security_modules=2))
    rc, out = _run(tmp_path, baseline=True)
    assert rc == 1
    assert "[REGRESSED] security-modules" in out
    assert "GATE FAILED" in out


def test_bug_module_increase_is_a_regression(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics(bug_modules=1))
    _run(tmp_path, save_baseline=True)
    _patch_metrics(monkeypatch, _clean_metrics(bug_modules=3))
    rc, out = _run(tmp_path, baseline=True)
    assert rc == 1
    assert "[REGRESSED] bug-modules" in out


def test_out_of_scope_increase_beyond_epsilon_regresses(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics(out_of_scope_pct=10.0))
    _run(tmp_path, save_baseline=True)
    _patch_metrics(monkeypatch, _clean_metrics(out_of_scope_pct=25.0))
    rc, out = _run(tmp_path, baseline=True)
    assert rc == 1
    assert "[REGRESSED] out-of-scope" in out


def test_out_of_scope_tiny_drift_within_epsilon_is_same(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics(out_of_scope_pct=10.0))
    _run(tmp_path, save_baseline=True)
    _patch_metrics(monkeypatch, _clean_metrics(out_of_scope_pct=10.02))
    rc, out = _run(tmp_path, baseline=True)
    assert rc == 0
    assert "[SAME] out-of-scope" in out


# --- --tolerance -------------------------------------------------------------

def test_tolerance_absorbs_small_score_drop(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics(score=90))
    _run(tmp_path, save_baseline=True)
    _patch_metrics(monkeypatch, _clean_metrics(score=88))
    # within tolerance -> not a regression
    rc, out = _run(tmp_path, baseline=True, tolerance=5)
    assert rc == 0
    assert "GATE PASSED (no regressions)" in out


def test_tolerance_does_not_absorb_a_larger_drop(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics(score=90))
    _run(tmp_path, save_baseline=True)
    _patch_metrics(monkeypatch, _clean_metrics(score=80))
    rc, out = _run(tmp_path, baseline=True, tolerance=5)
    assert rc == 1
    assert "[REGRESSED] score" in out


# --- composition with absolute checks ----------------------------------------

def test_absolute_failure_fails_even_without_regression(tmp_path, monkeypatch):
    """A run can fail on an absolute threshold even when nothing regressed."""
    _patch_metrics(monkeypatch, _clean_metrics(score=90))
    _run(tmp_path, save_baseline=True)
    # same metrics (no regression) but an impossible absolute min-score
    rc, out = _run(tmp_path, baseline=True, min_score=200)
    assert rc == 1
    assert "[FAIL] min-score" in out
    # the regression block still says no regressions
    assert "GATE PASSED (no regressions)" in out


def test_regression_fails_even_when_absolute_checks_pass(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics(score=90))
    _run(tmp_path, save_baseline=True)
    _patch_metrics(monkeypatch, _clean_metrics(score=70))
    # absolute checks all pass (defaults), but score regressed
    rc, out = _run(tmp_path, baseline=True)
    assert rc == 1
    assert "GATE FAILED (1 regression(s))" in out


# --- --json shape ------------------------------------------------------------

def test_json_includes_baseline_block(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics(score=90))
    _run(tmp_path, save_baseline=True)
    _patch_metrics(monkeypatch, _clean_metrics(score=70))
    rc, out = _run(tmp_path, baseline=True, json_out=True)
    assert rc == 1
    data = json.loads(out)
    assert "baseline" in data
    b = data["baseline"]
    assert b["regressed"] is True
    assert b["regressions"] == 1
    assert b["tolerance"] == 0
    assert isinstance(b["comparisons"], list) and b["comparisons"]
    for c in b["comparisons"]:
        assert {"name", "status", "before", "after", "regressed", "detail"} <= set(c)
        assert isinstance(c["regressed"], bool)


def test_json_omits_baseline_block_without_flag(tmp_path, monkeypatch):
    """No --baseline -> the verdict has no baseline block (byte-identical to bare)."""
    _patch_metrics(monkeypatch, _clean_metrics(score=90))
    rc, out = _run(tmp_path, json_out=True)
    data = json.loads(out)
    assert "baseline" not in data


# --- determinism -------------------------------------------------------------

def test_baseline_comparison_deterministic(tmp_path, monkeypatch):
    _patch_metrics(monkeypatch, _clean_metrics(score=90))
    _run(tmp_path, save_baseline=True)
    _patch_metrics(monkeypatch, _clean_metrics(score=70))
    _, out1 = _run(tmp_path, baseline=True)
    _, out2 = _run(tmp_path, baseline=True)
    assert out1 == out2
    _, j1 = _run(tmp_path, baseline=True, json_out=True)
    _, j2 = _run(tmp_path, baseline=True, json_out=True)
    assert j1 == j2


# --- the no-flag / bare behavior is unchanged --------------------------------

def test_bare_gate_unaffected_by_baseline_machinery(tmp_path, monkeypatch):
    """Without --baseline / --save-baseline, output carries no regression text."""
    _patch_metrics(monkeypatch, _clean_metrics(score=90))
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "Regression vs baseline" not in out
    assert "no regressions" not in out


# --- registration of the new flags -------------------------------------------

def test_baseline_flags_registered_with_defaults():
    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    cli_reporting.register_parsers(sub)
    args = parser.parse_args(["gate"])
    assert args.save_baseline is False
    assert args.baseline is False
    assert args.tolerance == 0
