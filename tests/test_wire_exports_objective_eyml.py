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
    is_namespace_package,
    oracle_target,
    plan_init_text,
    public_symbols_of_module,
    render_init_source,
    rendered_all_names,
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
    # Impact-scoped gating: a wired __init__.py is verified against the tests that
    # IMPORT the changed package, not the full suite — so a work-in-progress repo's
    # baseline suite, legitimately RED for an UNRELATED reason, no longer vetoes a
    # VALID __init__.py whose every export the import oracle already proved resolves.
    assert spec.scope_verify is True


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


def test_existing_all_is_replaced_not_duplicated(tmp_path: Path):
    # REGRESSION: an __init__ that ALREADY declares a (curated) __all__ AND has a
    # new sibling export to wire must yield exactly ONE __all__ — the merged
    # superset — not the old one left dead above a freshly-appended second block.
    # (Found wiring an external package with a hand-curated __all__: Apex emitted a
    # duplicate __all__, the first clobbered by the second.)
    init = (
        "from .aaa import alpha\n\n"
        "__all__ = [\n"
        '    "alpha",\n'
        "]\n"
    )
    pkg = _pkg(tmp_path, {
        "aaa.py": "def alpha():\n    return 1\n",
        "bbb.py": "def beta():\n    return 2\n",  # a NEW export, not yet wired
    }, init=init)
    plan = collect_package_exports(pkg, init)
    out = render_init_source(plan, init)
    assert out is not None
    # Exactly one __all__ assignment — the duplicate is the bug.
    assert out.count("__all__ = [") == 1
    # The merged list is a superset: the curated name AND the new one, sorted.
    assert out == (
        "from .aaa import alpha\n"
        "\n"
        "from .bbb import beta\n"
        "\n"
        "__all__ = [\n"
        '    "alpha",\n'
        '    "beta",\n'
        "]\n"
    )
    # And the rendered candidate re-parses (valid syntax, single binding).
    import ast as _ast
    tree = _ast.parse(out)
    all_assigns = [
        n for n in tree.body
        if isinstance(n, _ast.Assign)
        and any(isinstance(t, _ast.Name) and t.id == "__all__" for t in n.targets)
    ]
    assert len(all_assigns) == 1


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


def test_rendered_all_excludes_protocol_dunders(tmp_path: Path):
    # A `__getattr__` bound in the existing __init__ is import machinery, not a
    # re-exportable attribute — it must NOT be folded into __all__ (where
    # `from pkg import *` would try and fail to resolve it).
    pkg = _pkg(tmp_path, {"aaa.py": "def alpha():\n    return 1\n"},
               init="def __getattr__(name):\n    raise AttributeError(name)\n")
    plan = collect_package_exports(pkg, "def __getattr__(name):\n    raise AttributeError(name)\n")
    names = rendered_all_names(plan, "def __getattr__(name):\n    raise AttributeError(name)\n")
    assert "alpha" in names
    assert "__getattr__" not in names  # protocol dunder excluded


def test_bare_imports_are_not_folded_into_all(tmp_path: Path):
    # The P1 over-claim: a package whose __init__ does the very common
    # `import os` / `import sys` / `from collections import OrderedDict` must NOT
    # re-export those implementation-detail imports. They resolve (so the oracle
    # would pass), but they are NOT the package's public surface — folding them in
    # would make `from pkg import *` leak os/sys/OrderedDict to API/doc tooling.
    init = "import os\nimport sys\nfrom collections import OrderedDict\n"
    pkg = _pkg(tmp_path, {
        "core.py": "def engine():\n    return 1\n",
        "io.py": "class Loader:\n    pass\n",
    }, init=init)
    plan = collect_package_exports(pkg, init)
    names = rendered_all_names(plan, init)
    # The sibling modules' real public symbols ARE present.
    assert "engine" in names and "Loader" in names
    # The bare imports are NOT — implementation detail, not public API.
    assert "os" not in names
    assert "sys" not in names
    assert "OrderedDict" not in names


