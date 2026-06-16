"""Characterization harness proving _scan_file refactor is byte-identical.

Loads the original HEAD copy of global_state.py and the refactored working copy,
runs both _scan_file implementations over many source inputs covering every
branch, and asserts the appended (mutables, muts) lists are identical.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import app.tools.global_state as refactored


def _load_original():
    src = subprocess.check_output(
        ["git", "show", "HEAD:app/tools/global_state.py"],
        cwd=Path(__file__).resolve().parent.parent,
        text=True,
    )
    path = Path(tempfile.gettempdir()) / "_gs_orig_snapshot.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_gs_orig_snapshot", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_gs_orig_snapshot"] = mod
    spec.loader.exec_module(mod)
    return mod


ORIG = _load_original()


# Source inputs covering every branch of _scan_file.
SOURCES = {
    "empty": "",
    "list_literal": "registry = []\n",
    "dict_literal": "cache = {}\n",
    "set_literal": "seen = {1, 2}\n",
    "list_ctor": "registry = list()\n",
    "dict_ctor": "cache = dict()\n",
    "set_ctor": "seen = set()\n",
    "tuple_ctor_immutable": "x = tuple()\n",
    "frozenset_ctor_immutable": "x = frozenset()\n",
    "tuple_literal": "x = (1, 2)\n",
    "const_upper": "REGISTRY = {}\n",
    "const_under": "_CACHE = {}\n",
    "dunder_all": "__all__ = ['a']\n",
    "all_underscore": "___ = {}\n",
    "annassign_mutable": "cache: dict = {}\n",
    "annassign_no_value": "cache: dict\n",
    "annassign_const": "CACHE: dict = {}\n",
    "tuple_unpack": "a, b = [], {}\n",
    "attr_target": "obj.x = {}\n",
    "subscript_target": "d[0] = {}\n",
    "multi_target": "a = b = {}\n",
    "string_value": "x = 'hi'\n",
    "int_value": "x = 1\n",
    "none_value": "x = None\n",
    "call_other": "x = foo()\n",
    "call_method": "x = mod.list()\n",
    "global_simple": "def f():\n    global g\n    g = 1\n",
    "global_multi": "def f():\n    global a, b\n    a = b = 1\n",
    "async_global": "async def f():\n    global g\n    g = 1\n",
    "global_nested": "def f():\n    def inner():\n        global g\n        g = 1\n",
    "class_body": "class C:\n    x = {}\n",
    "class_with_global_method": "class C:\n    def m(self):\n        global g\n        g = 1\n",
    "mixed": (
        "registry = []\n"
        "CACHE = {}\n"
        "data: dict = {}\n"
        "def f():\n"
        "    global registry\n"
        "    registry.append(1)\n"
        "def g():\n"
        "    global x, y\n"
        "    x = y = 0\n"
    ),
    "syntax_error": "def f(:\n",
    "comment_only": "# nothing here\n",
    "nested_func_in_func": (
        "def outer():\n"
        "    global a\n"
        "    def inner():\n"
        "        global b\n"
        "        b = 1\n"
    ),
}


@pytest.mark.parametrize("key", sorted(SOURCES))
def test_scan_file_byte_identical(key, tmp_path):
    src = SOURCES[key]
    f = tmp_path / f"{key}_mod.py"
    f.write_text(src, encoding="utf-8")
    module = "pkg.sub.mod"

    o_mut: list[dict] = []
    o_g: list[dict] = []
    ORIG._scan_file(f, module, o_mut, o_g)

    r_mut: list[dict] = []
    r_g: list[dict] = []
    refactored._scan_file(f, module, r_mut, r_g)

    assert r_mut == o_mut, f"mutables mismatch for {key}"
    assert r_g == o_g, f"global_mutations mismatch for {key}"


def test_unreadable_file_both_noop(tmp_path):
    missing = tmp_path / "does_not_exist.py"
    o: list[dict] = []
    r: list[dict] = []
    ORIG._scan_file(missing, "m", o, o)
    refactored._scan_file(missing, "m", r, r)
    assert o == r == []


def test_full_analyze_byte_identical(tmp_path):
    (tmp_path / "a.py").write_text("registry = []\ncache = {}\n", encoding="utf-8")
    (tmp_path / "b.py").write_text(
        "def f():\n    global registry\n    registry = []\n", encoding="utf-8"
    )
    (tmp_path / "test_skip.py").write_text("leak = {}\n", encoding="utf-8")
    o = ORIG.analyze_global_state(tmp_path)
    r = refactored.analyze_global_state(tmp_path)
    # Distinct GlobalState classes (snapshot vs working copy) make dataclass
    # __eq__ return NotImplemented, so compare the fields directly.
    assert o.__dict__ == r.__dict__
