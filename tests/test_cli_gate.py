"""The `apex gate` subcommand: a zero-config, deterministic CI quality gate.

`apex gate` is the zero-config complement to `apex outcomes` — instead of a
user-written rubric it gates on Apex's OWN deterministic metrics (the health
grade + ProjectProfile) with sensible defaults. The CI contract under test:

  * a clean tmp repo passes with bare defaults (rc 0, "GATE PASSED");
  * an impossible / dirtied threshold fails (rc 1, "GATE FAILED");
  * `--json` mirrors the verdict with a `passed` bool + per-check entries;
  * the verdict is deterministic (same repo in -> same bytes out);
  * the defaults never spuriously fail a clean repo.

Deterministic, stdlib-only, LLM-free — these tests build a real (small) project
over a tmp tree, and monkeypatch the profiler when a failing metric must be
forced deterministically (no need to author a vulnerable fixture on disk).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

import app.cli_reporting as cli_reporting
from app.cli_reporting import cmd_gate

# Defaults mirror the parser: max-security/max-bugs ON at 0, min-score &
# out-of-scope OFF — so a bare gate is a conservative "no findings, no bugs".
_DEFAULTS = dict(min_score=0, max_security=0, max_bugs=0, max_out_of_scope=-1)


def _ns(target: Path, *, json_out: bool = False, **overrides) -> argparse.Namespace:
    kwargs = {**_DEFAULTS, **overrides}
    return argparse.Namespace(target=str(target), json=json_out, **kwargs)


def _run(target: Path, *, json_out: bool = False, **overrides) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_gate(_ns(target, json_out=json_out, **overrides))
    return rc, buf.getvalue()


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _clean_repo(root: Path) -> None:
    """A small, well-behaved all-Python project: no security findings, no
    correctness bugs — a clean repo a bare gate must pass."""
    _write(root, "app/core.py",
           "def compute(items):\n"
           "    total = 0\n"
           "    for it in items:\n"
           "        total += it\n"
           "    return total\n")
    _write(root, "app/util.py", "from app.core import compute\n\nVALUE = compute([1, 2, 3])\n")
    _write(root, "tests/test_core.py",
           "from app.core import compute\n\n"
           "def test_compute():\n    assert compute([1, 2]) == 3\n")


class _FakeProfile:
    """A stand-in ProjectProfile carrying exactly the fields the gate reads."""

    def __init__(self, *, security=(), bugs=(), out_of_scope_ratio=0.0):
        self.security_finding_modules = list(security)
        self.correctness_bug_modules = list(bugs)
        self.out_of_scope_ratio = out_of_scope_ratio


def _patch_profile(monkeypatch, profile: _FakeProfile) -> None:
    """Force `_gate_metrics`' profiler to return ``profile`` deterministically."""
    import app.tools.project_profile as pp

    class _FakeProfiler:
        def __init__(self, root):
            self._root = root

        def profile(self, *, light=False):
            return profile

    monkeypatch.setattr(pp, "ProjectProfiler", _FakeProfiler)


# --- clean repo passes with bare defaults -----------------------------------

