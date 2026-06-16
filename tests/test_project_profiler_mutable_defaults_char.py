"""Characterization harness for the ``_scan_mutable_defaults`` refactor.

Proves the decomposed implementation (small pure helpers ``_is_mutable_default``
/ ``_func_has_mutable_default`` / ``_tree_has_mutable_default`` feeding
``_scan_mutable_defaults``) is byte-identical to the pre-refactor original,
snapshotted from ``HEAD:app/tools/project_profile.py`` at refactor time.

For every representative temp tree the two implementations must return the same
``list[str]`` of module paths — same order (sorted) and same contents. The
original method is recovered by exec'ing the HEAD snapshot under a throwaway
module name and binding its unbound ``_scan_mutable_defaults`` onto the real
``ProjectProfiler`` instance, so both see identical inputs and only the scan
logic differs. Offline, stdlib + pytest only.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.tools.project_profile import ProjectProfiler

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_REL = "app/tools/project_profile.py"


def _load_original_scan():
    """Return the HEAD-snapshot ``_scan_mutable_defaults`` (unbound function)."""
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{TARGET_REL}"], cwd=str(REPO_ROOT)
    ).decode("utf-8")
    mod = types.ModuleType("_orig_project_profile")
    spec = importlib.util.spec_from_loader(mod.__name__, loader=None)
    mod.__spec__ = spec
    sys.modules[mod.__name__] = mod
    exec(compile(src, "<orig_project_profile>", "exec"), mod.__dict__)
    return mod.ProjectProfiler._scan_mutable_defaults


_original_scan = _load_original_scan()


def _modules_for(root: Path) -> list:
    """All ``*.py`` files under ``root`` as objects with a ``.path`` attribute,
    in a deterministic order (so any divergence is the scan's, not the input)."""
    rels = sorted(
        str(p.relative_to(root)) for p in root.rglob("*.py")
    )
    return [types.SimpleNamespace(path=rel) for rel in rels]


def _run_both(root: Path):
    prof = ProjectProfiler(str(root))
    modules = _modules_for(root)
    new = prof._scan_mutable_defaults(modules)
    old = _original_scan(prof, modules)
    return old, new


# --- representative inputs -------------------------------------------------

def _tree_literals(root: Path) -> None:
    (root / "pkg").mkdir()
    (root / "pkg" / "list_lit.py").write_text("def f(x=[]):\n    return x\n")
    (root / "pkg" / "dict_lit.py").write_text("def f(x={}):\n    return x\n")
    (root / "pkg" / "set_lit.py").write_text("def f(x={1, 2}):\n    return x\n")
    (root / "pkg" / "clean.py").write_text(
        "def f(x=0, y='s', z=(1, 2), w=None):\n    return x\n"
    )


def _tree_builtin_calls(root: Path) -> None:
    (root / "pkg").mkdir()
    # bare list()/dict()/set() are mutable defaults
    (root / "pkg" / "list_call.py").write_text("def f(x=list()):\n    return x\n")
    (root / "pkg" / "dict_call.py").write_text("def f(x=dict()):\n    return x\n")
    (root / "pkg" / "set_call.py").write_text("def f(x=set()):\n    return x\n")
    # calls WITH args/keywords or non-builtin names are NOT flagged
    (root / "pkg" / "list_arg.py").write_text("def f(x=list((1, 2))):\n    return x\n")
    (root / "pkg" / "dict_kw.py").write_text("def f(x=dict(a=1)):\n    return x\n")
    (root / "pkg" / "frozen.py").write_text("def f(x=frozenset()):\n    return x\n")
    (root / "pkg" / "tuple_call.py").write_text("def f(x=tuple()):\n    return x\n")


def _tree_kwonly_and_async(root: Path) -> None:
    (root / "svc").mkdir()
    (root / "svc" / "kwonly.py").write_text("def f(*, a=[], b=1):\n    return a\n")
    (root / "svc" / "kwonly_clean.py").write_text("def f(*, a=1, b='x'):\n    return a\n")
    (root / "svc" / "async_lit.py").write_text(
        "async def h(z={}):\n    return z\n"
    )
    (root / "svc" / "method.py").write_text(
        "class C:\n    def m(self, q=set()):\n        return q\n"
    )


def _tree_mixed_and_broken(root: Path) -> None:
    (root / "app").mkdir()
    (root / "app" / "many.py").write_text(
        "def a(x=0):\n    return x\n\n"
        "def b(y=[]):\n    return y\n\n"  # first mutable wins -> module flagged
        "def c(z=None):\n    return z\n"
    )
    (root / "app" / "syntax_err.py").write_text("def broken(:\n")
    (root / "app" / "no_defaults.py").write_text("def a(x):\n    return x\n")


def _tree_empty(root: Path) -> None:
    (root / "pkg").mkdir()
    (root / "pkg" / "clean.py").write_text("def add(a, b):\n    return a + b\n")


_TREES = [
    _tree_literals,
    _tree_builtin_calls,
    _tree_kwonly_and_async,
    _tree_mixed_and_broken,
    _tree_empty,
]


@pytest.mark.parametrize("build", _TREES, ids=[t.__name__ for t in _TREES])
def test_scan_mutable_defaults_byte_identical(build, tmp_path):
    build(tmp_path)
    old, new = _run_both(tmp_path)
    assert new == old


def test_no_modules_returns_empty(tmp_path):
    prof = ProjectProfiler(str(tmp_path))
    assert prof._scan_mutable_defaults([]) == []
    assert _original_scan(prof, []) == []


def test_missing_file_is_skipped(tmp_path):
    prof = ProjectProfiler(str(tmp_path))
    modules = [types.SimpleNamespace(path="does/not/exist.py")]
    assert prof._scan_mutable_defaults(modules) == []
    assert _original_scan(prof, modules) == []


def test_output_is_sorted(tmp_path):
    (tmp_path / "z.py").write_text("def f(x=[]):\n    return x\n")
    (tmp_path / "a.py").write_text("def f(x={}):\n    return x\n")
    (tmp_path / "m.py").write_text("def f(x=set()):\n    return x\n")
    old, new = _run_both(tmp_path)
    assert new == ["a.py", "m.py", "z.py"]
    assert new == old


def test_helpers_are_pure_and_static():
    """The new helpers are pure (AST in -> bool out) and carry no instance state."""
    import ast

    list_node = ast.parse("x=[]").body[0].value
    set_call = ast.parse("set()").body[0].value
    dict_arg = ast.parse("dict(a=1)").body[0].value
    name_call = ast.parse("frozenset()").body[0].value

    assert ProjectProfiler._is_mutable_default(list_node) is True
    assert ProjectProfiler._is_mutable_default(set_call) is True
    assert ProjectProfiler._is_mutable_default(dict_arg) is False
    assert ProjectProfiler._is_mutable_default(name_call) is False

    fn = ast.parse("def f(x=[]):\n    return x\n").body[0]
    assert ProjectProfiler._func_has_mutable_default(fn) is True
    tree = ast.parse("def g(a=1):\n    return a\n")
    assert ProjectProfiler._tree_has_mutable_default(tree) is False
