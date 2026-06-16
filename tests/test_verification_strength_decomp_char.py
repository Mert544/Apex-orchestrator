"""Characterization tests pinning assess_strength's exact output after its
decomposition into pure helpers (_weaker, _names_changed_function, _grade_file).

Each case exercises a distinct branch; the asserted dicts are the full,
byte-for-byte output the function produced before the refactor.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.verification_strength import (
    _grade_file,
    _names_changed_function,
    _weaker,
    assess_strength,
)

_CODE_A = "def foo():\n    return 1\n\ndef bar(x):\n    return x\n"
_CODE_A2 = "def foo():\n    return 2\n\ndef bar(x):\n    return x\n"
_CODE_B = "def baz():\n    pass\n"


def _build(tmp: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp


def test_no_code_files_is_test_change(tmp_path):
    assert assess_strength(tmp_path, ["tests/test_x.py"],
                           {"tests/test_x.py": None},
                           {"tests/test_x.py": _CODE_B}) == {
        "level": "test-change", "changed_functions": [],
        "module_tests": [], "function_tests": []}


def test_empty_changed_files(tmp_path):
    assert assess_strength(tmp_path, [], {}, {}) == {
        "level": "test-change", "changed_functions": [],
        "module_tests": [], "function_tests": []}


def test_non_python_only(tmp_path):
    assert assess_strength(tmp_path, ["README.md"],
                           {"README.md": None}, {"README.md": "hi"}) == {
        "level": "test-change", "changed_functions": [],
        "module_tests": [], "function_tests": []}


def test_function_level(tmp_path):
    root = _build(tmp_path, {
        "tests/test_mod.py": "from pkg.mod import foo\ndef test_it():\n    foo()\n"})
    assert assess_strength(root, ["pkg/mod.py"],
                           {"pkg/mod.py": _CODE_A},
                           {"pkg/mod.py": _CODE_A2}) == {
        "level": "function",
        "changed_functions": ["pkg/mod.py::foo"],
        "module_tests": ["tests/test_mod.py"],
        "function_tests": ["tests/test_mod.py"]}


def test_module_level_no_named_function(tmp_path):
    root = _build(tmp_path, {
        "tests/test_mod.py": "from pkg.mod import bar\ndef test_it():\n    bar(1)\n"})
    assert assess_strength(root, ["pkg/mod.py"],
                           {"pkg/mod.py": _CODE_A},
                           {"pkg/mod.py": _CODE_A2}) == {
        "level": "module",
        "changed_functions": ["pkg/mod.py::foo"],
        "module_tests": ["tests/test_mod.py"],
        "function_tests": []}


def test_none_level_unreferenced(tmp_path):
    root = _build(tmp_path, {
        "tests/test_other.py": "def test_z():\n    assert True\n"})
    assert assess_strength(root, ["pkg/mod.py"],
                           {"pkg/mod.py": _CODE_A},
                           {"pkg/mod.py": _CODE_A2}) == {
        "level": "none",
        "changed_functions": ["pkg/mod.py::foo"],
        "module_tests": [],
        "function_tests": []}


def test_worst_across_multiple_files(tmp_path):
    root = _build(tmp_path, {
        "tests/test_mod.py": "from pkg.mod import foo\ndef test_it():\n    foo()\n"})
    assert assess_strength(
        root, ["pkg/mod.py", "pkg/uncov.py"],
        {"pkg/mod.py": _CODE_A, "pkg/uncov.py": _CODE_B},
        {"pkg/mod.py": _CODE_A2, "pkg/uncov.py": "def baz():\n    return 9\n"}) == {
        "level": "none",
        "changed_functions": ["pkg/mod.py::foo", "pkg/uncov.py::baz"],
        "module_tests": ["tests/test_mod.py"],
        "function_tests": ["tests/test_mod.py"]}


def test_truncation_to_five(tmp_path):
    big_old = "".join(f"def f{i}():\n    return {i}\n\n" for i in range(8))
    big_new = "".join(f"def f{i}():\n    return {i + 100}\n\n" for i in range(8))
    files = {f"tests/test_f{i}.py": f"from pkg.mod import f{i}\nf{i}()\n"
             for i in range(8)}
    root = _build(tmp_path, files)
    out = assess_strength(root, ["pkg/mod.py"],
                          {"pkg/mod.py": big_old}, {"pkg/mod.py": big_new})
    assert out["level"] == "function"
    assert out["changed_functions"] == [f"pkg/mod.py::f{i}" for i in range(5)]
    assert out["module_tests"] == [f"tests/test_f{i}.py" for i in range(5)]
    assert out["function_tests"] == [f"tests/test_f{i}.py" for i in range(5)]


def test_new_file_old_none(tmp_path):
    root = _build(tmp_path, {"tests/test_mod.py": "import pkg.mod\nfoo\n"})
    out = assess_strength(root, ["pkg/mod.py"],
                          {"pkg/mod.py": None}, {"pkg/mod.py": _CODE_A2})
    assert out["level"] == "function"
    assert out["changed_functions"] == ["pkg/mod.py::bar", "pkg/mod.py::foo"]


# --- pure-helper unit characterization ---

@pytest.mark.parametrize("current,candidate,expected", [
    ("function", "module", "module"),
    ("function", "none", "none"),
    ("module", "function", "module"),
    ("none", "function", "none"),
    ("module", "module", "module"),
])
def test_weaker(current, candidate, expected):
    assert _weaker(current, candidate) == expected


def test_names_changed_function():
    assert _names_changed_function("call foo() now", ["foo"]) is True
    assert _names_changed_function("foobar only", ["foo"]) is False
    assert _names_changed_function("nothing here", []) is False


def test_grade_file_pure():
    tests = [("tests/test_mod.py", "from pkg.mod import foo\nfoo()\n"),
             ("tests/test_unrelated.py", "assert True\n")]
    level, mods, funcs = _grade_file("pkg/mod.py", ["foo"], tests)
    assert level == "function"
    assert mods == ["tests/test_mod.py"]
    assert funcs == ["tests/test_mod.py"]

    level2, mods2, funcs2 = _grade_file("pkg/mod.py", ["bar"], tests)
    assert level2 == "module"
    assert mods2 == ["tests/test_mod.py"]
    assert funcs2 == []

    level3, mods3, funcs3 = _grade_file("pkg/other.py", ["x"], tests)
    assert level3 == "none"
    assert mods3 == []
    assert funcs3 == []