def test_clean_repo_passes_with_defaults(tmp_path):
    _clean_repo(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "GATE PASSED" in out
    assert "GATE FAILED" not in out
    # The two conservative defaults are reported.
    assert "max-security" in out
    assert "max-bugs" in out


def test_empty_repo_does_not_crash_and_passes(tmp_path):
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "# Apex gate" in out
    assert "GATE PASSED" in out


def test_bare_defaults_skip_optional_checks(tmp_path):
    """min-score (0=off) and out-of-scope (off) are absent from a bare gate, so
    they can never spuriously fail a clean repo."""
    _clean_repo(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "min-score" not in out
    assert "out-of-scope" not in out


# --- failing thresholds -> rc 1, GATE FAILED ---------------------------------

def test_impossible_min_score_fails(tmp_path):
    _clean_repo(tmp_path)
    rc, out = _run(tmp_path, min_score=200)
    assert rc == 1
    assert "GATE FAILED" in out
    assert "[FAIL] min-score" in out


def test_security_finding_fails_with_max_security_zero(tmp_path, monkeypatch):
    _clean_repo(tmp_path)
    _patch_profile(monkeypatch, _FakeProfile(security=["app/danger.py"]))
    rc, out = _run(tmp_path)  # max-security defaults to 0
    assert rc == 1
    assert "GATE FAILED" in out
    assert "[FAIL] max-security" in out


def test_correctness_bug_fails_with_max_bugs_zero(tmp_path, monkeypatch):
    _clean_repo(tmp_path)
    _patch_profile(monkeypatch, _FakeProfile(bugs=["app/buggy.py"]))
    rc, out = _run(tmp_path)
    assert rc == 1
    assert "[FAIL] max-bugs" in out


def test_out_of_scope_fails_when_enabled(tmp_path, monkeypatch):
    _clean_repo(tmp_path)
    _patch_profile(monkeypatch, _FakeProfile(out_of_scope_ratio=0.6))
    rc, out = _run(tmp_path, max_out_of_scope=10.0)
    assert rc == 1
    assert "[FAIL] max-out-of-scope" in out
    assert "60.0% out of scope" in out


def test_security_finding_tolerated_when_threshold_raised(tmp_path, monkeypatch):
    _clean_repo(tmp_path)
    _patch_profile(monkeypatch, _FakeProfile(security=["app/danger.py"]))
    rc, out = _run(tmp_path, max_security=1)
    assert rc == 0
    assert "GATE PASSED" in out
    assert "[PASS] max-security" in out


# --- JSON mirror -------------------------------------------------------------

def test_json_has_passed_bool_and_per_check_entries(tmp_path):
    _clean_repo(tmp_path)
    rc, out = _run(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert data["passed"] is True
    assert isinstance(data["checks"], list) and data["checks"]
    for c in data["checks"]:
        assert {"name", "passed", "actual", "threshold", "detail"} <= set(c)
        assert isinstance(c["passed"], bool)
    assert "metrics" in data


def test_json_failing_gate_reports_passed_false(tmp_path):
    _clean_repo(tmp_path)
    rc, out = _run(tmp_path, json_out=True, min_score=200)
    assert rc == 1
    data = json.loads(out)
    assert data["passed"] is False
    names = {c["name"] for c in data["checks"]}
    assert "min-score" in names


# --- determinism -------------------------------------------------------------

def test_deterministic_byte_for_byte(tmp_path):
    _clean_repo(tmp_path)
    _, out1 = _run(tmp_path)
    _, out2 = _run(tmp_path)
    assert out1 == out2
    _, j1 = _run(tmp_path, json_out=True)
    _, j2 = _run(tmp_path, json_out=True)
    assert j1 == j2


def test_exit_code_is_returned_not_just_printed(tmp_path):
    _clean_repo(tmp_path)
    assert _run(tmp_path)[0] == 0
    assert _run(tmp_path, min_score=200)[0] == 1


# --- defensive: unreadable metrics never crash ------------------------------

def test_profiler_failure_degrades_without_crashing(tmp_path, monkeypatch):
    import app.tools.project_profile as pp

    class _BoomProfiler:
        def __init__(self, root):
            pass

        def profile(self, *, light=False):
            raise RuntimeError("boom")

    monkeypatch.setattr(pp, "ProjectProfiler", _BoomProfiler)
    rc, out = _run(tmp_path)
    # security/bugs collapse to 0 -> conservative defaults still pass.
    assert rc == 0
    assert "GATE PASSED" in out


# --- registration ------------------------------------------------------------

def test_registered_via_parser():
    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    cli_reporting.register_parsers(sub)
    assert "gate" in sub.choices
    assert sub.choices["gate"].get_default("func") is cmd_gate


def test_parser_defaults_match_bare_gate():
    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    cli_reporting.register_parsers(sub)
    args = parser.parse_args(["gate"])
    assert args.min_score == 0
    assert args.max_security == 0
    assert args.max_bugs == 0
    assert args.max_out_of_scope == -1
