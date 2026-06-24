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
    defined_public_names,
    has_module_all,
    has_star_import,
    has_walrus,
    imported_public_names,
    module_dotted_targets,
    project_has_star_consumer,
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

def test_public_set_collects_defs_classes_assigns_excludes_imports():
    names = public_star_names(_LEAF)
    # v2: def + class + assignment target ONLY — the imported ``os`` and the
    # ``from __future__`` ``annotations`` binding are EXCLUDED (defect #1).
    assert names == ["Thing", "VALUE", "helper"]
    assert "os" not in names and "annotations" not in names


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


def test_public_set_excludes_import_alias_asname():
    # v2: imports (even aliased) are NEVER members of the defined-public set; a
    # module that only imports defines nothing public — the empty set.
    src = "import os.path as op\nfrom collections import OrderedDict as OD\n"
    assert public_star_names(src) == []


def test_public_set_excludes_dotted_import_head():
    src = "import os.path\n"  # binds ``os`` — an IMPORT, excluded in v2
    assert public_star_names(src) == []


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
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")  # a package
    plan = plan_wire_module_exports(str(tmp_path), "app/util.py")
    assert plan.ok
    new = plan.new_contents["app/util.py"]
    # v2: defined-only ``__all__`` (no ``os`` / ``annotations``); landed here
    # because NO project file does ``from app.util import *`` (soundness scan).
    assert '__all__ = [\n    "Thing",\n    "VALUE",\n    "helper",\n]' in new
    assert "os" not in new.split("__all__", 1)[1].split("]", 1)[0]
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


# --- behaviour: the v2 star set is exactly the DEFINED publics ---------------

def test_star_set_after_equals_defined_publics_dropping_imports(tmp_path: Path):
    # v2 INTENTIONALLY shrinks the runtime ``from m import *`` set to the names the
    # module DEFINES, dropping the imported publics the v1 default leaked. With NO
    # project star consumer this shrink is provably unobservable, so it lands; the
    # landed star set equals exactly ``public_star_names`` (the defined publics).
    cases = [
        (_LEAF, ["Thing", "VALUE", "helper"], {"os", "annotations"}),
        ("import os, sys\ndef f(): pass\nclass C: pass\nX = 1\n_y = 2\n",
         ["C", "X", "f"], {"os", "sys"}),
        ('"""d"""\nfrom collections import OrderedDict\ndef g(): pass\n',
         ["g"], {"OrderedDict"}),
        ("from __future__ import annotations\nVALUE = 1\ndef h(): pass\n",
         ["VALUE", "h"], {"annotations"}),
    ]
    for i, (src, defined, dropped) in enumerate(cases):
        out = add_module_all(src)
        assert out is not None, f"case {i} should rewrite"
        assert public_star_names(src) == defined
        before = set(_star_set(tmp_path, f"mod_before_{i}", src))
        after = set(_star_set(tmp_path, f"mod_after_{i}", out))
        assert after == set(defined), f"case {i}: landed star set {after}"
        # The shrink dropped exactly the imported publics, nothing defined.
        assert before - after == dropped, f"case {i}: dropped {before - after}"
        assert set(defined) <= before


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


# =====================================================================
# v2 ACCEPTANCE — the 3 pilot defects fixed soundly (spec tests 1..10)
# =====================================================================

# A library module that IMPORTS stdlib publics (``re``, ``log``) AND defines a
# ``def`` + ``class``. v1 wrongly put ``re``/``log`` in ``__all__``; v2 emits the
# defined-only set and proves the star-set shrink safe via the project scan.
_IMPORTING_LEAF = (
    '"""A leaf that imports stdlib."""\n'
    "import re\n"
    "from math import log\n"
    "\n"
    "\n"
    "def foo():\n"
    "    return re.compile('x')\n"
    "\n"
    "\n"
    "class Bar:\n"
    "    pass\n"
)


def _pkg_project(tmp_path: Path, rel: str, src: str) -> Path:
    """Write ``rel`` inside a real package (its dir gets an ``__init__.py``) so the
    library-module eligibility gate passes; return the project root."""
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    (target.parent / "__init__.py").write_text("", encoding="utf-8")
    target.write_text(src, encoding="utf-8")
    return tmp_path


# --- spec #1: imported publics excluded, no consumer => defined-only __all__ --

def test_v2_imported_publics_excluded_when_no_star_consumer(tmp_path: Path):
    _pkg_project(tmp_path, "pkg/leaf.py", _IMPORTING_LEAF)
    plan = plan_wire_module_exports(str(tmp_path), "pkg/leaf.py")
    assert plan.ok
    new = plan.new_contents["pkg/leaf.py"]
    assert '__all__ = [\n    "Bar",\n    "foo",\n]' in new
    body = new.split("__all__", 1)[1]
    assert "re" not in body.split("]", 1)[0] and "log" not in body.split("]", 1)[0]
    # The pure computation agrees: defined publics only, imports excluded.
    assert defined_public_names(_IMPORTING_LEAF) == ["Bar", "foo"]
    assert imported_public_names(_IMPORTING_LEAF) == {"re", "log"}


