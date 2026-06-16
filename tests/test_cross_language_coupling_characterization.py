"""Characterization: refactored ``cross_language_coupling`` is byte-identical to the
pre-refactor original across a representative temp git tree and many input knobs.

The original module body is loaded from the git HEAD snapshot stashed in /tmp by the
refactor harness (falling back to ``git show`` here so the test is self-contained),
imported under a throwaway module name, and run side-by-side with the current code.
Outputs (CrossLink lists, in order, field-for-field) and rendered markdown must match
exactly for every input. Determinism is checked by repeating each call.
"""

from __future__ import annotations

import subprocess
import sys
import types
from dataclasses import astuple
from pathlib import Path

import pytest

from app.engine import cross_language_coupling as current


def _load_original() -> types.ModuleType:
    repo_root = Path(__file__).resolve().parent.parent
    rel = "app/engine/cross_language_coupling.py"
    src = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=repo_root, capture_output=True, text=True,
    ).stdout
    name = "_orig_cross_language_coupling"
    mod = types.ModuleType(name)
    mod.__file__ = str(repo_root / rel)
    sys.modules[name] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


def _git(repo: Path, *args: str) -> None:
    env_setup = [
        ("user.email", "a@b.c"),
        ("user.name", "Tester"),
        ("commit.gpgsign", "false"),
    ]
    if not (repo / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        for k, v in env_setup:
            subprocess.run(["git", "config", k, v], cwd=repo, check=True)
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


def _commit(repo: Path, files: dict[str, str]) -> None:
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c")


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    r = tmp_path_factory.mktemp("clc_char_repo")
    # Strong cross-boundary signal: api.py <-> client.js move together repeatedly.
    for i in range(5):
        _commit(r, {"app/api.py": f"x={i}\n", "web/client.js": f"y={i}\n"})
    # Same-language pairs that must never be emitted.
    for i in range(4):
        _commit(r, {"app/api.py": f"a={i}\n", "app/util.py": f"b={i}\n"})
    # A second cross pair with a smaller count.
    for i in range(3):
        _commit(r, {"app/render.py": f"r={i}\n", "web/style.css": f"s={i}\n"})
    # Mega-commit (should be ignored) — many files at once.
    big = {f"pkg/m{i}.py": f"{i}\n" for i in range(30)}
    big.update({f"front/f{i}.ts": f"{i}\n" for i in range(30)})
    _commit(r, big)
    # Single-file commits (never form a pair).
    _commit(r, {"README.md": "docs\n"})
    # Skipped-dir copy that must not leak in.
    _commit(r, {"node_modules/lib.js": "n\n", "app/api.py": "z\n"})
    return r


_INPUTS = [
    {"min_cochanges": 3, "limit": 5},
    {"min_cochanges": 1, "limit": 5},
    {"min_cochanges": 2, "limit": 2},
    {"min_cochanges": 5, "limit": 5},
    {"min_cochanges": 4, "limit": 1},
    {"min_cochanges": 100, "limit": 5},
    {"min_cochanges": 0, "limit": 5},
    {"min_cochanges": 3, "limit": 0},
    {"min_cochanges": -1, "limit": -1},
]


@pytest.mark.parametrize("kw", _INPUTS)
def test_byte_identical_links(repo: Path, kw: dict[str, int]) -> None:
    orig = _load_original()
    a = current.cross_language_coupling(str(repo), **kw)
    b = orig.cross_language_coupling(str(repo), **kw)
    assert [astuple(x) for x in a] == [astuple(x) for x in b]
    # Determinism: repeat yields the same.
    a2 = current.cross_language_coupling(str(repo), **kw)
    assert [astuple(x) for x in a] == [astuple(x) for x in a2]
    # Rendered markdown identical too.
    assert current.render_cross_language_markdown(a) == \
        orig.render_cross_language_markdown(b)


def test_byte_identical_nonexistent(repo: Path) -> None:
    orig = _load_original()
    missing = str(repo / "nope")
    assert current.cross_language_coupling(missing) == \
        orig.cross_language_coupling(missing)


def test_byte_identical_non_git(tmp_path: Path) -> None:
    orig = _load_original()
    a = current.cross_language_coupling(str(tmp_path))
    b = orig.cross_language_coupling(str(tmp_path))
    assert a == b == []
