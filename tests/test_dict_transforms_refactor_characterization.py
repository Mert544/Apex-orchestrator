"""Characterization tests pinning the refactored ``dict_get`` /
``dict_comprehension`` transforms to their exact rewrite and skip behaviour.

These exercise the public ``plan_*`` paths directly: a rewrite case asserts the
expected ``x.get(...)`` / comprehension text, and a battery of skip cases assert
an empty (no-op) plan. They guard the decomposition of ``_try_ifexp`` and
``_subscript_kv`` into pure helpers from drifting.
"""

from __future__ import annotations

import pytest

from app.execution.dict_get import plan_simplify_dict_get
from app.execution.dict_comprehension import plan_dict_comprehension


def _plan_get(tmp_path, src: str):
    p = tmp_path / "m.py"
    p.write_text(src)
    return plan_simplify_dict_get(str(tmp_path), "m.py")


def _plan_comp(tmp_path, src: str):
    p = tmp_path / "m.py"
    p.write_text(src)
    return plan_dict_comprehension(str(tmp_path), "m.py")


def _new_text(plan) -> str | None:
    """The single rewritten module text in a plan, or None when nothing was
    rewritten (``new_contents`` empty)."""
    if not plan.new_contents:
        return None
    return next(iter(plan.new_contents.values()))


# --- dict_get -------------------------------------------------------------

def test_dict_get_rewrites_name(tmp_path):
    plan = _plan_get(tmp_path, "y = x[k] if k in x else d\n")
    assert _new_text(plan) == "y = x.get(k, d)\n"


def test_dict_get_rewrites_attr_chain(tmp_path):
    plan = _plan_get(tmp_path, "y = self.cache[k] if k in self.cache else None\n")
    assert _new_text(plan) == "y = self.cache.get(k, None)\n"


def test_dict_get_rewrites_two_on_one_line(tmp_path):
    plan = _plan_get(
        tmp_path, "y = (x[k] if k in x else d) + (a[b] if b in a else c)\n")
    assert _new_text(plan) == "y = (x.get(k, d)) + (a.get(b, c))\n"


@pytest.mark.parametrize("src", [
    "y = (x[k]\n     if k in x else d)\n",      # multiline
    "y = x[k] if k in z else d\n",              # container mismatch
    "y = x[k] if j in x else d\n",              # key mismatch
    "y = f()[k] if k in f() else d\n",          # impure container
    "y = x[f()] if f() in x else d\n",          # impure key
    "y = x[a:b] if a in x else d\n",            # slice
    "y = x if k in x else d\n",                 # body not subscript
    "y = x[k] if k not in x else d\n",          # not-in
    "y = x[k] if a < k < x else d\n",           # two-op compare
    "z = 1\n",                                  # unrelated
])
def test_dict_get_skips(tmp_path, src):
    assert _new_text(_plan_get(tmp_path, src)) is None


# --- dict_comprehension ---------------------------------------------------

def test_comp_rewrites_simple(tmp_path):
    plan = _plan_comp(tmp_path, "out = {}\nfor t in it:\n    out[t] = t\n")
    assert _new_text(plan) == "out = {t: t for t in it}\n"


def test_comp_rewrites_tuple_target(tmp_path):
    plan = _plan_comp(tmp_path, "out = {}\nfor (a, b) in it:\n    out[a] = b\n")
    assert _new_text(plan) == "out = {a: b for (a, b) in it}\n"


@pytest.mark.parametrize("src", [
    "out = {}\nfor t in it:\n    out[t] = t\nelse:\n    pass\n",   # else clause
    "out = {}\nfor t in it:\n    out[t] = t\n    print(t)\n",      # multi-stmt body
    "out = {}\nfor t in it:\n    out[t] = out\n",                  # name in value
    "out = {}\nfor t in it:\n    out[out] = t\n",                  # name in key
    "out = {}\nfor t in it:\n    out[a:b] = t\n",                  # slice target
    "out = {1: 2}\nfor t in it:\n    out[t] = t\n",                # non-empty dict
    "out = {1}\nfor t in it:\n    out[t] = t\n",                   # set literal
    "out = {}\nfor t in it:\n    out[t] = z = t\n",                # chained assign
    "out = {}\nfor t in it:\n    self.out[t] = t\n",               # attr receiver
    "out = {}\nz = 1\n",                                           # no for
    "out = {}\nfor *a, b in it:\n    out[b] = a\n",                # starred target
    "out = {}\nfor t in it:\n    out[(t +\n         1)] = t\n",    # multiline key
])
def test_comp_skips(tmp_path, src):
    assert _new_text(_plan_comp(tmp_path, src)) is None