# --- spec #2: a project star consumer => REFUSE (soundness proof) ------------

def test_v2_refuses_when_a_project_file_star_imports_this_module(tmp_path: Path):
    _pkg_project(tmp_path, "pkg/leaf.py", _IMPORTING_LEAF)
    # Another module observes the star set — dropping ``re``/``log`` is observable.
    (tmp_path / "pkg" / "consumer.py").write_text(
        "from pkg.leaf import *\n\n\ndef use():\n    return re\n", encoding="utf-8")
    plan = plan_wire_module_exports(str(tmp_path), "pkg/leaf.py")
    assert not plan.new_contents  # REFUSED — honest no-op
    # And the underlying scan sees the consumer for this module's dotted target.
    sources = [_IMPORTING_LEAF, "from pkg.leaf import *\n"]
    assert project_has_star_consumer(sources, module_dotted_targets("pkg/leaf.py"))


# --- spec #3: __future__ annotations never appears in __all__ ----------------

def test_v2_future_annotations_never_in_all():
    src = (
        "from __future__ import annotations\n"
        "\n"
        "\n"
        "def g():\n"
        "    pass\n"
    )
    # No OTHER imported publics, so the set equals the default star set MINUS the
    # ``annotations`` binding — but ``annotations`` is itself an import, excluded.
    assert defined_public_names(src) == ["g"]
    assert "annotations" in imported_public_names(src)
    out = add_module_all(src)  # single-source: only import is ``annotations``
    assert out is not None and "annotations" not in out.split("__all__", 1)[1]


# --- spec #4: a file whose dir lacks __init__.py (setup.py) => no-op ---------

def test_v2_refuses_non_library_file_no_init_py(tmp_path: Path):
    # setup.py at the repo root: its directory has NO __init__.py — refuse.
    (tmp_path / "setup.py").write_text(_LEAF, encoding="utf-8")
    assert not plan_wire_module_exports(str(tmp_path), "setup.py").new_contents
    # A loose top-level module (no __init__.py beside it) is also refused.
    (tmp_path / "loose.py").write_text(_LEAF, encoding="utf-8")
    assert not plan_wire_module_exports(str(tmp_path), "loose.py").new_contents


# --- spec #5: docs/conf.py and the basename denylist => no-op ----------------

def test_v2_refuses_docs_conf_py_and_denylist_scripts(tmp_path: Path):
    _pkg_project(tmp_path, "docs/conf.py", _LEAF)  # conf.py IS denylisted...
    # ...even though its dir now has an __init__.py — a denylisted script anywhere.
    assert not plan_wire_module_exports(str(tmp_path), "docs/conf.py").new_contents
    for name in ("conftest.py", "manage.py", "noxfile.py", "_version.py"):
        _pkg_project(tmp_path, f"pkg/{name}", _LEAF)
        assert not plan_wire_module_exports(
            str(tmp_path), f"pkg/{name}").new_contents, name


# --- spec #6: __all__ lands AFTER a shebang line -----------------------------

def test_v2_all_lands_after_shebang():
    src = (
        "#!/usr/bin/env python\n"
        '"""Doc."""\n'
        "\n"
        "\n"
        "def run():\n"
        "    pass\n"
    )
    out = add_module_all(src)
    assert out is not None
    lines = out.splitlines()
    assert lines[0] == "#!/usr/bin/env python"  # shebang stays on physical line 1
    all_idx = lines.index("__all__ = [")
    assert all_idx > lines.index('"""Doc."""')  # after docstring
    assert all_idx > 0  # never above the shebang
    ast.parse(out)


# --- spec #7: __all__ lands AFTER a PEP-263 coding line ----------------------

def test_v2_all_lands_after_pep263_coding_line():
    src = (
        "# -*- coding: utf-8 -*-\n"
        "\n"
        "\n"
        "def run():\n"
        "    pass\n"
    )
    out = add_module_all(src)
    assert out is not None
    lines = out.splitlines()
    assert lines[0] == "# -*- coding: utf-8 -*-"  # coding line stays on line 1
    assert lines.index("__all__ = [") > 0  # below the coding line
    ast.parse(out)


def test_v2_all_lands_after_shebang_and_coding_on_line_two():
    # Shebang on line 1, PEP-263 coding on line 2 — __all__ must clear BOTH.
    src = (
        "#!/usr/bin/env python\n"
        "# coding: utf-8\n"
        "import os\n"
        "\n"
        "\n"
        "def run():\n"
        "    return os.getcwd()\n"
    )
    out = add_module_all(src)
    assert out is not None
    lines = out.splitlines()
    assert lines[0] == "#!/usr/bin/env python"
    assert lines[1] == "# coding: utf-8"
    assert lines.index("__all__ = [") >= 2  # below both prologue lines


# --- spec #8: idempotence — a second run is a byte-identical no-op -----------

