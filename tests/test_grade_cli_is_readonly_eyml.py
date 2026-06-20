"""Integrity regression: ``apex grade`` must be STRICTLY READ-ONLY.

A grade/report command is a measurement, not a development action. If grading a
project mutates that project's working tree as a side effect (e.g. an analysis
that *applies* a transform or writes a generated test instead of dry-running it),
the command becomes:

  * **untrustworthy** — "safe to let a free agent touch your project" is the
    whole moat, and a read-only command that secretly writes breaks it; and
  * **non-deterministic / non-idempotent** — a first ``grade`` and a second
    ``grade`` read DIFFERENT scores because the first one dirtied the tree (the
    observed failure: a stray generated test pushes the own-module count up and
    re-introduces a complex function, so the score DRIFTS between runs).

These tests lock the invariant three ways:

  1. Running the real CLI ``cmd_grade`` handler on a temp **git** repo leaves
     ``git status`` CLEAN — no file is created or modified.
  2. Two back-to-back runs yield the IDENTICAL score (idempotent / no drift).
  3. ``health_score.grade`` performs ZERO writes anywhere inside the project
     tree (traced at ``builtins.open`` / ``os.open``) — the durable guard that
     catches a future write even if it never reaches a git-tracked path.

The first test deliberately seeds a ``test_shield``-shaped module (the file the
original bug rewrote) so a regression that re-writes it surfaces here.
"""
from __future__ import annotations

import argparse
import builtins
import contextlib
import io
import json
import os
import subprocess
from pathlib import Path

import pytest

from app.cli_insight import cmd_grade
from app.engine.health_score import grade


# --------------------------------------------------------------------------- #
# Fixtures: a small but realistic temp project under git.                      #
# --------------------------------------------------------------------------- #

def _build_repo(root: Path) -> None:
    """A minimal, gradeable Python project with a linked test and a
    ``shield``-shaped module — modelling the file the original bug rewrote."""
    (root / "app").mkdir()
    (root / "app" / "execution").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "mod.py").write_text(
        "def add(x, y):\n    return x + y\n", encoding="utf-8")
    (root / "tests" / "test_mod.py").write_text(
        "from app.mod import add\n"
        "def test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8")
    # A module named like the one the original side effect rewrote, so a
    # regression that re-applies a shield/test-generation step into the tree
    # shows up as a dirtied file here.
    (root / "app" / "execution" / "test_shield.py").write_text(
        "def generate(name):\n"
        "    \"\"\"Stand-in for the shield generator.\"\"\"\n"
        "    return name\n",
        encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'p'\nversion = '0'\n", encoding="utf-8")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True,
    ).stdout


def _init_git_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init")


def _porcelain(root: Path) -> str:
    """``git status --porcelain`` — empty string iff the tree is clean."""
    return subprocess.run(
        ["git", "status", "--porcelain"], cwd=root,
        capture_output=True, text=True, check=True,
    ).stdout


def _grade_via_cli(root: Path) -> int:
    """Drive the real ``cmd_grade`` handler (JSON) and return its score."""
    ns = argparse.Namespace(
        target=str(root), json=True, save=False, diff=False, min_score=0)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_grade(ns)
    assert rc == 0
    return json.loads(buf.getvalue())["score"]


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    if not _has_git():
        pytest.skip("git not available")
    _build_repo(tmp_path)
    _init_git_repo(tmp_path)
    return tmp_path


def _has_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


# --------------------------------------------------------------------------- #
# 1. The CLI grade handler never dirties the working tree.                      #
# --------------------------------------------------------------------------- #

def test_cmd_grade_leaves_git_tree_clean(git_repo: Path) -> None:
    assert _porcelain(git_repo) == ""  # precondition: clean checkout
    _grade_via_cli(git_repo)
    assert _porcelain(git_repo) == "", (
        "apex grade mutated the working tree — a report command must be "
        "strictly read-only")


def test_cmd_grade_does_not_rewrite_test_shield(git_repo: Path) -> None:
    # The original bug rewrote app/execution/test_shield.py. Pin its bytes
    # across a grade so a re-introduced write is caught precisely.
    shield = git_repo / "app" / "execution" / "test_shield.py"
    before = shield.read_bytes()
    _grade_via_cli(git_repo)
    assert shield.read_bytes() == before
    # And no stray generated test was dropped anywhere.
    assert _porcelain(git_repo) == ""


