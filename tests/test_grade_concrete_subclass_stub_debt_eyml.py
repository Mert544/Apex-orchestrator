"""Concrete-subclass stub debt is no longer hidden behind ``bool(cls.bases)``.

Red-team P2 grade-honesty fix: the stub-debt scorer used to treat ANY class with
a base as an "interface" and exclude its unimplemented (``raise
NotImplementedError`` / ``...``) methods from debt. That over-excluded a CONCRETE
subclass (``class Impl(Base):`` that is itself instantiated, never abstract, never
subclassed in-project) whose own body is ``raise NotImplementedError`` — which is
real, unfinished, implementable debt, exactly what ``implement-stub`` lands.
Hiding it made the grade dishonest (under-reported debt) and made implement-stub's
own contributions invisible to the grade.

The fix drops the blanket ``bool(cls.bases)`` term, keeping only the two
principled exclusions: ``_class_is_interface`` (genuine ABC/Protocol) and
``cls.name in subclassed`` (a base subclassed in-project, whose stub methods are
intended override points). These tests pin that concrete-subclass debt now counts
while genuine ABCs / subclassed bases stay excluded.
"""

from __future__ import annotations

import ast

from app.engine.health_score import (
    _count_unimplemented_stubs,
    _subclassed_base_names,
    grade,
)


def _correctness(h):
    for c in h.components:
        if c.name == "Correctness":
            return c
    raise AssertionError("no Correctness component")


def _scaffold(root):
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='p'\nversion='0'\n", encoding="utf-8")


def _stub_debt(*sources: str) -> int:
    """Stub-debt total across the given source strings (project-wide subclass set)."""
    trees = [ast.parse(s) for s in sources]
    subclassed = _subclassed_base_names(trees)
    return sum(_count_unimplemented_stubs(t, subclassed) for t in trees)


# --- the bug: a concrete subclass's stub now counts ---------------------------

def test_concrete_subclass_notimplemented_stub_now_counts():
    """``class Impl(Base):`` (Base NOT abstract, Impl NOT subclassed) with a
    ``raise NotImplementedError`` method is real, implementable debt and MUST
    count — it was wrongly excluded by the old blanket ``bool(cls.bases)`` term.
    """
    src = (
        "class Base:\n"
        "    def g(self):\n        return 1\n\n\n"
        "class Impl(Base):\n"
        "    def f(self):\n        raise NotImplementedError\n"
    )
    assert _stub_debt(src) == 1


def test_concrete_subclass_ellipsis_stub_now_counts():
    src = (
        "class Base:\n"
        "    def g(self):\n        return 1\n\n\n"
        "class Impl(Base):\n"
        "    def f(self):\n        ...\n"
    )
    assert _stub_debt(src) == 1


def test_concrete_subclass_stub_costs_correctness_end_to_end(tmp_path):
    """Through the public ``grade()`` path: a concrete subclass stub costs points
    and is surfaced — the project can no longer read A+/100 on unfinished code.
    """
    _scaffold(tmp_path)
    (tmp_path / "app" / "impl.py").write_text(
        "class Base:\n"
        "    def g(self):\n        return 1\n\n\n"
        "class Impl(Base):\n"
        "    def f(self):\n        raise NotImplementedError\n",
        encoding="utf-8")
    h = grade(str(tmp_path))
    corr = _correctness(h)
    assert corr.points_lost > 0
    assert "unimplemented stub" in corr.detail
    assert "app/impl.py" in corr.top_files
    assert h.score < 100
    assert h.letter != "A+"


# --- the principled exclusions still hold -------------------------------------

def test_genuine_abc_subclass_stub_still_excluded():
    """A genuine ABC with an ``@abstractmethod`` stub is a contract, not debt."""
    src = (
        "import abc\n\n\n"
        "class A(abc.ABC):\n"
        "    @abc.abstractmethod\n"
        "    def f(self):\n        ...\n"
    )
    assert _stub_debt(src) == 0


def test_abc_base_class_unimpl_method_still_excluded():
    """A class inheriting ABC is an interface — its NotImplementedError method is
    an abstract extension point (caught by ``_class_is_interface``), not debt.
    """
    src = (
        "from abc import ABC\n\n\n"
        "class Store(ABC):\n"
        "    def save(self):\n        raise NotImplementedError\n"
    )
    assert _stub_debt(src) == 0


def test_subclassed_base_stub_still_excluded():
    """A class that IS subclassed in-project — its stub is an override point the
    subclass fills (caught by ``cls.name in subclassed``), not debt.
    """
    src = (
        "class Agent:\n"
        "    def _execute(self):\n        raise NotImplementedError\n\n\n"
        "class RealAgent(Agent):\n"
        "    def _execute(self):\n        return 1\n"
    )
    assert _stub_debt(src) == 0


def test_subclassed_across_modules_still_excluded():
    """The subclass set is project-wide: a base and its subclass may live in
    different modules and the base's stub still stays excluded.
    """
    base = (
        "class Agent:\n"
        "    def _execute(self):\n        raise NotImplementedError\n"
    )
    sub = (
        "from base import Agent\n\n\n"
        "class RealAgent(Agent):\n"
        "    def _execute(self):\n        return 1\n"
    )
    assert _stub_debt(base, sub) == 0


def test_baseless_class_stub_still_counts():
    """Unchanged: a base-less class with an unimplemented stub is debt."""
    src = (
        "class Solo:\n"
        "    def f(self):\n        raise NotImplementedError\n"
    )
    assert _stub_debt(src) == 1


def test_module_function_stub_still_counts():
    """Unchanged: a module-level function stub is debt."""
    assert _stub_debt("def compute(x):\n    raise NotImplementedError\n") == 1


# --- edge / empty paths -------------------------------------------------------

def test_empty_tree_no_debt():
    assert _stub_debt("") == 0
    assert _stub_debt("x = 1\n") == 0


def test_concrete_subclass_with_implemented_body_no_debt():
    """A concrete subclass that ACTUALLY implements its method is not debt."""
    src = (
        "class Base:\n    pass\n\n\n"
        "class Impl(Base):\n"
        "    def f(self):\n        return 42\n"
    )
    assert _stub_debt(src) == 0


# --- determinism --------------------------------------------------------------

def test_determinism_same_tree_same_count():
    src = (
        "class Base:\n"
        "    def g(self):\n        return 1\n\n\n"
        "class Impl(Base):\n"
        "    def f(self):\n        raise NotImplementedError\n"
    )
    first = _stub_debt(src)
    second = _stub_debt(src)
    assert first == second == 1


def test_self_grade_stays_a_plus_99():
    """Characterization: dropping ``bool(cls.bases)`` surfaces NO new debt in
    Apex's own concrete subclasses — every Apex class with a NotImplementedError
    body is correctly excluded by ``_class_is_interface`` (genuine ABC/Protocol)
    or ``subclassed`` (a base subclassed in-project), never by the dropped blanket
    base term. Apex's own stub-debt total is 0 and the self-grade holds at A+ 99
    (the lone remaining fix is unrelated duplication).
    """
    g = grade(".")
    assert (g.letter, g.score) == ("A+", 99)
