"""The `apex scope` subcommand: Apex's HONEST report of how much of the repo it
analyses (Python) and which biggest non-Python files it leaves out of scope —
the "what do you cover, and what don't you?" trust differentiator.

Grounded in ``ProjectProfiler.profile()`` (the scope-accounting fields) and
``scan_polyglot_facts`` (the biggest non-Python files). Deterministic, stdlib-
only, LLM-free. The fixtures build a real (small) profile over a tmp repo and
assert the rendered report plus its --json mirror.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

from app.cli_insight import cmd_scope


def _run(target: Path, json_out: bool = False) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_scope(argparse.Namespace(target=str(target), json=json_out))
    return rc, buf.getvalue()


def _write(root: Path, rel: str, body: str = "x = 1\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _polyglot_repo(root: Path) -> None:
    """A mix of Python (the analysed subset) and JS/HTML/CSS (out of scope)."""
    _write(root, "app/core.py", "def f():\n    return 1\n")
    _write(root, "app/util.py", "VALUE = 2\n")
    _write(root, "tests/test_core.py", "def test_f():\n    assert True\n")
    _write(root, "web/app.js", "function go() { return 1; }\n" * 20)
    _write(root, "web/extra.js", "const x = 1;\n" * 5)
    _write(root, "web/index.html", "<html><body>hi</body></html>\n" * 10)
    _write(root, "web/style.css", "body { color: red; }\n" * 3)


def _all_python_repo(root: Path) -> None:
    _write(root, "app/core.py", "def f():\n    return 1\n")
    _write(root, "app/util.py", "VALUE = 2\n")
    _write(root, "tests/test_core.py", "def test_f():\n    assert True\n")


# --- polyglot repo: the honest boundary -------------------------------------

def test_polyglot_headline_shows_ratios(tmp_path):
    _polyglot_repo(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "Apex analyses" in out
    assert "% of this repo (Python)" in out
    assert "outside its analysis scope" in out
    # The numbers must be a real partition, not 100%.
    assert "100%" not in out


def test_polyglot_breakdown_lists_languages(tmp_path):
    _polyglot_repo(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "Outside analysis scope" in out
    assert "JavaScript" in out
    assert "HTML" in out
    assert "CSS" in out


def test_polyglot_names_out_of_scope_files(tmp_path):
    _polyglot_repo(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "Largest / most-active out-of-scope files" in out
    assert "web/app.js" in out
    # Untested non-Python files are flagged honestly.
    assert "no test found" in out


def test_polyglot_json_is_valid_and_grounded(tmp_path):
    _polyglot_repo(tmp_path)
    rc, out = _run(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert data["all_python"] is False
    assert data["python_file_count"] >= 2
    assert data["analyzed_pct"] + data["out_of_scope_pct"] in (99, 100, 101)
    langs = {row["language"] for row in data["language_breakdown"]}
    assert {"JavaScript", "HTML", "CSS"} <= langs
    paths = {f["path"] for f in data["files"]}
    assert "web/app.js" in paths
    for f in data["files"]:
        assert set(f) == {"path", "language", "loc", "churn", "has_test"}


def test_breakdown_sorted_count_desc_then_name(tmp_path):
    _polyglot_repo(tmp_path)
    _, out = _run(tmp_path, json_out=True)
    data = json.loads(out)
    rows = data["language_breakdown"]
    ordering = [(-r["files"], r["language"]) for r in rows]
    assert ordering == sorted(ordering)


# --- all-Python repo: the reassurance path ----------------------------------

def test_all_python_reports_full_coverage(tmp_path):
    _all_python_repo(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "Apex analyses 100% of this repo (all Python)." in out
    assert "outside its analysis scope" not in out


def test_all_python_json(tmp_path):
    _all_python_repo(tmp_path)
    rc, out = _run(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert data["all_python"] is True
    assert data["analyzed_pct"] == 100
    assert data["out_of_scope_pct"] == 0
    assert data["language_breakdown"] == []
    assert data["files"] == []


# --- empty repo: read defensively, never crash ------------------------------

def test_empty_repo_does_not_crash(tmp_path):
    rc, out = _run(tmp_path)
    assert rc == 0
    # No source at all → still the honest "all" framing, never a divide-by-zero.
    assert "100%" in out


def test_empty_repo_json(tmp_path):
    rc, out = _run(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert data["all_python"] is True
    assert data["source_file_count"] == 0
    assert data["files"] == []


# --- determinism, exit code, registration -----------------------------------

def test_deterministic_byte_for_byte(tmp_path):
    _polyglot_repo(tmp_path)
    _, out1 = _run(tmp_path)
    _, out2 = _run(tmp_path)
    assert out1 == out2
    _, j1 = _run(tmp_path, json_out=True)
    _, j2 = _run(tmp_path, json_out=True)
    assert j1 == j2


def test_returns_zero_on_all_paths(tmp_path):
    assert _run(tmp_path)[0] == 0
    assert _run(tmp_path, json_out=True)[0] == 0
    _all_python_repo(tmp_path)
    assert _run(tmp_path)[0] == 0
    _polyglot_repo(tmp_path)
    assert _run(tmp_path)[0] == 0
    assert _run(tmp_path, json_out=True)[0] == 0


def test_registered_via_parser():
    import app.cli_insight as cli_insight

    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    cli_insight.register_parsers(sub)
    assert "scope" in sub.choices
    assert sub.choices["scope"].get_default("func") is cmd_scope
