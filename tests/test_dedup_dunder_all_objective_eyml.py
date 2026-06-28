"""dedup-dunder-all develop objective — REMOVE duplicate entries from an existing
module-level ``__all__ = [...]`` (or ``(...)``) of string literals, PRESERVING
first-appearance order.

The CONTENTS of ``__all__`` are a membership SET — ``from m import *`` consults only
WHICH names appear, never how many times — so dropping a repeat is behaviour-
IDENTICAL: nothing observable changes. DISTINCT from its sibling ``sort-dunder-all``,
which canonically ORDERS ``__all__`` (and de-dupes only as a side effect); this keeps
the author's ORIGINAL order and removes ONLY the duplicates, so it is a no-op on a
duplicate-free list whatever its order (it never reorders a deliberately-grouped
``__all__`` a sort would churn).

Covers: the core transform (de-dupe keeping FIRST-seen order; the explicit NOT-sorted
property; preserve the tuple container; preserve trailing-newline absence; preserve
the surrounding module bytes) plus EVERY refusal — no ``__all__``, a duplicate-FREE
list (sort's business, not this), a computed ``__all__`` (a name, a ``BinOp``, a
call), an ``__all__ += ...`` (``AugAssign``), an ``__all__.append/.extend`` call, a
conditional re-binding, a non-string element, more than one ``__all__``, a COMMENT in
the ``__all__`` span (comment-loss — a dropped dup line would orphan it), a syntax
error; plus idempotency and determinism; objective registration / reachability (the
1:1 facet-map<->registry parity invariant, substring-safety, the north-star manifest
classing it TIDY with the reverse tripwire clean, the soundness strategy + the
``dynamic_dunder_all`` corpus shape it must refuse, the facet ladder carrying the
phrase with the originals still leading); and the plan + END-TO-END landing
(``apply_rename`` verify=True de-dupes the ``__all__`` in place and the suite stays
green — proving the removal is behaviour-identical).
"""

from __future__ import annotations

import ast
from pathlib import Path

import app.engine.soundness_audit as sa
from app.execution.cross_file_rename import apply_rename
from app.execution.dedup_dunder_all import all_has_duplicates, dedup_module_all
from app.execution.objectives.dedup_dunder_all import plan_dedup_dunder_all

_PHRASE = "the duplicate __all__ entries to remove"
_REPO = Path(__file__).resolve().parents[1]


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

def test_dedupes_repeated_name_keeping_first_seen_order():
    out = dedup_module_all('__all__ = ["a", "b", "a"]\n')
    assert out is not None
    ast.parse(out)
    assert _all_names(out) == ["a", "b"]  # single occurrence — behaviour-identical


def test_dedup_is_NOT_sorted_preserves_author_order():
    # The defining property vs sort-dunder-all: a list whose UNIQUE names are out of
    # alphabetical order keeps that order — only the duplicate goes.
    out = dedup_module_all('__all__ = ["b", "a", "b"]\n')
    assert out is not None
    assert _all_names(out) == ["b", "a"]  # NOT ["a", "b"] — order preserved


def test_dedupes_multiple_repeats_first_seen_order():
    out = dedup_module_all('__all__ = ["c", "a", "c", "a", "b"]\n')
    assert out is not None
    assert _all_names(out) == ["c", "a", "b"]  # each kept at first appearance


def test_preserves_tuple_container():
    out = dedup_module_all('__all__ = ("b", "a", "b")\n')
    assert out is not None
    ast.parse(out)
    value = out.split("=", 1)[1].strip()
    assert value.startswith("(") and value.rstrip().endswith(")")  # still a tuple
    assert _all_names(out) == ["b", "a"]
    # literal_eval of the rendered value is a TUPLE, not a list.
    assert isinstance(ast.literal_eval(value), tuple)


def test_single_element_tuple_dup_renders_valid_trailing_comma():
    # ("a", "a") -> a one-element tuple; the trailing comma keeps it a tuple.
    out = dedup_module_all('__all__ = ("a", "a")\n')
    assert out is not None
    value = out.split("=", 1)[1].strip()
    assert isinstance(ast.literal_eval(value), tuple)
    assert _all_names(out) == ["a"]


def test_all_has_duplicates_true_for_repeat():
    assert all_has_duplicates('__all__ = ["a", "b", "a"]\n') is True


def test_all_has_duplicates_false_for_unique():
    assert all_has_duplicates('__all__ = ["b", "a"]\n') is False  # unsorted but unique


def test_preserves_trailing_newline_absence():
    out = dedup_module_all('__all__ = ["b", "a", "b"]')
    assert out is not None and not out.endswith("\n")


