from __future__ import annotations

from app.engine.develop_registry import (
    ObjectiveSpec,
    discover,
    objective,
    register,
    registered_specs,
)


def test_discovered_objectives_are_available():
    # The three migrated objectives now live as self-registering modules under
    # app/execution/objectives/ — they must show up with no hub edit.
    from app.engine.objective_compiler import available_objectives
    avail = set(available_objectives())
    assert {"merge-isinstance", "collapse-startswith", "cover-gaps"} <= avail


def test_registry_holds_specs():
    specs = registered_specs()
    assert "merge-isinstance" in specs
    spec = specs["merge-isinstance"]
    assert isinstance(spec, ObjectiveSpec)
    assert callable(spec.fitness) and callable(spec.moves)


def test_discover_is_idempotent():
    a = discover()
    b = discover()
    assert a is b  # the import sweep runs once; same registry object


def test_builtins_win_name_clash():
    # A discovered spec must never override a built-in objective of the same name.
    from app.engine.objective_compiler import _OBJECTIVES, _objectives_map
    register(ObjectiveSpec("modernize", lambda p: 999.0, lambda p: []))
    try:
        table = _objectives_map()
        # The built-in modernize fitness is used, not the bogus 999 one.
        assert table["modernize"] is _OBJECTIVES["modernize"]
    finally:
        # Restore the registry to its discovered state for other tests.
        from app.engine import develop_registry
        develop_registry._REGISTRY.pop("modernize", None)


def test_decorator_registers():
    def _fit(project_root):
        return 0.0

    @objective("demo-noop", _fit)
    def _moves(project_root):
        return []

    try:
        assert "demo-noop" in registered_specs()
        spec = registered_specs()["demo-noop"]
        assert spec.fitness is _fit and spec.moves is _moves
    finally:
        from app.engine import develop_registry
        develop_registry._REGISTRY.pop("demo-noop", None)


def test_register_returns_spec():
    spec = ObjectiveSpec("demo-x", lambda p: 1.0, lambda p: [])
    try:
        assert register(spec) is spec
    finally:
        from app.engine import develop_registry
        develop_registry._REGISTRY.pop("demo-x", None)


def test_migrated_objective_still_compiles(tmp_path):
    # End-to-end: a discovered objective drives a real compile campaign.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def kind(x):\n"
        "    return isinstance(x, int) or isinstance(x, float)\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import kind\ndef test_k():\n    assert kind(1) and kind(1.0)\n"
        "    assert not kind('a')\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")

    from app.engine.objective_compiler import compile_objective
    result = compile_objective(str(tmp_path), objective="merge-isinstance",
                               apply=True, verify=False)
    assert result.steps  # the discovered objective produced a verified move
    assert "isinstance(x, (int, float))" in (tmp_path / "app" / "m.py").read_text()
