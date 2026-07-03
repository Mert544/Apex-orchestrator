"""Shared git plumbing for the wave tooling (gate_runner / preflight / session_pulse).

These three scripts all speak to the SAME repository through the same handful of
read-mostly git calls. Keeping the calls here — one writer, three importers —
means the porcelain parsing (rename arrows, quoted paths, untracked files) is
fixed in exactly one place, and a fourth tool can join the family without
re-implementing it. Stdlib-only, deterministic: every function is a pure
function of the repository state it reads (no clock, no randomness).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verify  # same-dir sibling: the canonical chunk-partition + ROOT owner

ROOT = verify.ROOT


def git_out(*args: str, check: bool = True) -> str:
    """Run ``git <args>`` in ROOT and return stripped stdout ('' on failure
    when ``check=False``; raises on failure when ``check=True``)."""
    proc = subprocess.run(["git", *args], cwd=str(ROOT),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        if check:
            raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return ""
    return proc.stdout.strip()


def git_ok(*args: str) -> bool:
    """Run ``git <args>`` in ROOT, streaming its output; True iff exit 0."""
    return subprocess.run(["git", *args], cwd=str(ROOT)).returncode == 0


def current_branch() -> str:
    """The current branch name ('HEAD' when detached, '' when not a repo)."""
    return git_out("rev-parse", "--abbrev-ref", "HEAD", check=False)


def dirty_paths(*pathspecs: str) -> set[str]:
    """Working-tree paths that differ from HEAD (modified, staged, untracked —
    untracked expanded to individual files), optionally limited to pathspecs.

    Rename lines (``R  old -> new``) contribute BOTH sides: the old path's
    content is gone and the new path's content is unvetted, so a content key
    must treat each as changed."""
    args = ["status", "--porcelain", "--untracked-files=all"]
    if pathspecs:
        args += ["--", *pathspecs]
    paths: set[str] = set()
    for line in git_out(*args, check=False).splitlines():
        for part in line[3:].split(" -> "):
            part = part.strip().strip('"')
            if part:
                paths.add(part)
    return paths


def working_blob_hash(rel: str) -> str:
    """The git blob hash of the WORKING-TREE file at ``rel`` (no object is
    written — ``hash-object`` without ``-w`` only computes). 'absent' when the
    file does not exist, so a deletion still changes the content key."""
    if not (ROOT / rel).is_file():
        return "absent"
    return git_out("hash-object", "--", rel)


def head_hash(spec: str) -> str:
    """``git rev-parse <spec>`` — e.g. ``HEAD:app`` for a tree hash, or
    ``HEAD:tests/conftest.py`` for a blob hash. '' when the path is absent."""
    return git_out("rev-parse", spec, check=False)
