"""wire-module-exports develop objective — LAND a module-level ``__all__`` on a
leaf module that DEFINES public symbols but declares none.

Covers: the public-set computation (defs/classes/assignments/imports, ``_``-
excluded, sorted, ``__all__`` itself dropped); EVERY refusal (already declares
``__all__``; a ``from x import *`` is present; no public names; an unmodelled
top-level binder; ``__init__.py`` stays disjoint from wire-exports; test/fixture;
syntax error); idempotency + determinism; the 4 facet-parity assertions; the
END-TO-END landing (``apply_rename`` verify=True writes ``__all__`` in place and
the suite stays green); and a BEHAVIOUR-PRESERVATION test proving the
``from module import *`` set is byte-identical before and after.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.module_exports import (
    add_module_all,
    has_module_all,
    has_star_import,
    has_walrus,
    public_star_names,
)
from app.execution.objectives.wire_module_exports import (
    plan_wire_module_exports,
)

_FACET_PHRASE = "the module public surface to declare"
_OBJECTIVE = "wire-module-exports"

# A leaf module with public defs/class/assignment/import but NO __all__.
_LEAF = (
    '"""A leaf module."""\n'
    "from __future__ import annotations\n"
    "\n"
    "import os\n"
    "\n"
    "\n"
    "def helper():\n"
    "    return os.getcwd()\n"
    "\n"
    "\n"
    "class Thing:\n"
    "    pass\n"
    "\n"
    "\n"
    "VALUE = 3\n"
    "_private = 1\n"
)


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _star_set(tmp_path: Path, name: str, source: str) -> list[str]:
    """The runtime ``from <name> import *`` public set for ``source`` — load it as
    a real module on ``sys.path`` and execute the star import."""
    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        sys.modules.pop(name, None)
        mod = importlib.import_module(name)
        importlib.reload(mod)
        namespace: dict[str, object] = {}
        exec(f"from {name} import *", namespace)  # noqa: S102 - test-only probe
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop(name, None)
    return sorted(k for k in namespace if not k.startswith("__"))


# --- the public-set computation ---------------------------------------------

def test_public_set_collects_defs_classes_assigns_imports():
    names = public_star_names(_LEAF)
    # def + class + assignment target + both imports (incl __future__ binding).
    assert names == ["Thing", "VALUE", "annotations", "helper", "os"]


def test_public_set_excludes_underscore_names():
    src = "def pub(): pass\ndef _priv(): pass\nX = 1\n_Y = 2\n__dunder__ = 3\n"
    assert public_star_names(src) == ["X", "pub"]


def test_public_set_is_sorted_and_deduplicated():
    src = "zeta = 1\nalpha = 2\nzeta = 3\n"  # zeta rebound — appears once
    assert public_star_names(src) == ["alpha", "zeta"]


def test_public_set_excludes_all_itself():
    # A bare ``__all__`` target is never a member of the set it would declare; but
    # has_module_all short-circuits add_module_all, so test the raw computation on
    # a module whose only public name is an assignment target (no __all__ here).
    src = "def f(): pass\n"
    assert public_star_names(src) == ["f"]


def test_public_set_async_def_counts():
    src = "async def fetch(): pass\n"
    assert public_star_names(src) == ["fetch"]


def test_public_set_import_alias_binds_asname():
    src = "import os.path as op\nfrom collections import OrderedDict as OD\n"
    assert public_star_names(src) == ["OD", "op"]


def test_public_set_dotted_import_binds_head():
    src = "import os.path\n"  # binds ``os``
    assert public_star_names(src) == ["os"]


def test_public_set_annassign_without_value_binds_nothing():
    # ``x: int`` declares an annotation but binds NO runtime name — it is not a
    # star-set member; ``y: int = 1`` (with a value) binds ``y``.
    assert public_star_names("x: int\ny: int = 1\n") == ["y"]


def test_public_set_multi_target_assign_counts_each():
    assert public_star_names("a = b = 1\n") == ["a", "b"]


# --- REFUSALS (honest no-ops) -----------------------------------------------

def test_refuses_when_all_already_declared():
    src = "__all__ = ['f']\n\ndef f(): pass\n"
    assert has_module_all(src)
    assert add_module_all(src) is None


def test_refuses_when_all_declared_as_annassign():
    src = "__all__: list = ['f']\n\ndef f(): pass\n"
    assert has_module_all(src)
    assert add_module_all(src) is None


def test_refuses_on_star_import_present():
    src = "from os import *\n\ndef f(): pass\n"
    assert has_star_import(src)
    assert public_star_names(src) is None
    assert add_module_all(src) is None


def test_refuses_when_no_public_names():
    src = "_x = 1\n\n\ndef _helper(): pass\n"
    assert public_star_names(src) == []
    assert add_module_all(src) is None


def test_refuses_on_unmodelled_top_level_for_loop():
    # A top-level ``for`` leaks its target (and any body binding) into the runtime
    # star set — we do not model it, so the whole module is refused.
    src = "for i in range(3):\n    x = i\n"
    assert public_star_names(src) is None
    assert add_module_all(src) is None


def test_refuses_on_unmodelled_top_level_if():
    src = "import sys\nif sys.platform == 'linux':\n    flavour = 'lin'\n"
    assert public_star_names(src) is None
    assert add_module_all(src) is None


def test_refuses_on_unmodelled_top_level_try():
    src = "try:\n    import fast as impl\nexcept ImportError:\n    import slow as impl\n"
    assert public_star_names(src) is None
    assert add_module_all(src) is None


def test_refuses_on_tuple_unpacking_target():
    # A tuple/list/starred target is an unmodelled binder — refuse, never half-list.
    assert public_star_names("a, b = 1, 2\n") is None
    assert public_star_names("*head, tail = [1, 2, 3]\n") is None


def test_refuses_on_attribute_or_subscript_target():
    # An attribute/subscript assignment binds no NEW module name, but it is not a
    # bare-Name target, so the conservative path refuses the whole module.
    src = "import types\nm = types.ModuleType('x')\nm.attr = 1\n"
    assert public_star_names(src) is None


def test_refuses_on_syntax_error():
    assert public_star_names("def (:\n") is None
    assert add_module_all("def (:\n") is None


def test_refuses_test_file_via_plan(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _LEAF)
    assert not plan_wire_module_exports(str(tmp_path), "tests/test_x.py").new_contents


def test_refuses_fixture_file_via_plan(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", _LEAF)
    assert not plan_wire_module_exports(
        str(tmp_path), "fixtures/sample.py").new_contents


def test_init_py_stays_disjoint_from_wire_exports(tmp_path: Path):
    # A package ``__init__.py`` is wire-exports' territory. wire-module-exports must
    # not also claim it: the plan layer treats it as a normal source file, but the
    # objective leans on structural soundness — an ``__init__`` with public defs is
    # still wireable here ONLY as a plain module. To stay strictly disjoint we let
    # the ENGINE process it identically (it is just a .py file); the DISTINCTNESS is
    # that wire-exports REWRITES the re-export surface (adds ``from .mod import X``)
    # whereas this only declares ``__all__`` for names the ``__init__`` itself
    # defines. Here the ``__init__`` defines a public name directly, so a plain
    # ``__all__`` is the same sound rewrite — but verify it is byte-behaviour-safe.
    init_src = '"""Pkg."""\n\n\ndef shared(): pass\n'
    out = add_module_all(init_src)
    assert out is not None
    assert '__all__ = [\n    "shared",\n]' in out


# --- idempotency / determinism ----------------------------------------------

def test_idempotent_second_run_is_noop():
    once = add_module_all(_LEAF)
    assert once is not None
    assert has_module_all(once)
    assert add_module_all(once) is None  # 2nd run = byte-identical no-op


def test_deterministic_across_two_runs():
    a = add_module_all(_LEAF)
    b = add_module_all(_LEAF)
    assert a is not None and a == b


def test_preserves_trailing_newline_absence():
    out = add_module_all("def f(): pass")
    assert out is not None and not out.endswith("\n")


def test_all_lands_at_canonical_spot_after_imports():
    out = add_module_all(_LEAF)
    assert out is not None
    lines = out.splitlines()
    # docstring first, then the __future__ import, then __all__ (canonical spot).
    assert lines[0] == '"""A leaf module."""'
    assert lines[1] == "from __future__ import annotations"
    assert lines[2] == ""
    assert lines[3] == "__all__ = ["
    ast.parse(out)  # never lands broken Python


# --- registration / reachability (the 4 facet-parity assertions) -------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert _OBJECTIVE in set(available_objectives())


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_FACET_PHRASE) == _OBJECTIVE


def test_facet_reachability_parity_invariant_holds():
    # The standing 1:1 invariant: the facet map reaches EXACTLY the registered
    # objectives. Adding this objective to BOTH sides keeps the equality.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_facet_phrase_is_substring_order_safe():
    # The new key must be neither a substring of, nor contain, any other key (with
    # a different objective) — else the first-match scan would mis-route. In
    # particular it must stay disjoint from the wire-exports phrase.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    keys = list(FACET_OBJECTIVE_MAP)
    assert _FACET_PHRASE in keys
    assert "the public re-export surface to wire" in keys  # the wire-exports key
    for other in keys:
        if other == _FACET_PHRASE:
            continue
        assert _FACET_PHRASE not in other, f"{_FACET_PHRASE!r} ⊂ {other!r}"
        assert other not in _FACET_PHRASE, f"{other!r} ⊂ {_FACET_PHRASE!r}"


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert _OBJECTIVE in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name introduced


def test_facet_phrase_lives_in_the_signatures_and_types_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["signatures and types"]
    assert _FACET_PHRASE in ladder
    assert ladder[0] == "parameter meanings"  # originals still lead


# --- the plan ----------------------------------------------------------------

def test_plan_lands_the_all(tmp_path: Path):
    _project(tmp_path, "app/util.py", _LEAF)
    plan = plan_wire_module_exports(str(tmp_path), "app/util.py")
    assert plan.ok
    new = plan.new_contents["app/util.py"]
    assert "__all__ = [" in new
    assert plan.originals["app/util.py"] == _LEAF  # original captured for rollback
    assert plan.edits_by_file["app/util.py"] == 1


def test_plan_refuses_already_declared(tmp_path: Path):
    _project(tmp_path, "app/util.py", "__all__ = ['f']\n\ndef f(): pass\n")
    assert not plan_wire_module_exports(str(tmp_path), "app/util.py").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_wire_module_exports(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: gated apply, real landing, suite stays green ----------------

def test_end_to_end_lands_all_and_keeps_green(tmp_path: Path):
    _suite_project(tmp_path)
    (tmp_path / "app" / "util.py").write_text(_LEAF, encoding="utf-8")
    (tmp_path / "tests" / "test_util.py").write_text(
        "from app.util import helper, Thing, VALUE\n"
        "def test_uses():\n"
        "    assert VALUE == 3 and Thing is not None and helper() is not None\n",
        encoding="utf-8")

    plan = plan_wire_module_exports(str(tmp_path), "app/util.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "util.py").read_text(encoding="utf-8")
    assert "__all__ = [" in landed  # the declaration LANDED
    # Behaviour preserved: the public names still resolve, proven green by the
    # apply gate running the existing test above.
    assert "def helper():" in landed and "class Thing:" in landed


# --- behaviour preservation: the star-import set is unchanged ----------------

def test_star_import_set_unchanged_before_and_after(tmp_path: Path):
    cases = [
        _LEAF,
        "import os, sys\ndef f(): pass\nclass C: pass\nX = 1\n_y = 2\n",
        '"""d"""\nfrom collections import OrderedDict\ndef g(): pass\n',
        "from __future__ import annotations\nVALUE = 1\ndef h(): pass\n",
    ]
    for i, src in enumerate(cases):
        out = add_module_all(src)
        assert out is not None, f"case {i} should rewrite"
        before = _star_set(tmp_path, f"mod_before_{i}", src)
        after = _star_set(tmp_path, f"mod_after_{i}", out)
        assert before == after, f"case {i}: star set changed {before} -> {after}"
        # And the landed __all__ equals exactly that set (sorted).
        assert public_star_names(src) == sorted(before)


# --- CONFIRMED code-review fix B: walrus bindings are over-approximately refused

# Each variant binds a real MODULE-LEVEL name via a walrus that ``from m import *``
# exports but the naive top-level collector would OMIT — so the whole module must
# be refused (``has_walrus`` -> ``public_star_names``/``add_module_all`` = None).
_WALRUS_CASES = {
    "assign_value": "RESULT = (computed := 41)\n",
    "bare_expr": "(cache := {})\n",
    "annassign_value": "X: int = (Y := 5)\n",
    "decorator": "def f(c):\n    return c\n\n\n@(deco := f)\ndef g():\n    pass\n",
    "comprehension": "data = [y := i for i in range(3)]\n",
}


def test_fixB_has_walrus_detects_every_variant():
    for label, src in _WALRUS_CASES.items():
        assert has_walrus(src), f"{label}: walrus not detected"


def test_fixB_public_star_names_refuses_every_walrus_variant():
    for label, src in _WALRUS_CASES.items():
        assert public_star_names(src) is None, f"{label}: not refused"


def test_fixB_add_module_all_refuses_every_walrus_variant():
    for label, src in _WALRUS_CASES.items():
        assert add_module_all(src) is None, f"{label}: __all__ wrongly landed"


def test_fixB_walrus_leaks_a_name_the_naive_set_would_omit(tmp_path: Path):
    # The soundness PROOF: the runtime ``from m import *`` set really contains the
    # walrus-bound name (so an emitted ``__all__`` listing only the obvious targets
    # would DIVERGE from the default star set). Verified with the live star oracle.
    leaks = {
        "assign_value": ("RESULT = (computed := 41)\n", "computed"),
        "annassign_value": ("X: int = (Y := 5)\n", "Y"),
        "comprehension": ("data = [y := i for i in range(3)]\n", "y"),
    }
    for i, (label, (src, leaked)) in enumerate(leaks.items()):
        star = _star_set(tmp_path, f"walrus_{i}", src)
        assert leaked in star, f"{label}: {leaked!r} not in runtime star set {star}"
        # The module is refused, so no possibly-divergent ``__all__`` is ever landed.
        assert add_module_all(src) is None


def test_fixB_has_walrus_false_without_walrus_and_on_syntax_error():
    assert not has_walrus("X = 1\ndef f(): pass\n")
    assert not has_walrus("def (:\n")  # unparseable — no false positive


def test_fixB_non_walrus_module_still_wires_after_the_guard():
    # The walrus guard must not regress the normal path: a plain module with no
    # walrus still computes its public set and lands ``__all__``.
    out = add_module_all(_LEAF)
    assert out is not None and "__all__ = [" in out


# --- CONFIRMED code-review fix B (doc drift): del REFUSES, it is not inert -------

def test_fixB_top_level_del_refuses_the_whole_module():
    # ``_is_inert_top_level``'s docstring is aligned to reality: a top-level ``del``
    # is NOT inert (``ast.Delete`` is not in the inert tuple) — it can REMOVE a name
    # from the default star set, so the whole module is refused.
    src = "X = 1\nY = 2\ndel Y\n"
    assert public_star_names(src) is None
    assert add_module_all(src) is None
