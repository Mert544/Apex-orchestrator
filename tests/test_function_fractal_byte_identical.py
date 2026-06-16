"""Characterization tests proving the refactor of ``_analyze_function`` is
byte-identical to the pre-refactor implementation.

The original module source is loaded from ``git show HEAD:<path>`` and imported
under a throwaway module name, then both analyzers are run over a representative
temp tree. Full ``analyze_file`` / ``build_call_graph`` / ``compute_cross_file_impact``
outputs are compared field-by-field (and via ``repr``) for exact equality.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_REL = "app/tools/function_fractal_analyzer.py"


def _load_original_class():
    """Import the HEAD version of the analyzer under a unique module name."""
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{MODULE_REL}"], cwd=REPO_ROOT, text=True
    )
    mod_name = "_ffa_head_original"
    spec = importlib.util.spec_from_loader(mod_name, loader=None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    exec(compile(src, "<head:function_fractal_analyzer.py>", "exec"), module.__dict__)
    return module.FunctionFractalAnalyzer


# Representative source samples exercising every risk/purity branch.
SAMPLES = {
    "app/pkg/risky.py": '''
import os
import subprocess
import pickle
import yaml


def uses_eval(x):
    return eval(x)


def uses_exec(code):
    exec(code)


def py2_input():
    return input()


def dyn_import(name):
    return __import__(name)


def shell(cmd):
    os.system(cmd)
    subprocess.call(cmd)


def deser(blob):
    pickle.loads(blob)
    yaml.load(blob)


def many_args(a, b, c, d, e, f):
    """Has too many args."""
    return a + b + c + d + e + f


def bare_excepts():
    """Two bare excepts score twice."""
    try:
        pass
    except:
        pass
    try:
        pass
    except:
        pass
''',
    "app/pkg/clean.py": '''
"""Module docstring."""


def documented(a, b):
    """A clean pure function."""
    return a + b


class Widget:
    """A class."""

    def method(self, value):
        """Method docstring."""
        return value * 2

    def impure_method(self):
        print("hello")
        global _G
        _G = 1
''',
    "app/pkg/longfn.py": '''
def long_one():
    a = 0
''' + "".join(f"    a += {i}\n" for i in range(40)) + "    return a\n",
    "app/pkg/calls.py": '''
from app.pkg.clean import documented


def caller():
    return documented(1, 2)


async def async_caller():
    documented(3, 4)
''',
    "app/pkg/empty.py": "",
    "app/pkg/syntax_error.py": "def broken(:\n    pass\n",
}


@pytest.fixture
def tree(tmp_path):
    for rel, content in SAMPLES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def _fresh_analyzers():
    from app.tools.function_fractal_analyzer import FunctionFractalAnalyzer as New

    Old = _load_original_class()
    return Old(), New()


def test_analyze_file_byte_identical(tree):
    old, new = _fresh_analyzers()
    for rel in SAMPLES:
        path = tree / rel
        r_old = old.analyze_file(path)
        r_new = new.analyze_file(path)
        assert repr(r_old) == repr(r_new), f"mismatch in {rel}"
        assert r_old == r_new


def test_build_call_graph_byte_identical(tree):
    old, new = _fresh_analyzers()
    g_old = old.build_call_graph(tree)
    g_new = new.build_call_graph(tree)
    assert repr(g_old) == repr(g_new)
    assert list(g_old.keys()) == list(g_new.keys())


def test_cross_file_impact_byte_identical(tree):
    old, new = _fresh_analyzers()
    i_old = old.compute_cross_file_impact(tree)
    i_new = new.compute_cross_file_impact(tree)
    assert repr(i_old) == repr(i_new)


def test_real_repo_files_byte_identical():
    """Run both over a slice of the actual repo for extra coverage."""
    old, new = _fresh_analyzers()
    targets = sorted((REPO_ROOT / "app" / "tools").glob("*.py"))[:8]
    for path in targets:
        assert repr(old.analyze_file(path)) == repr(new.analyze_file(path)), path
