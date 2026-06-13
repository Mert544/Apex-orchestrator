"""Tests for the shared standard-objective helper, app/execution/objectives/_base.

``register_module_objective`` collapses the identical ``_modules``/``fitness``/
``moves`` trio that every standard spec used to hand-copy. These tests pin the
behaviour it must reproduce byte-for-byte: module selection, fitness = number of
changed modules, and the exact ``operator``/``target``/``description`` of each
emitted Move — plus the empty/edge paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.engine import develop_registry
from app.execution.objectives._base import register_module_objective


@dataclass
class _FakePlan:
    """Minimal stand-in for a RenamePlan: only ``new_contents`` is read."""
    new_contents: dict = field(default_factory=dict)


def _make_project(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _cleanup(name):
    develop_registry._REGISTRY.pop(name, None)


def test_returns_registered_spec(tmp_path):
    spec = register_module_objective(
        "demo-base", lambda root, rel: _FakePlan(),
        operator="demo_base", description="apply demo in {rel}")
    try:
        assert spec is develop_registry._REGISTRY["demo-base"]
        assert spec.name == "demo-base"
        assert callable(spec.fitness) and callable(spec.moves)
    finally:
        _cleanup("demo-base")


def test_fitness_and_moves_match_changed_modules(tmp_path):
    _make_project(tmp_path)

    def plan(root, rel):
        # Only a.py is "changed"; b.py is a clean no-op.
        return _FakePlan({rel: "x = 0\n"}) if rel.endswith("a.py") else _FakePlan()

    spec = register_module_objective(
        "demo-changed", plan, operator="demo_op",
        description="apply demo-changed in {rel}")
    try:
        moves = spec.moves(str(tmp_path))
        assert spec.fitness(str(tmp_path)) == 1.0
        assert len(moves) == 1
        m = moves[0]
        assert m.operator == "demo_op"
        assert m.target == "app/a.py:demo-changed"          # suffix defaults to name
        assert m.description == "apply demo-changed in app/a.py"
        # build_plan re-derives against the live tree via plan(root, rel)
        assert m.build_plan().new_contents == {"app/a.py": "x = 0\n"}
    finally:
        _cleanup("demo-changed")


def test_target_suffix_override(tmp_path):
    _make_project(tmp_path)
    spec = register_module_objective(
        "remove-demo", lambda root, rel: _FakePlan({rel: "z\n"}),
        operator="remove_demo", description="strip demo in {rel}",
        target_suffix="demo")
    try:
        moves = spec.moves(str(tmp_path))
        # Two own modules, both "changed" -> two moves, each using the override suffix.
        assert {m.target for m in moves} == {"app/a.py:demo", "app/b.py:demo"}
        assert spec.fitness(str(tmp_path)) == 2.0
    finally:
        _cleanup("remove-demo")


def test_empty_when_nothing_changes(tmp_path):
    _make_project(tmp_path)
    spec = register_module_objective(
        "demo-empty", lambda root, rel: _FakePlan(),  # always a no-op
        operator="demo_empty", description="apply demo-empty in {rel}")
    try:
        assert spec.fitness(str(tmp_path)) == 0.0
        assert spec.moves(str(tmp_path)) == []
    finally:
        _cleanup("demo-empty")


def test_empty_project_has_zero_fitness(tmp_path):
    # No own modules at all -> empty selection, no moves, no crash.
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    spec = register_module_objective(
        "demo-noproj", lambda root, rel: _FakePlan({rel: "q\n"}),
        operator="demo_noproj", description="apply demo-noproj in {rel}")
    try:
        assert spec.fitness(str(tmp_path)) == 0.0
        assert spec.moves(str(tmp_path)) == []
    finally:
        _cleanup("demo-noproj")