def test_preserves_surrounding_module_bytes():
    src = (
        '"""A module."""\n'
        "\n"
        "import os\n"
        "\n"
        '__all__ = ["b", "a", "b"]\n'
        "\n"
        "\n"
        "def f():\n"
        "    return os.getcwd()\n"
    )
    out = dedup_module_all(src)
    assert out is not None
    # Everything OUTSIDE the __all__ span is byte-identical.
    head_before, _, _tail = src.partition("__all__")
    head_after, _, _tail2 = out.partition("__all__")
    assert head_before == head_after  # docstring + imports untouched
    assert "def f():\n    return os.getcwd()\n" in out  # function body untouched
    assert _all_names(out) == ["b", "a"]


# --- the core transform: REFUSALS -------------------------------------------

def test_refuses_when_no_all():
    assert dedup_module_all("x = 1\n") is None


def test_refuses_duplicate_free_list():
    # An unsorted BUT unique list is sort-dunder-all's business — dedup is a no-op.
    assert dedup_module_all('__all__ = ["b", "a"]\n') is None
    assert dedup_module_all('__all__ = ["a", "b", "c"]\n') is None


def test_refuses_computed_all_name():
    assert dedup_module_all("_PUBLIC = ['a', 'a']\n__all__ = _PUBLIC\n") is None


def test_refuses_computed_all_binop():
    # A dynamic __all__ whose literal fragment repeats — editing only the literal
    # part could change the exported set the dynamic part composes with: refuse.
    assert dedup_module_all('_BASE = ["a"]\n__all__ = _BASE + ["x", "x"]\n') is None


def test_refuses_computed_all_call():
    assert dedup_module_all("__all__ = list(_names)\n") is None
    assert dedup_module_all('__all__ = sorted(["b", "a", "b"])\n') is None


def test_refuses_augassign_all():
    assert dedup_module_all('__all__ = ["a", "a"]\n__all__ += ["c"]\n') is None


def test_refuses_append_extend_all():
    assert dedup_module_all('__all__ = ["a", "a"]\n__all__.append("c")\n') is None
    assert dedup_module_all('__all__ = ["a", "a"]\n__all__.extend(["c"])\n') is None


def test_refuses_conditional_all():
    src = (
        "from typing import TYPE_CHECKING\n"
        '__all__ = ["a", "a"]\n'
        "if TYPE_CHECKING:\n"
        '    __all__ += ["c"]\n'
    )
    assert dedup_module_all(src) is None


def test_refuses_non_string_element():
    assert dedup_module_all('x = 1\n__all__ = ["a", "a", x]\n') is None
    assert dedup_module_all('__all__ = ["a", "a", 1]\n') is None
    assert dedup_module_all('n = "z"\n__all__ = ["a", "a", f"{n}"]\n') is None
    assert dedup_module_all("other = ['z']\n__all__ = ['a', 'a', *other]\n") is None


def test_refuses_multiple_all_assignments():
    assert dedup_module_all('__all__ = ["a", "a"]\n__all__ = ["b", "b"]\n') is None


def test_refuses_comment_in_span_comment_loss():
    # A duplicate IS present, but the multi-line __all__ carries a comment; dropping
    # the duplicate line would orphan it, so the whole declaration is refused.
    src = (
        "__all__ = [\n"
        '    "a",  # the primary export\n'
        '    "b",\n'
        '    "a",\n'
        "]\n"
    )
    assert dedup_module_all(src) is None


def test_refuses_own_line_comment_in_span():
    # A standalone comment line inside the span is equally orphan-prone: refuse.
    src = (
        "__all__ = [\n"
        "    # public surface\n"
        '    "a",\n'
        '    "b",\n'
        '    "a",\n'
        "]\n"
    )
    assert dedup_module_all(src) is None


def test_hash_inside_string_element_is_not_a_comment():
    # A literal '#' inside a STRING element is not a comment — de-dup still lands.
    out = dedup_module_all('__all__ = ["a#b", "c", "a#b"]\n')
    assert out is not None
    assert _all_names(out) == ["a#b", "c"]


def test_refuses_syntax_error():
    assert dedup_module_all("def (:\n") is None


# --- idempotency / determinism ----------------------------------------------

def test_idempotent_second_run_is_noop():
    once = dedup_module_all('__all__ = ["b", "a", "b"]\n')
    assert once is not None
    assert dedup_module_all(once) is None  # no remaining dup — byte-identical no-op


def test_deterministic_across_two_runs():
    a = dedup_module_all('__all__ = ["c", "a", "b", "c"]\n')
    b = dedup_module_all('__all__ = ["c", "a", "b", "c"]\n')
    assert a is not None and a == b


# --- relationship to sort-dunder-all (the order-vs-canonical boundary) --------