def test_explicit_human_all_entry_is_honored_even_if_imported(tmp_path: Path):
    # If a human DELIBERATELY listed a name in a literal __all__ — even an imported
    # one like `os` — that is their declared public surface and must be preserved.
    # Only AUTO-folding of bare imports is wrong; an explicit choice is honored.
    init = (
        "import os\n"
        "import sys\n"
        "__all__ = [\n"
        '    "os",\n'
        "]\n"
    )
    pkg = _pkg(tmp_path, {"core.py": "def engine():\n    return 1\n"}, init=init)
    plan = collect_package_exports(pkg, init)
    names = rendered_all_names(plan, init)
    assert "os" in names      # human explicitly listed it — honored
    assert "sys" not in names  # never listed, never auto-folded
    assert "engine" in names   # newly-wired sibling export


def test_defs_classes_assignments_in_init_are_folded(tmp_path: Path):
    # A def/class/assignment defined DIRECTLY in __init__ IS the package's own
    # public surface, so it is still folded into __all__ (unlike a bare import).
    init = (
        "import os\n\n"
        "def helper():\n    return 1\n\n"
        "class Thing:\n    pass\n\n"
        "CONST = 5\n"
        "TYPED: int = 7\n"
    )
    pkg = _pkg(tmp_path, {"core.py": "def engine():\n    return 1\n"}, init=init)
    plan = collect_package_exports(pkg, init)
    names = rendered_all_names(plan, init)
    assert "helper" in names and "Thing" in names      # def + class folded
    assert "CONST" in names and "TYPED" in names        # assignment targets folded
    assert "engine" in names                            # sibling export wired
    assert "os" not in names                            # bare import excluded


def test_rendered_all_names_sorted_and_no_import_init_unchanged(tmp_path: Path):
    # Determinism: __all__ is sorted. And an __init__ with bare imports plus
    # sibling exports renders byte-IDENTICALLY to one with no imports at all —
    # because the imports contribute nothing to the public surface.
    with_imports = "import os\nimport sys\n"
    no_imports = ""
    files = {
        "core.py": "def zebra():\n    return 1\n\ndef alpha():\n    return 2\n",
        "io.py": "class Mid:\n    pass\n",
    }
    pkg_a = tmp_path / "a"
    pkg_a.mkdir()
    pkg_b = tmp_path / "b"
    pkg_b.mkdir()
    for name, src in files.items():
        (pkg_a / name).write_text(src, encoding="utf-8")
        (pkg_b / name).write_text(src, encoding="utf-8")
    (pkg_a / "__init__.py").write_text(with_imports, encoding="utf-8")
    (pkg_b / "__init__.py").write_text(no_imports, encoding="utf-8")

    plan_a = collect_package_exports(pkg_a, with_imports)
    names_a = rendered_all_names(plan_a, with_imports)
    assert names_a == sorted(names_a)                 # deterministic sorted order
    assert names_a == ["Mid", "alpha", "zebra"]

    # The __all__ FOLD set is identical whether or not bare imports are present.
    plan_b = collect_package_exports(pkg_b, no_imports)
    assert rendered_all_names(plan_b, no_imports) == names_a


def test_oracle_checks_folded_explicit_all_entry(tmp_path: Path):
    # The plan must feed the FULL emitted __all__ to the oracle, not just the NEW
    # exports. Here a human's EXPLICIT __all__ lists `Removed`, which is imported
    # then `del`'d, so it does NOT resolve as a package attribute. We honor the
    # explicit choice and fold `Removed` into __all__ -> the oracle (fed the full
    # list) catches the unresolvable name and REFUSES, landing nothing rather than
    # an __all__ whose `Removed` would break `from pkg import *`.
    init = (
        "from .gone import Removed\n"
        "del Removed\n"
        "__all__ = [\n"
        '    "Removed",\n'
        "]\n"
    )
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "aaa.py").write_text("def fresh():\n    return 1\n", encoding="utf-8")
    # `gone.py` defines Removed so the import line itself succeeds; the `del`
    # then unbinds it, so the package has no `Removed` attribute.
    (pkg / "gone.py").write_text("Removed = object()\n", encoding="utf-8")
    (pkg / "__init__.py").write_text(init, encoding="utf-8")

    # `Removed` is folded in (an explicit __all__ entry, honored), but unresolvable.
    plan = collect_package_exports(pkg, init)
    all_names = rendered_all_names(plan, init)
    assert "Removed" in all_names  # folded in (explicit human __all__ entry)

    result = plan_wire_exports(str(tmp_path), "pkg/__init__.py")
    assert not result.new_contents  # the oracle caught the unresolvable folded name
    assert (pkg / "__init__.py").read_text() == init  # untouched


