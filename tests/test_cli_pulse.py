"""The `apex pulse` subcommand: the cell's instant-value face — a one-screen
grounded "vital signs" snapshot of the project Apex sits in (grade, honest
scope, the top grounded next-moves, and the measured track record).

Deterministic, stdlib-only, LLM-free. The fixtures build a real (small) project
over a tmp tree and assert the rendered snapshot plus its --json mirror. The
idea engine is bounded by pulse to a small budget, so these stay fast.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

from app.cli_reporting import cmd_pulse


def _run(target: Path, json_out: bool = False) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_pulse(argparse.Namespace(target=str(target), json=json_out))
    return rc, buf.getvalue()


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _python_repo(root: Path) -> None:
    """A small all-Python project with enough structure to grade and to seed
    a couple of ideas."""
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


def _polyglot_repo(root: Path) -> None:
    """Python plus out-of-scope JS/HTML so the scope line reports a real split."""
    _python_repo(root)
    _write(root, "web/app.js", "function go() { return 1; }\n" * 30)
    _write(root, "web/index.html", "<html><body>hi</body></html>\n" * 15)


def _seed_memory(root: Path) -> None:
    """Plant an idea-memory file so the track-record line has measured rates."""
    payload = {
        "by_operator": {
            "sort_imports": {"applied": 50, "rolled_back": 0, "blocked": 0},
            "harden": {"applied": 0, "rolled_back": 2, "blocked": 1},
        },
        "by_label": {},
        "by_sequence": {},
    }
    _write(root, ".apex/idea-memory.json", json.dumps(payload))


# --- core render: grade + scope + exit code ---------------------------------

def test_pulse_prints_grade_scope_and_returns_zero(tmp_path):
    _python_repo(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "Apex pulse" in out
    assert "Grade:" in out
    assert "Scope: analysing" in out
    assert "Next moves:" in out
    assert "Track record:" in out


def test_pulse_all_python_scope_line(tmp_path):
    _python_repo(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "Scope: analysing 100% (all Python)" in out


def test_pulse_polyglot_scope_line_names_out_of_scope(tmp_path):
    _polyglot_repo(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "out of scope" in out
    assert "100% (all Python)" not in out
    # The biggest out-of-scope file is named.
    assert "web/app.js" in out


# --- JSON mirror -------------------------------------------------------------

def test_pulse_json_is_valid_with_expected_keys(tmp_path):
    _python_repo(tmp_path)
    rc, out = _run(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert set(data) == {"project_root", "grade", "scope", "moves", "trackrecord"}
    assert set(data["grade"]) >= {"letter", "score"}
    assert set(data["scope"]) >= {"all_python", "analyzed_pct", "out_of_scope_pct", "files"}
    assert isinstance(data["moves"], list)
    assert set(data["trackrecord"]) == {"by_type", "has_record"}


def test_pulse_json_moves_carry_title_and_focus_fields(tmp_path):
    _python_repo(tmp_path)
    _, out = _run(tmp_path, json_out=True)
    data = json.loads(out)
    for m in data["moves"]:
        assert set(m) == {"title", "branch_path", "value", "focus"}
        assert isinstance(m["title"], str) and m["title"]


# --- track record: fresh repo vs seeded memory ------------------------------

def test_fresh_repo_has_no_track_record(tmp_path):
    _python_repo(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "Track record: no track record yet" in out
    _, jout = _run(tmp_path, json_out=True)
    data = json.loads(jout)
    assert data["trackrecord"]["has_record"] is False
    assert data["trackrecord"]["by_type"] == []


def test_seeded_memory_renders_landing_rates(tmp_path):
    _python_repo(tmp_path)
    _seed_memory(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 0
    # Reliable first (100%), then risky (0%), with sample counts.
    assert "sort_imports 100% (50)" in out
    assert "harden 0% (3)" in out
    assert "no track record yet" not in out
    _, jout = _run(tmp_path, json_out=True)
    data = json.loads(jout)
    assert data["trackrecord"]["has_record"] is True
    keys = [r["key"] for r in data["trackrecord"]["by_type"]]
    assert keys == ["sort_imports", "harden"]


# --- defensive / empty paths -------------------------------------------------

def test_empty_repo_does_not_crash(tmp_path):
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "Apex pulse" in out
    assert "Track record: no track record yet" in out


def test_empty_repo_json(tmp_path):
    rc, out = _run(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert data["scope"]["all_python"] is True
    assert data["moves"] == [] or isinstance(data["moves"], list)
    assert data["trackrecord"]["has_record"] is False


# --- determinism -------------------------------------------------------------

def test_deterministic_byte_for_byte(tmp_path):
    _polyglot_repo(tmp_path)
    _seed_memory(tmp_path)
    _, out1 = _run(tmp_path)
    _, out2 = _run(tmp_path)
    assert out1 == out2
    _, j1 = _run(tmp_path, json_out=True)
    _, j2 = _run(tmp_path, json_out=True)
    assert j1 == j2


def test_returns_zero_on_all_paths(tmp_path):
    assert _run(tmp_path)[0] == 0
    assert _run(tmp_path, json_out=True)[0] == 0
    _python_repo(tmp_path)
    assert _run(tmp_path)[0] == 0
    _polyglot_repo(tmp_path)
    assert _run(tmp_path, json_out=True)[0] == 0


# --- registration ------------------------------------------------------------

def test_registered_via_parser():
    import app.cli_reporting as cli_reporting

    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    cli_reporting.register_parsers(sub)
    assert "pulse" in sub.choices
    assert sub.choices["pulse"].get_default("func") is cmd_pulse
