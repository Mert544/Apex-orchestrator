"""Characterization tests pinning ``_capture_oracles`` and its pure helpers.

These exercise every branch of the oracle-capture path (empty specs, simple /
kwargs / nested literal returns, calls that raise, non-callable and missing
attributes, non-literal arguments, non-literal and NaN returns, bad call-arg
syntax, non-importable modules, import errors, and dotted packages) and assert
the exact returned mapping, plus that ``sys.path`` / ``sys.modules`` are restored
unchanged. They pin the behaviour the byte-identical decomposition preserves.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

from app.execution.test_shield import (
    _capture_one_oracle,
    _capture_oracles,
    _collect_oracles,
    _restore_modules,
    _stale_module_names,
)

_MOD_OK = """
def f():
    return 42

def g(a, b=3):
    return a + b

def h():
    return {'x': [1, 2], 't': (1, 'a')}

def raises():
    raise ValueError("boom")

not_callable = 7

def nonlit():
    return object()

def floaty():
    return float('nan')

def strret():
    return "hello"
"""


def _write_module(root: Path, modname: str, src: str) -> None:
    (root / (modname + ".py")).write_text(textwrap.dedent(src), encoding="utf-8")


def _capture(tmp_path: Path, modname: str, src: str, specs):
    """Run ``_capture_oracles`` against a freshly written module, asserting that
    ``sys.path`` / ``sys.modules`` are restored exactly."""
    _write_module(tmp_path, modname, src)
    path_before = list(sys.path)
    mods_before = dict(sys.modules)
    out = _capture_oracles(tmp_path, modname, specs)
    assert sys.path == path_before
    assert set(sys.modules) == set(mods_before)
    return out


def test_empty_specs_returns_empty(tmp_path):
    assert _capture_oracles(tmp_path, "anything", []) == {}


def test_simple_literal_oracle(tmp_path):
    assert _capture(tmp_path, "char_simple", _MOD_OK, [("f", "")]) == {"f": "42"}


def test_kwargs_and_args(tmp_path):
    assert _capture(tmp_path, "char_kw", _MOD_OK, [("g", "5, b=10")]) == {"g": "15"}


def test_nested_literal_oracle(tmp_path):
    # Dict keys render SORTED ('t' < 'x') for hash-seed-stable bytes; the contained
    # list/tuple keep their (deterministic) order, so the value oracle still lands.
    out = _capture(tmp_path, "char_nested", _MOD_OK, [("h", "")])
    assert out == {"h": "{'t': (1, 'a'), 'x': [1, 2]}"}


def test_string_return_oracle(tmp_path):
    assert _capture(tmp_path, "char_str", _MOD_OK, [("strret", "")]) == {
        "strret": "'hello'"
    }


def test_call_that_raises_declines(tmp_path):
    assert _capture(tmp_path, "char_raise", _MOD_OK, [("raises", "")]) == {}


def test_non_callable_attribute_declines(tmp_path):
    assert _capture(tmp_path, "char_nc", _MOD_OK, [("not_callable", "")]) == {}


def test_missing_attribute_declines(tmp_path):
    assert _capture(tmp_path, "char_miss", _MOD_OK, [("nope", "")]) == {}


def test_non_literal_argument_declines(tmp_path):
    assert _capture(tmp_path, "char_nla", _MOD_OK, [("f", "set()")]) == {}


def test_non_literal_return_declines(tmp_path):
    assert _capture(tmp_path, "char_nlr", _MOD_OK, [("nonlit", "")]) == {}


def test_nan_return_declines(tmp_path):
    assert _capture(tmp_path, "char_nan", _MOD_OK, [("floaty", "")]) == {}


def test_bad_call_arg_syntax_declines(tmp_path):
    assert _capture(tmp_path, "char_bad", _MOD_OK, [("f", "1, , 2")]) == {}


def test_mixed_specs(tmp_path):
    out = _capture(
        tmp_path,
        "char_mixed",
        _MOD_OK,
        [
            ("f", ""),
            ("raises", ""),
            ("g", "1, b=2"),
            ("not_callable", ""),
            ("nonlit", ""),
            ("h", ""),
            ("missing", ""),
        ],
    )
    assert out == {"f": "42", "g": "3", "h": "{'t': (1, 'a'), 'x': [1, 2]}"}


def test_non_importable_module(tmp_path):
    out = _capture_oracles(tmp_path, "totally_absent_module_xyz", [("f", "")])
    assert out == {}


def test_import_error_module(tmp_path):
    (tmp_path / "char_broken.py").write_text("def broken(:\n", encoding="utf-8")
    path_before = list(sys.path)
    mods_before = dict(sys.modules)
    out = _capture_oracles(tmp_path, "char_broken", [("broken", "")])
    assert out == {}
    assert sys.path == path_before
    assert set(sys.modules) == set(mods_before)


def test_dotted_package(tmp_path):
    pkg = tmp_path / "char_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "leaf.py").write_text(textwrap.dedent(_MOD_OK), encoding="utf-8")
    path_before = list(sys.path)
    mods_before = dict(sys.modules)
    out = _capture_oracles(tmp_path, "char_pkg.leaf", [("f", ""), ("g", "2, b=2")])
    assert out == {"f": "42", "g": "4"}
    assert sys.path == path_before
    assert set(sys.modules) == set(mods_before)


# --- pure helpers in isolation ---------------------------------------------


def test_stale_module_names_matches_exact_and_package_prefix():
    # Evicts ``dotted`` itself and any of its package PREFIXES; a deeper
    # submodule (``pkg.leaf.sub``) and an unrelated name are left alone.
    names = ["pkg", "pkg.leaf", "pkgother", "other", "pkg.leaf.sub"]
    assert _stale_module_names("pkg.leaf", names) == ["pkg", "pkg.leaf"]


def test_stale_module_names_empty():
    assert _stale_module_names("pkg.leaf", []) == []


class _Mod:
    def f(self):
        return 42

    not_callable = 7

    def raises(self):
        raise ValueError("boom")

    def nonlit(self):
        return object()


def test_capture_one_oracle_simple():
    assert _capture_one_oracle(_Mod(), "f", "") == "42"


def test_capture_one_oracle_declines_each_branch():
    m = _Mod()
    assert _capture_one_oracle(m, "f", "set()") is None  # non-literal arg
    assert _capture_one_oracle(m, "not_callable", "") is None  # not callable
    assert _capture_one_oracle(m, "missing", "") is None  # missing attr
    assert _capture_one_oracle(m, "raises", "") is None  # call raises
    assert _capture_one_oracle(m, "nonlit", "") is None  # non-literal return


def test_collect_oracles_filters_declines():
    assert _collect_oracles(_Mod(), [("f", ""), ("raises", ""), ("nonlit", "")]) == {
        "f": "42"
    }


def test_collect_oracles_empty():
    assert _collect_oracles(_Mod(), []) == {}


def test_restore_modules_drops_added_and_restores_evicted():
    saved = dict(sys.modules)
    sentinel_added = "char_sentinel_added_mod"
    sys.modules[sentinel_added] = object()  # type: ignore[assignment]
    # evict an existing real module
    evicted_name, evicted_mod = next(iter(saved.items()))
    del sys.modules[evicted_name]
    _restore_modules(saved)
    assert sentinel_added not in sys.modules
    assert sys.modules.get(evicted_name) is evicted_mod


def test_target_package_named_app_still_lands_its_oracle(tmp_path):
    """A target whose top-level package is literally named ``app`` (a very common
    real project name — and the shield's OWN package name) still lands its value
    oracle: the probe children bind the shield helpers from the shield's repo
    FIRST, then purge the module cache so the TARGET's ``app`` resolves under its
    own root (`_PROBE_PREAMBLE`). Before that, the target's ``app`` shadowed the
    helpers' package inside every probe, the helper import died, and EVERY oracle
    silently declined — an honest but needless capability loss (witness mining and
    value oracles returned nothing on any project named ``app``). Guards the
    collision AND the ambient-env independence (no PYTHONPATH is required for the
    probe to find its own helpers)."""
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "colliding.py").write_text("def f():\n    return 42\n", encoding="utf-8")
    assert _capture_oracles(tmp_path, "app.colliding", [("f", "")]) == {"f": "42"}