# --------------------------------------------------------------------------- #
# 2. Two runs are identical: idempotent, no score drift.                        #
# --------------------------------------------------------------------------- #

def test_cmd_grade_is_idempotent_no_score_drift(git_repo: Path) -> None:
    first = _grade_via_cli(git_repo)
    after_first = _porcelain(git_repo)
    second = _grade_via_cli(git_repo)
    after_second = _porcelain(git_repo)

    assert after_first == "" and after_second == ""
    assert first == second, (
        "grade score drifted between two runs on an unchanged tree — the first "
        "run must not have mutated anything the second run reads")


# --------------------------------------------------------------------------- #
# 3. The durable guard: grade() writes nothing into the project tree at all.    #
# --------------------------------------------------------------------------- #

class _WriteTracer:
    """Records every write that targets a path inside ``root`` (ignoring
    ``.git`` bookkeeping and ``__pycache__`` bytecode, which are not project
    source).

    It hooks all the write surfaces the codebase actually uses: ``builtins.open``
    and ``io.open`` (write modes), ``os.open`` (write flags), and
    ``pathlib.Path.write_text`` / ``write_bytes``. That breadth is what makes a
    pass meaningful — a regression that writes through any of these is caught,
    even if it never reaches a git-tracked path."""

    def __init__(self, root: Path) -> None:
        self.root = os.path.abspath(str(root))
        self.writes: list[str] = []
        self._open = builtins.open
        self._ioopen = io.open
        self._osopen = os.open
        self._wtext = Path.write_text
        self._wbytes = Path.write_bytes

    def _flag(self, target: str) -> bool:
        ap = os.path.abspath(target)
        return (
            ap.startswith(self.root)
            and os.sep + ".git" + os.sep not in ap
            and "__pycache__" not in ap
        )

    @staticmethod
    def _pathish(obj) -> bool:  # noqa: ANN001
        return isinstance(obj, (str, bytes, os.PathLike))

    def __enter__(self) -> "_WriteTracer":
        tracer = self

        def make_open(real):
            def traced(file, mode="r", *a, **k):  # noqa: ANN001
                if (tracer._pathish(file) and any(c in str(mode) for c in "wax+")
                        and tracer._flag(os.fsdecode(file))):
                    tracer.writes.append(os.fsdecode(file))
                return real(file, mode, *a, **k)
            return traced

        write_flags = (
            os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC)

        def traced_osopen(path, flags, *a, **k):  # noqa: ANN001
            if (tracer._pathish(path) and (flags & write_flags)
                    and tracer._flag(os.fsdecode(path))):
                tracer.writes.append(os.fsdecode(path))
            return tracer._osopen(path, flags, *a, **k)

        def traced_wtext(self, *a, **k):  # noqa: ANN001
            if tracer._flag(str(self)):
                tracer.writes.append(str(self))
            return tracer._wtext(self, *a, **k)

        def traced_wbytes(self, *a, **k):  # noqa: ANN001
            if tracer._flag(str(self)):
                tracer.writes.append(str(self))
            return tracer._wbytes(self, *a, **k)

        builtins.open = make_open(self._open)
        io.open = make_open(self._ioopen)
        os.open = traced_osopen
        Path.write_text = traced_wtext
        Path.write_bytes = traced_wbytes
        return self

    def __exit__(self, *exc) -> None:
        builtins.open = self._open
        io.open = self._ioopen
        os.open = self._osopen
        Path.write_text = self._wtext
        Path.write_bytes = self._wbytes


def test_grade_performs_no_writes_into_project_tree(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    with _WriteTracer(tmp_path) as tracer:
        result = grade(str(tmp_path))
    assert result.score >= 0
    assert tracer.writes == [], (
        "health_score.grade wrote into the project tree: "
        f"{tracer.writes!r} — grading must be a pure measurement")


def test_write_tracer_catches_a_deliberate_write(tmp_path: Path) -> None:
    # Guard against a vacuous tracer: a real write MUST be recorded.
    with _WriteTracer(tmp_path) as tracer:
        (tmp_path / "scratch.txt").write_text("x", encoding="utf-8")
    assert any(w.endswith("scratch.txt") for w in tracer.writes)