def test_bare_del_import_is_not_folded_so_surface_still_wires(tmp_path: Path):
    # Counterpart to the explicit-__all__ case: when the SAME `del`'d name is just
    # a bare import (no explicit __all__), the fix means it is NEVER folded — so it
    # cannot poison __all__ at all. The package's real public surface (`fresh`)
    # still wires correctly, and the emitted __all__ holds only resolvable names.
    init = (
        "from .gone import Removed\n"
        "del Removed\n"
    )
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "aaa.py").write_text("def fresh():\n    return 1\n", encoding="utf-8")
    (pkg / "gone.py").write_text("Removed = object()\n", encoding="utf-8")
    (pkg / "__init__.py").write_text(init, encoding="utf-8")

    plan = collect_package_exports(pkg, init)
    all_names = rendered_all_names(plan, init)
    assert all_names == ["fresh"]      # Removed (bare import) never folded
    assert "Removed" not in all_names

    result = plan_wire_exports(str(tmp_path), "pkg/__init__.py")
    # The real surface wires (the oracle passes — no unresolvable folded name).
    assert result.new_contents
    landed = result.new_contents["pkg/__init__.py"]
    assert "from .aaa import fresh" in landed
    assert '"fresh"' in landed and '"Removed"' not in landed


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


# --- PEP 420 namespace packages (no __init__.py): refuse cleanly -------------
# DECISION: a package directory with public modules but NO __init__.py is a
# deliberate PEP 420 namespace-package portion. CREATING an __init__.py would
# convert it to a *regular* package and break namespace-portion merging across
# sys.path entries — a semantic change we cannot prove safe. The conservative,
# honest behavior is to REFUSE (no crash, no file created), never silently
# convert. (If we ever created one, the import oracle would still have to prove
# every name resolves; we choose not to, to preserve the namespace semantics.)

def _ns_pkg(tmp_path: Path, files: dict[str, str], name: str = "ns_pkg") -> Path:
    """A namespace-package dir: real modules, but deliberately NO __init__.py."""
    pkg = tmp_path / name
    pkg.mkdir()
    for fname, src in files.items():
        (pkg / fname).write_text(src, encoding="utf-8")
    return pkg


def test_is_namespace_package_detects_missing_init(tmp_path: Path):
    _ns_pkg(tmp_path, {"aaa.py": "def alpha():\n    return 1\n"})
    assert is_namespace_package(tmp_path, "ns_pkg") is True


def test_is_namespace_package_false_when_init_present(tmp_path: Path):
    # A regular package (has __init__.py) is NOT a namespace package.
    _pkg(tmp_path, {"aaa.py": "def alpha():\n    return 1\n"})
    assert is_namespace_package(tmp_path, "pkg") is False


def test_is_namespace_package_false_for_empty_or_missing_dir(tmp_path: Path):
    # A dir with no *.py modules is nothing to wire; a missing dir is not a package.
    (tmp_path / "empty").mkdir()
    assert is_namespace_package(tmp_path, "empty") is False
    assert is_namespace_package(tmp_path, "does_not_exist") is False


def test_plan_init_text_refuses_namespace_package(tmp_path: Path):
    # The headline safe behavior: a namespace package yields a clean refusal
    # (candidate None + a reason), NOT a fabricated __init__.py.
    _ns_pkg(tmp_path, {
        "aaa.py": "def alpha():\n    return 1\n",
        "bbb.py": "class Widget:\n    pass\n",
    })
    candidate, plan = plan_init_text(str(tmp_path), "ns_pkg/__init__.py")
    assert candidate is None
    assert plan.refused_reason is not None
    assert "namespace" in plan.refused_reason


