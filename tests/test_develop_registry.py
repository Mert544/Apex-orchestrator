from __future__ import annotations

import pytest

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
    # Uses an existing manifest name so the register-time soundness lock passes;
    # the point of the test is the decorator MECHANICS (it registers the wrapped
    # moves fn under the given name/fitness), which are name-agnostic. Restored
    # (re-discovered) afterwards so the built-in fitness is not left overridden.
    def _fit(project_root):
        return 0.0

    @objective("sort-imports", _fit)
    def _moves(project_root):
        return []

    try:
        assert "sort-imports" in registered_specs()
        spec = registered_specs()["sort-imports"]
        assert spec.fitness is _fit and spec.moves is _moves
    finally:
        from app.engine import develop_registry
        develop_registry._REGISTRY.pop("sort-imports", None)
        develop_registry._DISCOVERED = False


def test_register_returns_spec():
    # Existing manifest name (the soundness lock passes); the assertion under test
    # is that register() RETURNS the spec it stored. Restored afterwards.
    spec = ObjectiveSpec("dedup", lambda p: 1.0, lambda p: [])
    try:
        assert register(spec) is spec
    finally:
        from app.engine import develop_registry
        develop_registry._REGISTRY.pop("dedup", None)
        develop_registry._DISCOVERED = False


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


# --- register-time soundness-manifest lock (autonomy trust-floor) ------------

def test_register_rejects_objective_absent_from_soundness_manifest():
    # A NEW objective with no declared soundness strategy must FAIL LOUDLY at
    # register (import) time, not skew silently until the late self-audit. The
    # name is genuinely absent from SOUNDNESS_STRATEGY, so this is the intended
    # trip — non-tautological.
    from app.engine.soundness_audit import SOUNDNESS_STRATEGY
    missing_name = "totally-unregistered-objective-zzz"
    assert missing_name not in SOUNDNESS_STRATEGY  # the precondition the trip needs
    with pytest.raises(ValueError, match=missing_name):
        register(ObjectiveSpec(missing_name, lambda p: 0.0, lambda p: []))
    # The failed registration left no partial entry behind.
    assert missing_name not in registered_specs()


def test_register_accepts_objective_present_in_soundness_manifest():
    # A name that IS in the manifest registers fine — the lock trips only on a
    # truly-undeclared objective. Use a manifest name not otherwise registered
    # here, and restore the registry afterwards.
    from app.engine.soundness_audit import SOUNDNESS_STRATEGY
    present_name = "modernize"
    assert present_name in SOUNDNESS_STRATEGY
    spec = ObjectiveSpec(present_name, lambda p: 1.0, lambda p: [])
    try:
        assert register(spec) is spec  # registers, returns the spec
        assert registered_specs()[present_name] is spec
    finally:
        from app.engine import develop_registry
        develop_registry._REGISTRY.pop(present_name, None)
        develop_registry._DISCOVERED = False  # re-discover to restore the built-in


def test_soundness_lock_does_not_break_import_or_objective_count():
    # The lock runs at import for every current objective; all 92 are already in
    # SOUNDNESS_STRATEGY (91 + java-final-parameter), so import must stay clean and
    # the count unchanged (no import breakage, no count-pin drift).
    from app.engine.objective_compiler import available_objectives
    from app.engine.soundness_audit import SOUNDNESS_STRATEGY
    names = list(available_objectives())
    assert len(names) == 92
    assert [n for n in names if n not in SOUNDNESS_STRATEGY] == []
