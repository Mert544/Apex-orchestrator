"""Falsifiable tests for the scoped gate's interpreter/path parity — the fix
for the 2026-07-08 audit's finding: the impact-scoped per-move gate ran under
``sys.executable`` (Apex's OWN Python) while the baseline capture, the
full-suite gate, and the pytest-missing probe all use the TARGET project's
``.venv`` when present. On an external project whose deps live only in its
venv, the scoped run's tests would SKIP (``pytest.importorskip``) — a fake
green — or collection-error — a false red that vetoes every landing. The
PYTHONPATH had the same asymmetry: the full-suite runner serves a genuine
separated ``src``/``lib`` flat-module dir (``_import_roots``); the scoped run
put only the root on the path, so that whole layout class was un-landable.

Both tests here failed on the pre-fix code (venv shim never invoked; the
src-layout landing rolled back on a collection error).
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, apply_rename


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _edit_plan(rel: str, original: str, new: str) -> RenamePlan:
    plan = RenamePlan(old=rel, new="edit")
    plan.originals[rel] = original
    plan.new_contents[rel] = new
    plan.edits_by_file[rel] = 1
    return plan


def test_scoped_gate_runs_the_targets_venv_interpreter(tmp_path):
    # A recording shim stands in for the target's .venv python: it writes a
    # marker, then execs the real interpreter (so the tests genuinely run).
    # The scoped gate must invoke IT — not Apex's own sys.executable.
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/core.py", "def f():\n    return 1\n")
    _write(tmp_path, "tests/test_core.py",
           "from app.core import f\n\n\ndef test_f():\n    assert f() == 1\n")
    _write(tmp_path, "pyproject.toml", "[project]\nname='demo'\nversion='0'\n")
    marker = tmp_path / ".venv" / "invoked.txt"
    shim = tmp_path / ".venv" / "bin" / "python"
    shim.parent.mkdir(parents=True)
    shim.write_text(
        f"#!/bin/sh\necho used > {marker}\nexec {sys.executable} \"$@\"\n",
        encoding="utf-8")
    shim.chmod(0o755)

    before = (tmp_path / "app" / "core.py").read_text(encoding="utf-8")
    plan = _edit_plan("app/core.py", before,
                      "def f():\n    return 1  # tidy\n")
    res = apply_rename(tmp_path, plan, verify=True, impact_scope=True)

    assert res["applied"] is True and res["verified"] is True
    assert res["test_evidence"]["scoped"] is True
    assert marker.exists(), "the scoped run must use the target's .venv python"


def test_scoped_gate_resolves_separated_src_modules(tmp_path):
    # Flat module under src/ (``src/util.py`` + ``import util`` in the test):
    # the full-suite runner serves this via _import_roots; the scoped gate used
    # to put only the root on PYTHONPATH, so collection errored and the correct
    # move was rolled back as a false red.
    _write(tmp_path, "src/util.py", "def add(a, b):\n    return a + b\n")
    _write(tmp_path, "tests/test_util.py",
           "import util\n\n\ndef test_add():\n    assert util.add(1, 2) == 3\n")
    _write(tmp_path, "pyproject.toml", "[project]\nname='demo'\nversion='0'\n")

    before = (tmp_path / "src" / "util.py").read_text(encoding="utf-8")
    plan = _edit_plan("src/util.py", before,
                      "def add(a, b):\n    return a + b  # tidy\n")
    res = apply_rename(tmp_path, plan, verify=True, impact_scope=True)

    assert res["applied"] is True and res["verified"] is True
    assert res["test_evidence"]["scoped"] is True
    assert res["test_evidence"]["tests"] == ["tests/test_util.py"]
    assert "# tidy" in (tmp_path / "src" / "util.py").read_text(encoding="utf-8")