def test_plan_wire_exports_refuses_namespace_package_no_file_created(tmp_path: Path):
    # End-to-end refusal: an empty plan AND the namespace package stays a
    # namespace package — no __init__.py is created on disk (semantics preserved).
    _ns_pkg(tmp_path, {"aaa.py": "def alpha():\n    return 1\n"})
    plan = plan_wire_exports(str(tmp_path), "ns_pkg/__init__.py")
    assert not plan.new_contents and not plan.blockers
    assert not (tmp_path / "ns_pkg" / "__init__.py").exists()  # never converted


def test_regular_package_still_wires_after_namespace_guard(tmp_path: Path):
    # Regression: the namespace guard keys ONLY off a MISSING __init__.py, so a
    # normal package (empty __init__.py present) wires exactly as before.
    _pkg(tmp_path, {"aaa.py": "def alpha():\n    return 1\n"})
    candidate, plan = plan_init_text(str(tmp_path), "pkg/__init__.py")
    assert candidate is not None
    assert plan.refused_reason is None
    assert "from .aaa import alpha" in candidate


# --- src/ layout: oracle imports under the REAL top-level path (pkg, not src.pkg)

def _src_project(tmp_path: Path, pyproject: str, files: dict[str, str],
                 init: str = "", pkg_name: str = "pkg") -> Path:
    """A src/-layout project: pyproject declares the root, package lives at
    src/<pkg_name>/ with an existing (possibly empty) __init__.py."""
    (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    pkg = tmp_path / "src" / pkg_name
    pkg.mkdir(parents=True)
    for fname, src in files.items():
        (pkg / fname).write_text(src, encoding="utf-8")
    (pkg / "__init__.py").write_text(init, encoding="utf-8")
    return pkg


_PYTEST_SRC = "[tool.pytest.ini_options]\npythonpath = [\"src\"]\n"
_SETUPTOOLS_SRC = "[tool.setuptools]\npackage-dir = {\"\" = \"src\"}\n"


def test_oracle_target_strips_src_root():
    # The import oracle must import src/pkg as `pkg` with src/ on the path, not
    # `src.pkg` rooted at the project. oracle_target encodes exactly that.
    root, init_rel, dotted = oracle_target("/proj", "src/pkg/__init__.py")
    assert root == Path("/proj/src")
    assert init_rel == "pkg/__init__.py"
    assert dotted == "pkg"
    # And package_dotted_name on the stripped init_rel agrees (the oracle derives
    # the dotted name from init_rel, so the stripping alone fixes the import path).
    assert package_dotted_name(init_rel) == "pkg"


def test_oracle_target_identity_for_normal_layout():
    # No src/, no declared root -> identity: byte-identical to the old behavior.
    assert oracle_target("/proj", "pkg/__init__.py") == (
        Path("/proj"), "pkg/__init__.py", "pkg")
    assert oracle_target("/proj", "app/sub/__init__.py") == (
        Path("/proj"), "app/sub/__init__.py", "app.sub")


def test_oracle_target_keeps_subpackage_path_under_src():
    # A sub-package under src/ keeps its full dotted path below the stripped root.
    assert oracle_target("/proj", "src/pkg/sub/__init__.py") == (
        Path("/proj/src"), "pkg/sub/__init__.py", "pkg.sub")


def test_oracle_target_does_not_strip_package_named_src():
    # A regular package literally named `src` (src/__init__.py) is NOT a source
    # root to strip — stripping would empty its dotted path. Keep it as identity.
    assert oracle_target("/proj", "src/__init__.py") == (
        Path("/proj"), "src/__init__.py", "src")


def test_oracle_target_honors_pyproject_declared_root(tmp_path: Path):
    # A custom setuptools root (`lib`) declared in pyproject is stripped too.
    (tmp_path / "pyproject.toml").write_text(
        "[tool.setuptools]\npackage-dir = {\"\" = \"lib\"}\n", encoding="utf-8")
    root, init_rel, dotted = oracle_target(str(tmp_path), "lib/pkg/__init__.py")
    assert root == tmp_path / "lib"
    assert init_rel == "pkg/__init__.py" and dotted == "pkg"


def test_src_layout_wires_with_absolute_sibling_import(tmp_path: Path):
    # The real-world break: a src/ package whose module does the ABSOLUTE
    # top-level import `from pkg.helper import base` (normal in src/ layouts,
    # since `pkg` is the installed name). Under the WRONG `src.pkg` path that
    # absolute import fails and the oracle wrongly refuses; under the corrected
    # `pkg` path (src/ on sys.path) it resolves and the surface wires.
    _src_project(tmp_path, _PYTEST_SRC, {
        "aaa.py": "from pkg.helper import base\n\ndef alpha():\n    return base() + 1\n",
        "helper.py": "def base():\n    return 10\n",
    })
    plan = plan_wire_exports(str(tmp_path), "src/pkg/__init__.py")
    landed = plan.new_contents["src/pkg/__init__.py"]
    assert "from .aaa import alpha" in landed
    assert "from .helper import base" in landed
    assert '"alpha"' in landed and '"base"' in landed


def test_src_layout_oracle_resolves_under_pkg_not_src_pkg(tmp_path: Path):
    # Direct oracle contrast at the layout boundary: the SAME candidate that
    # resolves under the corrected `pkg` path (src/ on the path) is REFUSED under
    # the naive `src.pkg` path — proving the oracle validates the right module.
    _src_project(tmp_path, _PYTEST_SRC, {
        "aaa.py": "from pkg.helper import base\n\ndef alpha():\n    return base()\n",
        "helper.py": "def base():\n    return 10\n",
    })
    candidate = (
        "from .aaa import alpha\nfrom .helper import base\n\n"
        "__all__ = [\n    \"alpha\",\n    \"base\",\n]\n"
    )
    expected = ["alpha", "base"]

    # WRONG: project root on the path, dotted `src.pkg` -> the absolute
    # `from pkg.helper` inside aaa.py cannot resolve -> oracle refuses.
    assert exports_resolve(str(tmp_path), "src/pkg/__init__.py",
                           candidate, expected) is False
    # RIGHT: the oracle_target-resolved root/init_rel -> imports as `pkg`.
    o_root, o_init, _ = oracle_target(str(tmp_path), "src/pkg/__init__.py")
    assert exports_resolve(o_root, o_init, candidate, expected) is True
    # Side-effect-free: the empty __init__.py is restored either way.
    assert (tmp_path / "src" / "pkg" / "__init__.py").read_text() == ""


def test_src_layout_via_setuptools_package_dir(tmp_path: Path):
    # The setuptools `package-dir={"":"src"}` declaration is honored the same as
    # pytest pythonpath — the src/ root is stripped and the package wires.
    _src_project(tmp_path, _SETUPTOOLS_SRC, {
        "aaa.py": "from pkg.helper import base\n\ndef alpha():\n    return base()\n",
        "helper.py": "def base():\n    return 1\n",
    })
    plan = plan_wire_exports(str(tmp_path), "src/pkg/__init__.py")
    assert plan.new_contents
    assert "from .aaa import alpha" in plan.new_contents["src/pkg/__init__.py"]


def test_src_layout_wrong_path_name_is_refused(tmp_path: Path):
    # never-fake-green at the layout boundary: a __all__ name that does NOT
    # resolve even under the corrected `pkg` path is still refused — the fix only
    # changes WHICH module is imported, never relaxes the resolve check.
    _src_project(tmp_path, _PYTEST_SRC, {"aaa.py": "def alpha():\n    return 1\n"})
    o_root, o_init, _ = oracle_target(str(tmp_path), "src/pkg/__init__.py")
    candidate = (
        "from .aaa import alpha\n\n__all__ = [\n    \"alpha\",\n    \"ghost\",\n]\n"
    )
    # `ghost` is nowhere defined -> unresolvable -> oracle refuses the candidate.
    assert exports_resolve(o_root, o_init, candidate, ["alpha", "ghost"]) is False


def test_src_layout_import_failure_still_refuses(tmp_path: Path):
    # Determinism/honesty unchanged on src/: a module that raises at import time
    # makes its export unresolvable, so the oracle declines and nothing lands —
    # exactly as on a normal layout.
    _src_project(tmp_path, _PYTEST_SRC, {
        "bad.py": "raise RuntimeError('boom')\n\ndef gamma():\n    return 3\n",
    })
    plan = plan_wire_exports(str(tmp_path), "src/pkg/__init__.py")
    assert not plan.new_contents
    assert (tmp_path / "src" / "pkg" / "__init__.py").read_text() == ""


def test_src_layout_plan_is_deterministic(tmp_path: Path):
    # Same src/ package -> byte-identical candidate across two runs (no clock/random).
    _src_project(tmp_path, _PYTEST_SRC, {
        "m1.py": "def zee():\n    return 1\n\nclass Aye:\n    pass\n",
        "m2.py": "def mid():\n    return 2\n",
    })
    a = plan_wire_exports(str(tmp_path), "src/pkg/__init__.py").new_contents
    b = plan_wire_exports(str(tmp_path), "src/pkg/__init__.py").new_contents
    assert a == b and a
    block = a["src/pkg/__init__.py"].split("__all__", 1)[1]
    assert block.index("Aye") < block.index("mid") < block.index("zee")


# --- regression guard: the normal (__init__-present, non-src) case is unchanged

def test_normal_case_candidate_is_byte_identical(tmp_path: Path):
    # The exact bytes the engine emitted before this change for a plain package,
    # pinned so the namespace + src/ work cannot perturb the common path.
    _pkg(tmp_path, {
        "aaa.py": "class Widget:\n    pass\n\ndef alpha():\n    return 1\n",
        "bbb.py": "def beta():\n    return 2\n",
    })
    candidate, _ = plan_init_text(str(tmp_path), "pkg/__init__.py")
    assert candidate == (
        "from .aaa import Widget, alpha\n"
        "from .bbb import beta\n"
        "\n"
        "__all__ = [\n"
        '    "Widget",\n'
        '    "alpha",\n'
        '    "beta",\n'
        "]\n"
    )


def test_normal_layout_oracle_call_is_identity(tmp_path: Path):
    # The oracle plumbing for a non-src package is the identity, so a normal
    # package still wires and resolves exactly as before the layout work.
    _pkg(tmp_path, {"aaa.py": "def alpha():\n    return 1\n"})
    assert oracle_target(str(tmp_path), "pkg/__init__.py") == (
        tmp_path, "pkg/__init__.py", "pkg")
    plan = plan_wire_exports(str(tmp_path), "pkg/__init__.py")
    assert "from .aaa import alpha" in plan.new_contents["pkg/__init__.py"]


def test_end_to_end_lands_init_in_src_layout_and_import_works(tmp_path: Path):
    # The headline src/ proof: a full gated apply lands a real __init__.py under
    # src/pkg/ and `from pkg import X` resolves in a clean import with src/ on the
    # path (pytest pythonpath=src), even with an absolute sibling import inside.
    import os
    import subprocess
    import sys

    from app.engine.objective_compiler import compile_objective

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n\n"
        "[tool.pytest.ini_options]\npythonpath = [\"src\"]\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    pkg = tmp_path / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "aaa.py").write_text(
        "from pkg.helper import base\n\ndef alpha():\n    return base() + 1\n",
        encoding="utf-8")
    (pkg / "helper.py").write_text("def base():\n    return 10\n", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="wire-exports",
                               apply=True, verify=True)
    assert result.steps and result.steps[0].verified is True

    text = (pkg / "__init__.py").read_text()
    assert "from .aaa import alpha" in text
    assert "from .helper import base" in text

    # `from pkg import X` resolves with src/ on the path — exactly how a real
    # caller / pytest pythonpath=src imports the package (NOT src.pkg).
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [sys.executable, "-c",
         "from pkg import alpha, base; "
         "assert base() == 10 and alpha() == 11; print('OK')"],
        cwd=str(tmp_path / "src"), capture_output=True, text=True, env=env)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stderr


