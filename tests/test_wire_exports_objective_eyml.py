"""wire-exports develop objective — auto-populate a package's public API surface.

Covers: objective registration/reachability + facet route; public-symbol
collection (defs/classes/assignments, ``_private`` and ``__all__`` skipped);
deterministic collision resolution (first sorted module wins, the later
collider is skipped, never guessed); sorted ``from .mod import Name`` +
``__all__`` rendering; the import oracle catching an unresolvable export
(rollback); already-wired byte-identical no-op + idempotence; refusal of
test/fixture packages; determinism across two runs; and the end-to-end gated
apply that lands a real ``__init__.py`` so ``from pkg import X`` works.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.export_wiring import (
    collect_package_exports,
    plan_init_text,
    public_symbols_of_module,
    render_init_source,
)
from app.execution.import_oracle import exports_resolve, package_dotted_name
from app.execution.objectives.wire_exports import plan_wire_exports


# --- registration / reachability ---------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "wire-exports" in set(available_objectives())


def test_objective_spec_is_callable_and_expensive():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["wire-exports"]
    assert callable(spec.fitness) and callable(spec.moves)
    # The fitness scan imports each candidate package in a subprocess — flagged
    # expensive so the fast plan/ascend board skips it (runnable explicitly).
    assert spec.expensive is True


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective("the public re-export surface to wire") == "wire-exports"


def test_facet_reachability_invariant_holds():
    # The facet map must reach exactly the available objectives (a standing
    # invariant); adding wire-exports to both sides keeps the equality.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


# --- public-symbol collection (pure AST) -------------------------------------

def test_collects_defs_classes_and_assignments():
    src = (
        "def alpha():\n    return 1\n\n"
        "async def beta():\n    return 2\n\n"
        "class Widget:\n    pass\n\n"
        "SHARED = 1\n"
        "TYPED: int = 2\n"
    )
    assert public_symbols_of_module(src) == ["alpha", "beta", "Widget", "SHARED", "TYPED"]


def test_skips_private_and_dunder_and_all():
    src = (
        "def _hidden():\n    return 0\n\n"
        "__all__ = ['x']\n"
        "__version__ = '1'\n"
        "def public():\n    return 1\n"
    )
    assert public_symbols_of_module(src) == ["public"]


def test_unparseable_module_yields_no_symbols():
    assert public_symbols_of_module("def (:\n") == []


def test_annassign_without_value_is_not_exported():
    # A bare annotation (`x: int`) binds nothing, so it is not a re-exportable name.
    assert public_symbols_of_module("x: int\n") == []


# --- collision resolution (deterministic, honest under-claim) ----------------

def _pkg(tmp_path: Path, files: dict[str, str], init: str = "") -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    for name, src in files.items():
        (pkg / name).write_text(src, encoding="utf-8")
    (pkg / "__init__.py").write_text(init, encoding="utf-8")
    return pkg


def test_collision_first_sorted_module_wins(tmp_path: Path):
    pkg = _pkg(tmp_path, {
        "aaa.py": "def SHARED():\n    return 1\n",
        "bbb.py": "def SHARED():\n    return 2\n",
    })
    plan = collect_package_exports(pkg, "")
    assert plan.exports["SHARED"] == "aaa"   # sorted-first module wins
    assert plan.skipped == ["SHARED"]        # the later collider is recorded, not guessed


def test_existing_init_binding_is_left_alone(tmp_path: Path):
    pkg = _pkg(tmp_path, {"aaa.py": "def already():\n    return 1\n"},
               init="from .aaa import already\n")
    plan = collect_package_exports(pkg, "from .aaa import already\n")
    assert "already" not in plan.exports  # the human already wired it


# --- rendering: sorted re-exports + sorted __all__ ---------------------------

def test_renders_sorted_imports_and_all(tmp_path: Path):
    pkg = _pkg(tmp_path, {
        "aaa.py": "class Widget:\n    pass\n\ndef alpha():\n    return 1\n",
        "bbb.py": "def beta():\n    return 2\n",
    })
    plan = collect_package_exports(pkg, "")
    out = render_init_source(plan, "")
    assert out == (
        "from .aaa import Widget, alpha\n"
        "from .bbb import beta\n"
        "\n"
        "__all__ = [\n"
        '    "Widget",\n'
        '    "alpha",\n'
        '    "beta",\n'
        "]\n"
    )


def test_render_none_when_nothing_to_export(tmp_path: Path):
    pkg = _pkg(tmp_path, {"aaa.py": "def _only_private():\n    return 0\n"})
    plan = collect_package_exports(pkg, "")
    assert render_init_source(plan, "") is None


# --- plan layer: full wire, no-op, refusal -----------------------------------

def test_plan_wires_public_symbols(tmp_path: Path):
    _pkg(tmp_path, {
        "aaa.py": "def alpha():\n    return 1\n\nclass Widget:\n    pass\n\n"
                  "def _hidden():\n    return 0\n\nSHARED = 1\n",
        "bbb.py": "def beta():\n    return 2\n\ndef SHARED():\n    return 9\n",
    })
    plan = plan_wire_exports(str(tmp_path), "pkg/__init__.py")
    text = plan.new_contents["pkg/__init__.py"]
    assert "from .aaa import SHARED, Widget, alpha" in text
    assert "from .bbb import beta" in text
    # _hidden is private; bbb.SHARED collides with aaa.SHARED -> excluded.
    assert "_hidden" not in text
    assert "from .bbb import SHARED" not in text
    assert text.count('"SHARED"') == 1


def test_plan_noop_when_already_wired(tmp_path: Path):
    # A package already fully exported -> byte-identical no-op (idempotent).
    init = (
        "from .aaa import alpha\n\n"
        "__all__ = [\n"
        '    "alpha",\n'
        "]\n"
    )
    _pkg(tmp_path, {"aaa.py": "def alpha():\n    return 1\n"}, init=init)
    plan = plan_wire_exports(str(tmp_path), "pkg/__init__.py")
    assert not plan.new_contents


def test_plan_is_idempotent_after_apply(tmp_path: Path):
    _pkg(tmp_path, {
        "aaa.py": "def alpha():\n    return 1\n",
        "bbb.py": "def beta():\n    return 2\n",
    })
    init_rel = "pkg/__init__.py"
    plan = plan_wire_exports(str(tmp_path), init_rel)
    (tmp_path / init_rel).write_text(plan.new_contents[init_rel], encoding="utf-8")
    again = plan_wire_exports(str(tmp_path), init_rel)
    assert not again.new_contents  # re-running lands nothing


def test_plan_refuses_test_package(tmp_path: Path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "helper.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (tests / "__init__.py").write_text("", encoding="utf-8")
    plan = plan_wire_exports(str(tmp_path), "tests/__init__.py")
    assert not plan.new_contents and not plan.blockers


def test_plan_noop_when_no_public_symbols(tmp_path: Path):
    _pkg(tmp_path, {"aaa.py": "def _p():\n    return 0\n"})
    plan = plan_wire_exports(str(tmp_path), "pkg/__init__.py")
    assert not plan.new_contents


# --- the import oracle: catch an unresolvable export -------------------------

def test_package_dotted_name():
    assert package_dotted_name("pkg/__init__.py") == "pkg"
    assert package_dotted_name("a/b/__init__.py") == "a.b"


def test_oracle_refuses_an_unresolvable_export(tmp_path: Path):
    # A module that raises at import time means `from pkg import gamma` can never
    # resolve -> the oracle returns False and the original file is restored.
    _pkg(tmp_path, {
        "bad.py": "raise RuntimeError('boom')\n\ndef gamma():\n    return 3\n",
    })
    candidate = "from .bad import gamma\n\n__all__ = [\n    \"gamma\",\n]\n"
    ok = exports_resolve(tmp_path, "pkg/__init__.py", candidate, ["gamma"])
    assert ok is False
    # side-effect-free: the original empty __init__ is restored.
    assert (tmp_path / "pkg" / "__init__.py").read_text() == ""


def test_oracle_passes_for_a_real_surface(tmp_path: Path):
    _pkg(tmp_path, {"aaa.py": "def alpha():\n    return 1\n"})
    candidate = "from .aaa import alpha\n\n__all__ = [\n    \"alpha\",\n]\n"
    assert exports_resolve(tmp_path, "pkg/__init__.py", candidate, ["alpha"]) is True
    assert (tmp_path / "pkg" / "__init__.py").read_text() == ""  # restored


def test_oracle_empty_expected_is_false(tmp_path: Path):
    _pkg(tmp_path, {"aaa.py": "def alpha():\n    return 1\n"})
    assert exports_resolve(tmp_path, "pkg/__init__.py", "", []) is False


def test_plan_refused_when_oracle_fails(tmp_path: Path):
    # End-to-end through the plan: a package whose only public symbol lives behind
    # an import-time crash is refused (no plan), original untouched.
    _pkg(tmp_path, {"bad.py": "raise RuntimeError('boom')\n\ndef gamma():\n    return 3\n"})
    plan = plan_wire_exports(str(tmp_path), "pkg/__init__.py")
    assert not plan.new_contents
    assert (tmp_path / "pkg" / "__init__.py").read_text() == ""


# --- determinism --------------------------------------------------------------

def test_plan_is_deterministic_across_two_runs(tmp_path: Path):
    _pkg(tmp_path, {
        "m1.py": "def zee():\n    return 1\n\nclass Aye:\n    pass\n",
        "m2.py": "def mid():\n    return 2\n",
    })
    a, _ = plan_init_text(str(tmp_path), "pkg/__init__.py")
    b, _ = plan_init_text(str(tmp_path), "pkg/__init__.py")
    assert a == b and a is not None
    all_block = a.split("__all__", 1)[1]
    assert all_block.index("Aye") < all_block.index("mid") < all_block.index("zee")


# --- end-to-end: gated apply lands a real __init__.py, imports work ----------

def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_end_to_end_lands_init_and_import_works(tmp_path: Path):
    import os
    import subprocess
    import sys

    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    pkg = tmp_path / "app" / "pkg"
    pkg.mkdir()
    (pkg / "aaa.py").write_text(
        "def alpha():\n    return 1\n\nclass Widget:\n    pass\n\n"
        "def _hidden():\n    return 0\n\nSHARED = 1\n", encoding="utf-8")
    (pkg / "bbb.py").write_text(
        "def beta():\n    return 2\n\ndef SHARED():\n    return 9\n", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="wire-exports",
                               apply=True, verify=True)
    assert result.steps and result.steps[0].verified is True

    text = (pkg / "__init__.py").read_text()
    assert "from .aaa import SHARED, Widget, alpha" in text
    assert "from .bbb import beta" in text
    assert "_hidden" not in text                    # private excluded
    assert "from .bbb import SHARED" not in text     # collided-second excluded

    # The headline proof: `from app.pkg import X` now resolves in a clean import.
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [sys.executable, "-c",
         "from app.pkg import SHARED, Widget, alpha, beta; "
         "assert SHARED == 1 and alpha() == 1 and beta() == 2; print('OK')"],
        cwd=str(tmp_path), capture_output=True, text=True, env=env)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stderr


def test_end_to_end_noop_on_already_wired(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    pkg = tmp_path / "app" / "pkg"
    pkg.mkdir()
    (pkg / "aaa.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    wired = (
        "from .aaa import alpha\n\n"
        "__all__ = [\n"
        '    "alpha",\n'
        "]\n"
    )
    (pkg / "__init__.py").write_text(wired, encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="wire-exports",
                               apply=True, verify=True)
    assert not result.steps  # nothing landed
    assert (pkg / "__init__.py").read_text() == wired  # byte-identical no-op