def test_distinct_from_sort_on_a_dedup_only_module():
    from app.execution.sort_dunder_all import sort_module_all

    # A list that is unsorted AND duplicated: dedup keeps first-seen order; sort
    # canonicalises. They produce DIFFERENT bytes — proving they are distinct moves.
    src = '__all__ = ["b", "a", "b"]\n'
    dd = dedup_module_all(src)
    st = sort_module_all(src)
    assert dd is not None and st is not None
    assert _all_names(dd) == ["b", "a"]   # order preserved
    assert _all_names(st) == ["a", "b"]   # canonical
    assert dd != st


# --- registration / reachability --------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "dedup-dunder-all" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["dedup-dunder-all"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "dedup-dunder-all"


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

    # Filed TIDY (a behavior-preserving idiom — removing a duplicate from an EXISTING
    # __all__ lands no new code), alongside its sibling sort-dunder-all; CONCRETE is
    # reserved for objectives that land code that did not exist before. Keeping it out
    # of CONCRETE keeps the anti-drift concrete_ratio honest.
    buckets = classify_objectives(available_objectives())
    assert "dedup-dunder-all" in buckets["TIDY"]
    assert "dedup-dunder-all" not in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_soundness_strategy_declared_and_reverse_clean():
    assert "dedup-dunder-all" in sa.SOUNDNESS_STRATEGY
    strategy = sa.SOUNDNESS_STRATEGY["dedup-dunder-all"]
    assert "membership-is-a-set" in strategy and "comment-loss" in strategy
    assert sa.strategy_subset_of_registry() == []  # no stale strategy name


def test_facet_phrase_lives_in_the_import_direction_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["import direction"]
    assert _PHRASE in ladder
    assert ladder[0] == "an unused import"  # originals still lead


# --- the soundness corpus: the dynamic-__all__ shape MUST refuse -------------

def _verdict(objective: str, shape: str) -> str:
    from app.engine.objective_compiler import _objectives_map

    _fitness, moves = _objectives_map()[objective]
    changed = sa._changed_files(moves, sa.corpus_root(_REPO) / shape)
    return sa._classify_cell(shape, objective, changed)


def test_corpus_shape_present():
    assert "dynamic_dunder_all" in set(sa.corpus_shapes(_REPO))


def test_dedup_refuses_dynamic_dunder_all_corpus_shape():
    assert _verdict("dedup-dunder-all", "dynamic_dunder_all") == "refused"


def test_sort_sibling_also_refuses_dynamic_dunder_all():
    # The fixture pins the shared-gate boundary: sort-dunder-all refuses it too.
    assert _verdict("sort-dunder-all", "dynamic_dunder_all") == "refused"


def test_dedup_never_violates_any_corpus_shape():
    # dedup-dunder-all only acts on a duplicate PURE-literal __all__, which no fixture
    # has — so it refuses every shape and lands no violating change.
    corpus = sa.corpus_refusal_findings(_REPO)
    cells = corpus.get("dedup-dunder-all", {})
    bad = {s: v for s, v in cells.items() if v.startswith("VIOLATION")}
    assert bad == {}, bad


# --- the plan: a duplicated __all__ gets de-duped ---------------------------

def test_plan_dedupes_all(tmp_path: Path):
    _project(tmp_path, "app/api.py", '__all__ = ["b", "a", "b"]\n')
    plan = plan_dedup_dunder_all(str(tmp_path), "app/api.py")
    assert plan.ok
    new = plan.new_contents["app/api.py"]
    assert _all_names(new) == ["b", "a"]  # de-duped, order preserved
    assert plan.originals["app/api.py"] == '__all__ = ["b", "a", "b"]\n'
    assert plan.edits_by_file["app/api.py"] == 1


def test_plan_refuses_module_without_dup(tmp_path: Path):
    _project(tmp_path, "app/api.py", '__all__ = ["b", "a"]\n')
    assert not plan_dedup_dunder_all(str(tmp_path), "app/api.py").new_contents


def test_plan_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", '__all__ = ["a", "a"]\n')
    assert not plan_dedup_dunder_all(str(tmp_path), "tests/test_x.py").new_contents


def test_plan_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", '__all__ = ["a", "a"]\n')
    assert not plan_dedup_dunder_all(str(tmp_path), "fixtures/sample.py").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_dedup_dunder_all(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: gated apply, real landing, suite stays green ----------------

def test_end_to_end_dedupes_all_and_keeps_green(tmp_path: Path):
    _suite_project(tmp_path)
    (tmp_path / "app" / "api.py").write_text(
        '__all__ = ["beta", "alpha", "beta"]\n'
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

    plan = plan_dedup_dunder_all(str(tmp_path), "app/api.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "api.py").read_text(encoding="utf-8")
    assert _all_names(landed) == ["beta", "alpha"]  # de-duped, order preserved
    # Behaviour preserved (proven green by the apply gate): both symbols import.
    assert "def alpha():" in landed and "def beta():" in landed
