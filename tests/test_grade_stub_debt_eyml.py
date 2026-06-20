"""Stub-debt-in-Correctness: the grade now SEES unimplemented develop work.

A project of stubs used to read A+/100 because grade() never ran the suite and
only flagged SyntaxErrors. These tests pin the fix (Fix A): a NON-abstract
unimplemented stub (``raise NotImplementedError`` / ``...``) is folded into the
EXISTING Correctness bucket as debt, so the grade can flag the work to do AND
rise once `apex develop` lands it — while legitimate abstract / interface /
override stubs are excluded so a real ABC isn't wrongly charged.
"""

from __future__ import annotations

from app.engine.health_score import grade


def _correctness(h):
    """The single Correctness component (name, points_lost, detail, top_files)."""
    for c in h.components:
        if c.name == "Correctness":
            return c
    raise AssertionError("no Correctness component")


def _snapshot(h):
    return {
        "score": h.score,
        "letter": h.letter,
        "components": [
            (c.name, c.points_lost, c.detail, list(c.top_files))
            for c in h.components
        ],
    }


def _scaffold(root):
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='p'\nversion='0'\n", encoding="utf-8")


def test_non_abstract_notimplemented_stub_costs_correctness(tmp_path):
    _scaffold(tmp_path)
    (tmp_path / "app" / "m.py").write_text(
        "def compute(x):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import compute\ndef test_c():\n    assert True\n", encoding="utf-8")
    h = grade(str(tmp_path))
    corr = _correctness(h)
    # The stub is develop debt: it MUST cost Correctness points, so the project
    # can no longer read A+/100 on broken/unfinished code.
    assert corr.points_lost > 0
    assert "unimplemented stub" in corr.detail
    assert "app/m.py" in corr.top_files
    assert h.score < 100
    assert h.letter != "A+"


def test_ellipsis_stub_costs_correctness(tmp_path):
    _scaffold(tmp_path)
    (tmp_path / "app" / "m.py").write_text(
        "def compute(x):\n    ...\n", encoding="utf-8")
    h = grade(str(tmp_path))
    corr = _correctness(h)
    assert corr.points_lost > 0
    assert "unimplemented stub" in corr.detail


def test_abstractmethod_stub_not_penalized(tmp_path):
    _scaffold(tmp_path)
    (tmp_path / "app" / "iface.py").write_text(
        "from abc import abstractmethod\n\n\n"
        "class Base:\n"
        "    @abstractmethod\n"
        "    def run(self):\n        raise NotImplementedError\n",
        encoding="utf-8")
    h = grade(str(tmp_path))
    corr = _correctness(h)
    # An abstract method is a contract, not unfinished concrete work.
    assert corr.points_lost == 0
    assert "unimplemented stub" not in corr.detail


def test_protocol_class_stub_not_penalized(tmp_path):
    _scaffold(tmp_path)
    (tmp_path / "app" / "proto.py").write_text(
        "from typing import Protocol\n\n\n"
        "class Reader(Protocol):\n"
        "    def read(self) -> str:\n        ...\n",
        encoding="utf-8")
    h = grade(str(tmp_path))
    assert _correctness(h).points_lost == 0


def test_abc_base_class_stub_not_penalized(tmp_path):
    _scaffold(tmp_path)
    (tmp_path / "app" / "abcbase.py").write_text(
        "from abc import ABC\n\n\n"
        "class Store(ABC):\n"
        "    def save(self):\n        raise NotImplementedError\n",
        encoding="utf-8")
    h = grade(str(tmp_path))
    assert _correctness(h).points_lost == 0


def test_override_stub_on_subclassed_base_not_penalized(tmp_path):
    """A stub method on a class that IS subclassed is a template hook, not debt.

    Mirrors Apex's own ``Agent._execute`` / ``LLMProvider.complete`` — a base
    class with no ABC marker whose method a subclass fills downstream.
    """
    _scaffold(tmp_path)
    (tmp_path / "app" / "base.py").write_text(
        "class Agent:\n"
        "    def _execute(self):\n        raise NotImplementedError\n\n\n"
        "class RealAgent(Agent):\n"
        "    def _execute(self):\n        return 1\n",
        encoding="utf-8")
    h = grade(str(tmp_path))
    assert _correctness(h).points_lost == 0


def test_bare_pass_body_not_penalized(tmp_path):
    """A bare ``pass`` is a legitimate no-op (plugin hook), not explicit debt."""
    _scaffold(tmp_path)
    (tmp_path / "app" / "plugin.py").write_text(
        "def register(proxy):\n    pass\n", encoding="utf-8")
    h = grade(str(tmp_path))
    assert _correctness(h).points_lost == 0
    assert "unimplemented stub" not in _correctness(h).detail


def test_implementing_the_stub_raises_the_grade(tmp_path):
    """The whole point: a verified stub-implementation MUST move the grade UP."""
    before = tmp_path / "before"
    after = tmp_path / "after"
    for root, body in ((before, "    raise NotImplementedError\n"),
                       (after, "    return x + 1\n")):
        root.mkdir()
        _scaffold(root)
        (root / "app" / "m.py").write_text(
            "def compute(x):\n" + body, encoding="utf-8")
        (root / "tests" / "test_m.py").write_text(
            "from app.m import compute\ndef test_c():\n    assert True\n",
            encoding="utf-8")
    h_before = grade(str(before))
    h_after = grade(str(after))
    assert h_after.score > h_before.score
    assert _correctness(h_after).points_lost < _correctness(h_before).points_lost


def test_no_stub_project_is_byte_identical_to_before(tmp_path):
    """A project with NO unimplemented stub grades EXACTLY as before the fix.

    The pre-fix Correctness component for a clean project is
    ``("Correctness", 0, "0 likely-crash / dead-code bug(s)", [])`` — the stub
    fold-in must leave that, and the whole snapshot, byte-identical.
    """
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calc.py").write_text(
        'def add(a, b):\n    """Add."""\n    return a + b\n', encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8")
    expected = {
        "score": 100,
        "letter": "A+",
        "components": [
            ("Security", 0, "0 finding(s)", []),
            ("Architecture", 0, "0 import cycle(s), 0 fragile module(s)", []),
            ("Testing", 0, "0 untested module(s) of ~1", []),
            ("Code debt", 0,
             "0 module(s) with modernization / mutable-default / reliability debt", []),
            ("Correctness", 0, "0 likely-crash / dead-code bug(s)", []),
            ("Maintainability", 0, "0 function(s) over complexity 12", []),
            ("Duplication", 0, "0 duplicated block(s)", []),
        ],
    }
    assert _snapshot(grade(str(tmp_path))) == expected