# --- value-leak fix: land a VALID __init__.py on a RED baseline (impact-scoped) -
# The buyer demonstration: a work-in-progress repo whose FULL suite is red for an
# UNRELATED reason (an unsynthesizable `registry.capital_of` stub) refused to land
# a correct `toolkit/__init__.py`, even though wire-exports' import oracle had
# already proved every re-exported name resolves AND toolkit's own tests pass.
# scope_verify=True gates wire-exports against the tests that IMPORT the changed
# package, so the unrelated red module — which does not import toolkit — no longer
# vetoes the valid wiring. The full suite stays the commit-time backstop.

def _red_baseline_two_package_project(tmp_path: Path) -> Path:
    """A WIP repo: a wireable `toolkit/` package (sibling public symbols, empty
    __init__.py, its OWN passing test importing `from toolkit import ...`) PLUS an
    UNRELATED `registry.py` whose test FAILS — keeping the FULL suite RED. The
    failing test does NOT import toolkit, so it is not in toolkit's impacted set."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='wip'\nversion='0'\n", encoding="utf-8")
    toolkit = tmp_path / "toolkit"
    toolkit.mkdir()
    (toolkit / "shapes.py").write_text(
        "def area(side):\n    return side * side\n", encoding="utf-8")
    (toolkit / "colors.py").write_text(
        "def mix(a, b):\n    return a + b\n", encoding="utf-8")
    (toolkit / "__init__.py").write_text("", encoding="utf-8")

    # The unrelated, unsynthesizable module: a function that raises, and a test
    # that asserts a real return value — so the full suite is legitimately RED and
    # stays RED (no synthesizer can fill it). It imports ONLY `registry`.
    (tmp_path / "registry.py").write_text(
        "def capital_of(country):\n"
        "    raise NotImplementedError\n", encoding="utf-8")

    tests = tmp_path / "tests"
    tests.mkdir()
    # toolkit's OWN test — imports the wired PACKAGE surface (`from toolkit import
    # ...`), so it COVERS `toolkit/__init__.py` (the impact scope) and passes once
    # the package is wired. This is the realistic buyer test: it expects the public
    # API the package is supposed to re-export.
    (tests / "test_toolkit.py").write_text(
        "from toolkit import area, mix\n\n"
        "def test_area():\n    assert area(3) == 9\n\n"
        "def test_mix():\n    assert mix(2, 3) == 5\n", encoding="utf-8")
    # The UNRELATED red test — imports only `registry`, never toolkit.
    (tests / "test_registry.py").write_text(
        "from registry import capital_of\n\n"
        "def test_capital():\n    assert capital_of('france') == 'paris'\n",
        encoding="utf-8")
    return tmp_path


def _full_suite_is_red(root: Path) -> bool:
    import os
    import subprocess
    import sys

    env = {**os.environ,
           "PYTHONPATH": str(root) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=str(root), capture_output=True, text=True, env=env)
    return proc.returncode != 0


def test_red_baseline_lands_init_under_impact_scope(tmp_path: Path):
    # The headline value-leak proof: on a RED baseline, wire-exports now LANDS a
    # verified `toolkit/__init__.py` because impact-scoping runs toolkit's own
    # (passing) importing tests, NOT the unrelated red registry test.
    from app.engine.objective_compiler import compile_objective

    root = _red_baseline_two_package_project(tmp_path)
    # Precondition: the FULL suite is genuinely RED (the unrelated stub fails).
    assert _full_suite_is_red(root)

    result = compile_objective(str(root), objective="wire-exports",
                               apply=True, verify=True)

    # The valid __init__.py LANDED and was VERIFIED (its impacted tests passed),
    # despite the red baseline — the change was NOT rolled back.
    assert result.steps and result.steps[0].verified is True
    text = (root / "toolkit" / "__init__.py").read_text()
    assert "from .shapes import area" in text
    assert "from .colors import mix" in text
    assert '"area"' in text and '"mix"' in text

    # The unrelated red test STAYS red — it was never touched, and the suite is
    # still red for the same pre-existing reason (no fake-green of the whole suite).
    assert _full_suite_is_red(root)
    assert (root / "registry.py").read_text() == (
        "def capital_of(country):\n    raise NotImplementedError\n")


def test_red_baseline_vetoes_under_full_suite_path(tmp_path: Path):
    # Contrast: the SAME landed wiring, gated by the FULL suite (impact_scope off),
    # IS rolled back by the unrelated red test — exactly the value leak the
    # scope_verify flag fixes. Proves the flag is load-bearing, not incidental.
    from app.execution.cross_file_rename import apply_rename
    from app.execution.objectives.wire_exports import plan_wire_exports

    root = _red_baseline_two_package_project(tmp_path)
    plan = plan_wire_exports(str(root), "toolkit/__init__.py")
    assert plan.new_contents  # the oracle passed — a valid candidate exists

    # Full-suite gate (impact_scope=False): the unrelated red registry test fails
    # the suite, so the correct __init__.py is rolled back — the leak.
    res = apply_rename(str(root), plan, verify=True, impact_scope=False)
    assert res.get("applied") is False
    assert res.get("rolled_back") is True
    assert (root / "toolkit" / "__init__.py").read_text() == ""  # restored

    # Impact-scoped gate (impact_scope=True): the SAME plan LANDS, verified by
    # toolkit's own passing tests.
    plan2 = plan_wire_exports(str(root), "toolkit/__init__.py")
    res2 = apply_rename(str(root), plan2, verify=True, impact_scope=True)
    assert res2.get("applied") is True and res2.get("verified") is True
    assert "from .shapes import area" in (root / "toolkit" / "__init__.py").read_text()


def test_green_baseline_behavior_unchanged(tmp_path: Path):
    # Regression: on a GREEN-baseline project the impact-scoped flag changes
    # nothing observable — wire-exports lands the same verified __init__.py.
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)  # all-green suite (test_ok passes)
    pkg = tmp_path / "app" / "pkg"
    pkg.mkdir()
    (pkg / "aaa.py").write_text(
        "def alpha():\n    return 1\n\nclass Widget:\n    pass\n", encoding="utf-8")
    (pkg / "bbb.py").write_text("def beta():\n    return 2\n", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="wire-exports",
                               apply=True, verify=True)
    assert result.steps and result.steps[0].verified is True
    text = (pkg / "__init__.py").read_text()
    assert "from .aaa import Widget, alpha" in text
    assert "from .bbb import beta" in text


def test_oracle_still_refuses_unresolvable_export_under_impact_scope(tmp_path: Path):
    # never-fake-green: impact-scoping is ADDITIVE to the import oracle, not a
    # relaxation. A package whose only public symbol lives behind an import-time
    # crash never produces a candidate (the oracle refuses BEFORE any gate), so
    # nothing lands — even on a red baseline and even under scope_verify.
    from app.engine.objective_compiler import compile_objective

    root = _red_baseline_two_package_project(tmp_path)
    # Replace a toolkit module with one that crashes at import — `area` cannot
    # resolve, so the oracle (subprocess, suite-independent) refuses the candidate.
    (root / "toolkit" / "shapes.py").write_text(
        "raise RuntimeError('boom')\n\ndef area(side):\n    return side\n",
        encoding="utf-8")
    # Remove toolkit's test that would import the crashing module (so the failure
    # is the ORACLE's, not a test-collection error) — colors still has a surface.
    (root / "tests" / "test_toolkit.py").write_text(
        "from toolkit.colors import mix\n\n"
        "def test_mix():\n    assert mix(2, 3) == 5\n", encoding="utf-8")

    result = compile_objective(str(root), objective="wire-exports",
                               apply=True, verify=True)
    text = (root / "toolkit" / "__init__.py").read_text()
    # The crashing `area` is never re-exported (oracle refused that name); the
    # __init__ holds no `from .shapes import area`. Either nothing landed, or only
    # the resolvable `colors` surface — but never the unresolvable `area`.
    assert "from .shapes import area" not in text
    if result.steps:
        assert "from .colors import mix" in text and '"area"' not in text


def test_red_baseline_apply_is_deterministic(tmp_path: Path):
    # Determinism: two independent red-baseline projects yield byte-identical
    # landed __init__.py (no clock/random in scoring or rendering).
    from app.engine.objective_compiler import compile_objective

    root_a = _red_baseline_two_package_project(tmp_path / "a")
    root_b = _red_baseline_two_package_project(tmp_path / "b")
    compile_objective(str(root_a), objective="wire-exports", apply=True, verify=True)
    compile_objective(str(root_b), objective="wire-exports", apply=True, verify=True)
    a = (root_a / "toolkit" / "__init__.py").read_text()
    b = (root_b / "toolkit" / "__init__.py").read_text()
    assert a == b and "from .shapes import area" in a