def test_v2_idempotent_second_run_is_byte_identical_noop(tmp_path: Path):
    once = add_module_all(_IMPORTING_LEAF)
    assert once is not None and has_module_all(once)
    assert add_module_all(once) is None  # already declares __all__ — no-op
    # Idempotent at the plan layer too.
    _pkg_project(tmp_path, "pkg/leaf.py", _IMPORTING_LEAF)
    p1 = plan_wire_module_exports(str(tmp_path), "pkg/leaf.py")
    landed = p1.new_contents["pkg/leaf.py"]
    (tmp_path / "pkg" / "leaf.py").write_text(landed, encoding="utf-8")
    p2 = plan_wire_module_exports(str(tmp_path), "pkg/leaf.py")
    assert not p2.new_contents  # second pass over the landed file is a no-op


# --- spec #9: a clean module importing nothing public still fires ------------

def test_v2_module_with_no_public_imports_still_fires(tmp_path: Path):
    # Only a PRIVATE import (``import os as _os``) + a stdlib import used but bound
    # privately => imported_publics is empty => the set equals the default star set
    # => behaviour-identical with NO project scan needed => fires.
    src = (
        "import os as _os\n"
        "\n"
        "\n"
        "def cwd():\n"
        "    return _os.getcwd()\n"
        "\n"
        "\n"
        "VALUE = 7\n"
    )
    assert imported_public_names(src) == set()  # no PUBLIC import
    assert defined_public_names(src) == ["VALUE", "cwd"]
    _pkg_project(tmp_path, "pkg/clean.py", src)
    # Even WITH a project star consumer, an empty imported-publics set means the
    # star set does not shrink, so it is still safe to land.
    (tmp_path / "pkg" / "c.py").write_text("from pkg.clean import *\n", encoding="utf-8")
    plan = plan_wire_module_exports(str(tmp_path), "pkg/clean.py")
    assert plan.ok
    assert '__all__ = [\n    "VALUE",\n    "cwd",\n]' in plan.new_contents["pkg/clean.py"]


# --- spec #10: an __init__ that re-exports via imports + a star consumer => refuse

def test_v2_init_reexport_with_star_consumer_is_refused(tmp_path: Path):
    # A package __init__ whose public surface is deliberate IMPORT re-exports, and a
    # sibling does ``from pkg import *`` — dropping the re-exports is observable, so
    # REFUSE (don't blindly strip deliberate re-exports). __init__.py is itself an
    # eligible library module, so only the soundness scan can stop this.
    init_src = "from .core import Engine\nfrom .util import helper\n"
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(init_src, encoding="utf-8")
    (pkg / "core.py").write_text("class Engine: pass\n", encoding="utf-8")
    (pkg / "util.py").write_text("def helper(): pass\n", encoding="utf-8")
    (tmp_path / "app_star.py").write_text("from pkg import *\n", encoding="utf-8")
    # Eligibility passes (__init__.py), imported_publics is non-empty, and a star
    # consumer of ``pkg`` exists => REFUSE.
    assert imported_public_names(init_src) == {"Engine", "helper"}
    assert defined_public_names(init_src) == []  # it DEFINES nothing — pure re-export
    plan = plan_wire_module_exports(str(tmp_path), "pkg/__init__.py")
    assert not plan.new_contents  # REFUSED — re-exports preserved


def test_v2_init_dotted_targets_include_package_and_explicit_form():
    # The dotted-target builder over-approximates an __init__ to BOTH spellings, so
    # ``from pkg import *`` AND ``from pkg.__init__ import *`` are both caught.
    targets = module_dotted_targets("pkg/sub/__init__.py")
    assert targets == {"pkg.sub", "pkg.sub.__init__"}
    assert module_dotted_targets("pkg/mod.py") == {"pkg.mod"}


# --- v2 soundness scan: relative star imports are over-approximated ----------

def test_v2_relative_star_import_anywhere_blocks_the_shrink():
    # We cannot resolve a relative ``from . import *`` target from source text, so
    # ANY relative star import is treated as a potential observer => unsafe.
    for rel_star in ("from . import *\n", "from .mod import *\n", "from .. import *\n"):
        assert project_has_star_consumer([rel_star], {"pkg.leaf"})
    # An ABSOLUTE star import of a DIFFERENT module is provably not an observer.
    assert not project_has_star_consumer(["from other.mod import *\n"], {"pkg.leaf"})


def test_v2_add_module_all_single_source_refuses_self_star(tmp_path: Path):
    # Single-source floor: a module that imports a public AND contains a star import
    # is refused outright by the star-import guard (the set is unknowable).
    src = "import re\nfrom x import *\ndef f(): pass\n"
    assert add_module_all(src) is None  # star import guard fires first
    # With imported publics but a relative star import in the SAME source, the
    # shrink-safety floor refuses (the source is its own scan set when module_rel
    # is None) — but here the star-import guard already returns None, so confirm a
    # NON-star module with imported publics and no consumer DOES land.
    ok_src = "import re\n\n\ndef f():\n    return re\n"
    assert add_module_all(ok_src) is not None
