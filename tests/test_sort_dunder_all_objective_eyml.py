"""sort-dunder-all develop objective — SORT + de-duplicate an existing
module-level ``__all__ = [...]`` (or ``(...)``) of string literals into canonical
lexicographic order.

The ORDER of ``__all__`` never affects ``from m import *`` (only WHICH names are
exported), so reordering and dropping an accidental duplicate is behaviour-
IDENTICAL — nothing observable changes. It is the public-surface analogue of
``sort-imports`` (also TIDY). Where a linter only flags an unsorted ``__all__``,
Apex rewrites it.

Covers: the core transform (sort an unsorted list; de-dupe a repeat; sort + de-dupe
together; preserve the tuple container; preserve trailing-newline absence; preserve
the surrounding module bytes) plus EVERY refusal — no ``__all__`` (the
wire-module-exports boundary), a computed ``__all__`` (a name, a ``BinOp``, a call),
an ``__all__ += ...`` (``AugAssign``), an ``__all__.append/.extend`` call, a
conditional re-binding, a non-string element, more than one ``__all__``, an
already-canonical list, a syntax error; plus idempotency and determinism; the
COMPOSITION with wire-module-exports (a freshly-wired ``__all__`` is already
canonical → a fixpoint; and the two surfaces are disjoint — wire refuses where an
``__all__`` exists, sort acts there); objective registration / reachability (the
1:1 facet-map<->registry parity invariant, substring-safety, the north-star manifest
classing it TIDY with the reverse tripwire clean, the facet ladder carrying the
phrase with the originals still leading); and the plan + END-TO-END landing
(``apply_rename`` verify=True sorts the ``__all__`` in place and the suite stays
green — proving the reorder is behaviour-identical).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.objectives.sort_dunder_all import plan_sort_dunder_all
from app.execution.sort_dunder_all import all_is_sortable, sort_module_all

_PHRASE = "the module __all__ to sort"


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


def _all_names(source: str) -> list:
    """The ``__all__`` value of ``source``, evaluated (a list/tuple of names)."""
    tree = ast.parse(source)
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in stmt.targets):
            return list(ast.literal_eval(stmt.value))
    raise AssertionError("no __all__ found")


# --- the core transform: detection & rewrite --------------------------------

def test_sorts_unsorted_list():
    out = sort_module_all('__all__ = ["b", "a", "c"]\n')
    assert out is not None
    ast.parse(out)
    assert _all_names(out) == ["a", "b", "c"]


def test_dedupes_repeated_name():
    out = sort_module_all('__all__ = ["a", "b", "a"]\n')
    assert out is not None
    assert _all_names(out) == ["a", "b"]  # single occurrence — behaviour-identical


def test_sorts_and_dedupes_together():
    out = sort_module_all('__all__ = ["b", "a", "b"]\n')
    assert out is not None
    assert _all_names(out) == ["a", "b"]


def test_preserves_tuple_container():
    out = sort_module_all('__all__ = ("b", "a")\n')
    assert out is not None
    ast.parse(out)
    value = out.split("=", 1)[1].strip()
    assert value.startswith("(") and value.rstrip().endswith(")")  # still a tuple
    assert _all_names(out) == ["a", "b"]
    # literal_eval of the rendered value is a TUPLE, not a list.
    assert isinstance(ast.literal_eval(value), tuple)


def test_all_is_sortable_true_for_unsorted():
    assert all_is_sortable('__all__ = ["b", "a"]\n') is True


def test_all_is_sortable_false_for_sorted():
    assert all_is_sortable('__all__ = ["a", "b"]\n') is False


def test_preserves_trailing_newline_absence():
    out = sort_module_all('__all__ = ["b", "a"]')
    assert out is not None and not out.endswith("\n")


def test_preserves_surrounding_module_bytes():
    src = (
        '"""A module."""\n'
        "\n"
        "import os\n"
        "\n"
        '__all__ = ["b", "a"]\n'
        "\n"
        "\n"
        "def f():\n"
        "    return os.getcwd()\n"
    )
    out = sort_module_all(src)
    assert out is not None
    # Everything OUTSIDE the __all__ span is byte-identical: split the modules on
    # their __all__ block and compare the head + tail.
    head_before, _, _tail = src.partition("__all__")
    head_after, _, _tail2 = out.partition("__all__")
    assert head_before == head_after  # docstring + imports untouched
    assert "def f():\n    return os.getcwd()\n" in out  # function body untouched
    assert _all_names(out) == ["a", "b"]


# --- the core transform: REFUSALS -------------------------------------------

def test_refuses_when_no_all():
    assert sort_module_all("x = 1\n") is None  # the wire-module-exports boundary


def test_refuses_computed_all_name():
    assert sort_module_all("_PUBLIC = ['a']\n__all__ = _PUBLIC\n") is None


def test_refuses_computed_all_binop():
    assert sort_module_all('_BASE = ["a"]\n__all__ = _BASE + ["x"]\n') is None


def test_refuses_computed_all_call():
    assert sort_module_all("__all__ = list(_names)\n") is None
    assert sort_module_all('__all__ = sorted(["b", "a"])\n') is None


def test_refuses_augassign_all():
    assert sort_module_all('__all__ = ["b", "a"]\n__all__ += ["c"]\n') is None


def test_refuses_append_extend_all():
    assert sort_module_all('__all__ = ["b", "a"]\n__all__.append("c")\n') is None
    assert sort_module_all('__all__ = ["b", "a"]\n__all__.extend(["c"])\n') is None


def test_refuses_conditional_all():
    src = (
        "from typing import TYPE_CHECKING\n"
        '__all__ = ["b", "a"]\n'
        "if TYPE_CHECKING:\n"
        '    __all__ += ["c"]\n'
    )
    assert sort_module_all(src) is None


def test_refuses_non_string_element():
    assert sort_module_all('x = 1\n__all__ = ["a", x]\n') is None
    assert sort_module_all('__all__ = ["a", 1]\n') is None
    assert sort_module_all('n = "z"\n__all__ = ["a", f"{n}"]\n') is None
    assert sort_module_all("other = ['z']\n__all__ = [*other]\n") is None


def test_refuses_multiple_all_assignments():
    assert sort_module_all('__all__ = ["b"]\n__all__ = ["a"]\n') is None


def test_refuses_already_sorted_idempotent():
    assert sort_module_all('__all__ = ["a", "b", "c"]\n') is None


def test_refuses_syntax_error():
    assert sort_module_all("def (:\n") is None


# --- idempotency / determinism ----------------------------------------------

def test_idempotent_second_run_is_noop():
    once = sort_module_all('__all__ = ["b", "a"]\n')
    assert once is not None
    assert sort_module_all(once) is None  # already canonical — byte-identical no-op


def test_deterministic_across_two_runs():
    a = sort_module_all('__all__ = ["c", "a", "b"]\n')
    b = sort_module_all('__all__ = ["c", "a", "b"]\n')
    assert a is not None and a == b


# --- composition with wire-module-exports (the non-conflict proof) -----------

def test_composes_with_wire_module_exports_to_a_fixpoint():
    from app.execution.module_exports import add_module_all

    # A module with no __all__: wire CREATES one ...
    src = "def beta():\n    pass\n\n\ndef alpha():\n    pass\n"
    wired = add_module_all(src)
    assert wired is not None and "__all__" in wired
    # ... and it is ALREADY canonical, so sort is a byte-identical no-op (fixpoint).
    assert sort_module_all(wired) is None


def test_wire_creates_sort_orders_distinct_surfaces():
    from app.execution.module_exports import add_module_all

    # On a module that ALREADY has an __all__: wire REFUSES (it only creates a
    # missing one) while sort may act — the surfaces are disjoint.
    src = '__all__ = ["b", "a"]\n\n\ndef a():\n    pass\n\n\ndef b():\n    pass\n'
    assert add_module_all(src) is None  # wire refuses the existing __all__
    assert sort_module_all(src) is not None  # sort acts on it


# --- registration / reachability --------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "sort-dunder-all" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["sort-dunder-all"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "sort-dunder-all"


def test_facet_reachability_parity_invariant_holds():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_facet_phrase_is_substring_order_safe():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    keys = list(FACET_OBJECTIVE_MAP)
    assert _PHRASE in keys
    for other in keys:
        if other == _PHRASE:
            continue
        assert _PHRASE not in other, f"{_PHRASE!r} is a substring of {other!r}"
        assert other not in _PHRASE, f"{other!r} is a substring of {_PHRASE!r}"


def test_manifest_classes_it_tidy_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "sort-dunder-all" in buckets["TIDY"]
    assert manifest_subset_of_registry() == []


def test_facet_phrase_lives_in_the_import_direction_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["import direction"]
    assert _PHRASE in ladder
    assert ladder[0] == "an unused import"  # originals still lead


# --- the plan: an unsorted __all__ gets sorted -------------------------------

def test_plan_sorts_all(tmp_path: Path):
    _project(tmp_path, "app/api.py", '__all__ = ["b", "a", "c"]\n')
    plan = plan_sort_dunder_all(str(tmp_path), "app/api.py")
    assert plan.ok
    new = plan.new_contents["app/api.py"]
    assert _all_names(new) == ["a", "b", "c"]
    assert plan.originals["app/api.py"] == '__all__ = ["b", "a", "c"]\n'
    assert plan.edits_by_file["app/api.py"] == 1


def test_plan_refuses_module_without_all(tmp_path: Path):
    _project(tmp_path, "app/api.py", "x = 1\n")
    assert not plan_sort_dunder_all(str(tmp_path), "app/api.py").new_contents


def test_plan_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", '__all__ = ["b", "a"]\n')
    assert not plan_sort_dunder_all(str(tmp_path), "tests/test_x.py").new_contents


def test_plan_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", '__all__ = ["b", "a"]\n')
    assert not plan_sort_dunder_all(str(tmp_path), "fixtures/sample.py").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_sort_dunder_all(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: gated apply, real landing, suite stays green ----------------

def test_end_to_end_sorts_all_and_keeps_green(tmp_path: Path):
    _suite_project(tmp_path)
    (tmp_path / "app" / "api.py").write_text(
        '__all__ = ["beta", "alpha"]\n'
        "\n"
        "\n"
        "def alpha():\n"
        "    return 1\n"
        "\n"
        "\n"
        "def beta():\n"
        "    return 2\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_api.py").write_text(
        "from app.api import alpha, beta\n"
        "def test_both():\n"
        "    assert alpha() == 1 and beta() == 2\n",
        encoding="utf-8")

    plan = plan_sort_dunder_all(str(tmp_path), "app/api.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "api.py").read_text(encoding="utf-8")
    assert _all_names(landed) == ["alpha", "beta"]  # sorted
    # Behaviour preserved (proven green by the apply gate): both symbols import.
    assert "def alpha():" in landed and "def beta():" in landed
