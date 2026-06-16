"""Characterization: refactored api_ergonomics is byte-identical to HEAD original.

Loads the pre-refactor snapshot of ``app/tools/api_ergonomics.py`` (captured from
``git show HEAD:...``) as a standalone module and runs both it and the current
module over a battery of source inputs that exercise EVERY branch of
``_analyze_function``: long lists, boolean traps, positional overload, kw-only
markers, varargs-only, receivers, dunders, nested defs, classmethods, defaults
alignment edges, and empty/unparseable trees. Outputs (full ``to_dict``, order +
contents) must match with zero mismatches.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

import app.tools.api_ergonomics as current

_REPO = Path(__file__).resolve().parents[1]
_TARGET = "app/tools/api_ergonomics.py"


def _load_original_module(tmp_path: Path):
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{_TARGET}"], cwd=_REPO, text=True
    )
    path = tmp_path / "api_ergonomics_orig.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("api_ergonomics_orig", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["api_ergonomics_orig"] = mod  # dataclass needs module registered
    spec.loader.exec_module(mod)
    return mod


# Source bodies exercising every branch / threshold of the analyzer.
_CASES: dict[str, str] = {
    "empty": "",
    "syntax_error": "def f(:\n",
    "no_params": "def f():\n    return 1\n",
    "varargs_only": "def f(*args, **kwargs):\n    return 1\n",
    "short_ok": "def f(a, b, c):\n    return 1\n",
    "long_list": "def f(a, b, c, d, e, f, g):\n    return 1\n",
    "exactly_max": "def f(a, b, c, d, e):\n    return 1\n",
    "bool_trap_anno": "def f(a: bool, b: bool):\n    return 1\n",
    "bool_trap_default": "def f(a=True, b=False):\n    return 1\n",
    "single_bool": "def f(a: bool, b):\n    return 1\n",
    "optional_bool_skipped": "def f(a: 'bool | None' = None):\n    return 1\n",
    "positional_overload": "def f(a, b, c, d, e, ff):\n    return 1\n",
    "pos_overload_with_star": "def f(a, b, c, d, e, ff, *, kw=1):\n    return 1\n",
    "pos_overload_with_vararg": "def f(a, b, c, d, e, ff, *rest):\n    return 1\n",
    "kwonly_counts": "def f(a, b, c, *, d, e, ff):\n    return 1\n",
    "posonly": "def f(a, b, /, c, d, e, ff):\n    return 1\n",
    "defaults_tail": "def f(a, b, c=True, d=False, e=True, ff=False):\n    return 1\n",
    "kw_defaults_gap": "def f(*, a, b=True, c=False, d=True):\n    return 1\n",
    "dunder_skipped": (
        "class C:\n"
        "    def __init__(self, a, b, c, d, e, ff):\n"
        "        pass\n"
    ),
    "method_receiver": (
        "class C:\n"
        "    def m(self, a, b, c, d, e, ff):\n"
        "        return 1\n"
    ),
    "classmethod_cls": (
        "class C:\n"
        "    @classmethod\n"
        "    def m(cls, a, b, c, d, e, ff):\n"
        "        return 1\n"
    ),
    "nested_fn": (
        "def outer(a, b, c, d, e, ff):\n"
        "    def inner(g, h, i, j, k, l):\n"
        "        return 1\n"
        "    return inner\n"
    ),
    "async_def": "async def f(a, b, c, d, e, ff, g):\n    return 1\n",
    "all_smells": "def f(a: bool, b: bool, c, d, e, ff):\n    return 1\n",
    "method_only_self": (
        "class C:\n"
        "    def m(self):\n"
        "        return 1\n"
    ),
    "self_not_method_ctx": "def f(self, a, b, c, d, e, ff):\n    return 1\n",
}


@pytest.fixture
def original(tmp_path):
    return _load_original_module(tmp_path)


def _build_tree(root: Path) -> None:
    for name, body in _CASES.items():
        (root / f"{name}.py").write_text(body, encoding="utf-8")


@pytest.mark.parametrize("max_params", [0, 1, 3, 5, 10])
def test_byte_identical_reports(original, tmp_path, max_params):
    tree = tmp_path / "proj"
    tree.mkdir()
    _build_tree(tree)

    orig_out = original.analyze_api_ergonomics(tree, max_params=max_params).to_dict()
    new_out = current.analyze_api_ergonomics(tree, max_params=max_params).to_dict()
    assert new_out == orig_out


def test_empty_tree_identical(original, tmp_path):
    tree = tmp_path / "empty"
    tree.mkdir()
    assert (
        current.analyze_api_ergonomics(tree).to_dict()
        == original.analyze_api_ergonomics(tree).to_dict()
    )


def test_offender_order_and_cap_identical(original, tmp_path):
    tree = tmp_path / "many"
    tree.mkdir()
    # 30 long functions -> exercises sort + _OFFENDER_CAP truncation.
    for i in range(30):
        n = 6 + (i % 4)
        params = ", ".join(f"p{j}" for j in range(n))
        (tree / f"mod{i:02d}.py").write_text(
            f"def f{i}({params}):\n    return 1\n", encoding="utf-8"
        )
    orig_out = original.analyze_api_ergonomics(tree).to_dict()
    new_out = current.analyze_api_ergonomics(tree).to_dict()
    assert new_out == orig_out
    assert len(new_out["offenders"]) == len(orig_out["offenders"])
    assert [o["function"] for o in new_out["offenders"]] == [
        o["function"] for o in orig_out["offenders"]
    ]
