"""Characterization tests for the ``analyze_function_length`` refactor.

These pin the *full* observable output of the refactored
:func:`analyze_function_length` against the pristine pre-refactor implementation
loaded straight from ``git show HEAD:...``. The original is executed in an
isolated module so both versions run over the identical representative temp
trees and every field (histogram order + contents, longest order + contents,
scalars) is compared byte-for-byte. Zero mismatches is the contract.

Stdlib-only, offline, deterministic.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.tools.function_length import FunctionLength, analyze_function_length

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_REL = "app/tools/function_length.py"


def _load_original() -> types.ModuleType:
    """Import the HEAD (pre-refactor) version of the module under a unique name.

    The pristine source is fetched via ``git show`` so the comparison is against
    the committed baseline, not the working tree, and is materialized to a temp
    file that imports cleanly using the live ``app.*`` dependencies.
    """
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{TARGET_REL}"],
        cwd=REPO_ROOT,
        text=True,
    )
    tmp = Path(__file__).parent / "_function_length_original_baseline.py"
    tmp.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "_function_length_original_baseline", tmp
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def original():
    mod = _load_original()
    yield mod
    tmp = Path(__file__).parent / "_function_length_original_baseline.py"
    tmp.unlink(missing_ok=True)
    sys.modules.pop("_function_length_original_baseline", None)


def _write(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _as_tuple(r: FunctionLength) -> tuple:
    """Order-sensitive, fully-materialized snapshot of every result field."""
    return (
        tuple(r.histogram.items()),
        r.over_threshold,
        r.threshold,
        r.total_functions,
        r.mean,
        r.median,
        r.max,
        tuple(tuple(sorted(e.items())) for e in r.longest),
        # also pin raw longest ordering (sorted() above would hide order)
        tuple(tuple(e.items()) for e in r.longest),
    )


# Representative trees exercising every branch the refactor reorganized.
_TREES: dict[str, dict[str, str]] = {
    "empty": {},
    "single_short": {
        "app/m.py": "def f():\n    return 1\n",
    },
    "docstring_and_blank": {
        "app/a.py": (
            "def f():\n"
            '    """doc\n'
            '    spanning\n'
            '    lines"""\n'
            "\n"
            "    # comment\n"
            "    x = 1\n"
            "    return x\n"
        ),
        "app/b.py": "def only_doc():\n    \"\"\"just a doc\"\"\"\n",
    },
    "methods_and_nesting": {
        "app/pkg/c.py": (
            "class K:\n"
            "    def method(self):\n"
            "        a = 1\n"
            "        b = 2\n"
            "        return a + b\n"
            "    async def amethod(self):\n"
            "        return 0\n"
            "    class Inner:\n"
            "        def deep(self):\n"
            "            return 9\n"
        ),
        "app/pkg/d.py": (
            "def outer():\n"
            "    def inner():\n"
            "        return 1\n"
            "    return inner\n"
        ),
    },
    "fixtures_excluded": {
        "app/keep.py": "def keep():\n    return 1\n",
        "tests/test_x.py": "def test_thing():\n    assert True\n",
        "examples/ex.py": "def example():\n    return 2\n",
        "fixtures/f.py": "def fixture():\n    return 3\n",
    },
    "unparsable_skipped": {
        "app/good.py": "def good():\n    return 1\n",
        "app/broken.py": "def broken(:\n    this is not python\n",
    },
    "many_for_longest_cap": {
        f"app/mod{i:02d}.py": (
            f"def fn{i:02d}():\n"
            + "".join(f"    x{j} = {j}\n" for j in range(i + 1))
            + "    return 0\n"
        )
        for i in range(30)
    },
    "ties_for_sort_order": {
        "app/zeta.py": "def b():\n    a = 1\n    return a\n",
        "app/alpha.py": "def a():\n    a = 1\n    return a\n",
        "app/alpha2.py": "def a():\n    a = 1\n    return a\n",
    },
}


@pytest.mark.parametrize("tree_name", sorted(_TREES))
@pytest.mark.parametrize("threshold", [1, 3, 50])
@pytest.mark.parametrize("max_files", [0, 2, 500])
def test_byte_identical_to_baseline(
    original, tmp_path, tree_name, threshold, max_files
):
    root = tmp_path / tree_name
    for rel, src in _TREES[tree_name].items():
        _write(root / rel, src)

    new = analyze_function_length(root, max_files=max_files, threshold=threshold)
    old = original.analyze_function_length(
        root, max_files=max_files, threshold=threshold
    )

    assert _as_tuple(new) == _as_tuple(old)
    # dataclasses.asdict gives a second, independent equality witness.
    assert dataclasses.asdict(new) == dataclasses.asdict(old)


def test_nonexistent_root_matches_baseline(original, tmp_path):
    missing = tmp_path / "does_not_exist"
    new = analyze_function_length(missing, threshold=7)
    old = original.analyze_function_length(missing, threshold=7)
    assert dataclasses.asdict(new) == dataclasses.asdict(old)
    assert new.threshold == 7
