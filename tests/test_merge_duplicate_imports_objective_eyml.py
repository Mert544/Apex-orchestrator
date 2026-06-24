"""merge-duplicate-imports develop objective — collapse repeated same-module
``from``-import lines into one, PROVABLY binding-identical.

Covers: the core merge (2+ same-module lines -> 1, first-appearance order, binding
multiset unchanged, exact-repeat de-dup, aliases preserved, indentation/newline
preserved) plus EVERY refusal — ``from __future__``; ``from x import *``; a duplicate
line carrying a trailing comment / ``# noqa`` / ``# type:`` that would be lost; an
INCOMPATIBLE alias (same local from two different name/asname pairs); a guarded /
non-sibling import (inside ``try``/``if``/function — not a top-level sibling);
intervening execution-relevant code between the group endpoints; test/fixture input;
a syntax error — plus idempotency and determinism; the four facet-parity assertions
(available, reachable-from-facet, the facet-map<->registry 1:1 invariant,
substring-safety, the north-star manifest classing it TIDY with the reverse tripwire
clean, the facet ladder carrying the phrase with the originals still leading); the
END-TO-END landing (``apply_rename`` verify=True merges in place and the suite stays
green); and a binding-preservation oracle (every name importable before the merge is
importable after)."""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.duplicate_imports import merge_duplicate_imports
from app.execution.objectives.merge_duplicate_imports import (
    plan_merge_duplicate_imports,
)

_PHRASE = "the duplicate from-imports to merge"

# Two same-module from-imports -> one merged line (first-appearance order).
_DUP = (
    "from collections import OrderedDict\n"
    "from collections import defaultdict\n"
    "\n"
    "\n"
    "x = OrderedDict()\n"
    "y = defaultdict(list)\n"
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


def _bindings(source: str) -> list[tuple[int, str, str, str | None]]:
    """The multiset (as a sorted list) of ``(level, module, name, asname)`` every
    top-level ``from``-import in ``source`` establishes — the invariant a merge must
    preserve exactly."""
    out: list[tuple[int, str, str, str | None]] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                out.append((node.level, node.module or "", alias.name, alias.asname))
    return sorted(out)


# --- the core transform: the merge ------------------------------------------

def test_merges_two_same_module_lines_into_one():
    out = merge_duplicate_imports(_DUP)
    assert out is not None
    assert "from collections import OrderedDict, defaultdict" in out
    # The two original lines collapsed to one statement.
    assert out.count("from collections import") == 1
    ast.parse(out)  # never lands broken Python


def test_merge_preserves_first_appearance_order():
    src = (
        "from m import c\n"
        "from m import a\n"
        "from m import b\n"
    )
    out = merge_duplicate_imports(src)
    assert out is not None
    assert "from m import c, a, b\n" == out


def test_merge_preserves_binding_multiset():
    out = merge_duplicate_imports(_DUP)
    assert out is not None
    # PROVABLY binding-identical: only the line count drops.
    assert _bindings(out) == _bindings(_DUP)


def test_merge_three_lines_with_aliases():
    src = (
        "from pkg import a as A\n"
        "from pkg import b\n"
        "from pkg import c as C\n"
    )
    out = merge_duplicate_imports(src)
    assert out is not None
    assert out == "from pkg import a as A, b, c as C\n"
    assert _bindings(out) == _bindings(src)


def test_merge_dedups_exact_repeat_alias():
    # An EXACT duplicate (same name, same asname) is collapsed to one — still
    # binding-identical: re-binding ``a`` from the same module is a no-op, so the
    # binding ENVIRONMENT (the SET of distinct (level, module, name, asname) bindings)
    # is unchanged; only the redundant literal repeat drops from the multiset.
    src = (
        "from m import a\n"
        "from m import a\n"
        "from m import b\n"
    )
    out = merge_duplicate_imports(src)
    assert out is not None
    assert out == "from m import a, b\n"
    assert set(_bindings(out)) == set(_bindings(src))


def test_distinct_modules_are_not_merged():
    src = (
        "from a import x\n"
        "from b import y\n"
    )
    assert merge_duplicate_imports(src) is None  # different modules — nothing to do


def test_relative_imports_merge_only_at_same_level():
    # Same module name but DIFFERENT relative level are distinct groups (.m vs ..m).
    src = (
        "from .m import a\n"
        "from ..m import b\n"
    )
    assert merge_duplicate_imports(src) is None


def test_relative_imports_same_level_merge():
    src = (
        "from .m import a\n"
        "from .m import b\n"
    )
    out = merge_duplicate_imports(src)
    assert out is not None
    assert out == "from .m import a, b\n"
    assert _bindings(out) == _bindings(src)


def test_merge_preserves_indentation_inside_a_block_is_not_attempted():
    # Sanity: indentation handling is exercised only at top level (the merge never
    # touches non-body imports — see the guarded-import refusals), so a clean
    # top-level merge keeps column 0.
    out = merge_duplicate_imports(_DUP)
    assert out is not None
    assert not out.startswith(" ")


# --- refusals ----------------------------------------------------------------

def test_refuses_future_import():
    # ``from __future__`` is order/placement-sensitive — never merged.
    src = (
        "from __future__ import annotations\n"
        "from __future__ import division\n"
    )
    assert merge_duplicate_imports(src) is None


def test_refuses_star_import_anywhere():
    src = (
        "from m import *\n"
        "from m import a\n"
        "from m import b\n"
    )
    assert merge_duplicate_imports(src) is None


def test_refuses_when_a_line_carries_a_trailing_comment():
    src = (
        "from m import a  # keep this\n"
        "from m import b\n"
    )
    assert merge_duplicate_imports(src) is None


def test_refuses_when_a_line_carries_noqa():
    src = (
        "from m import a\n"
        "from m import b  # noqa: F401\n"
    )
    assert merge_duplicate_imports(src) is None


def test_refuses_when_a_line_carries_type_comment():
    src = (
        "from m import a  # type: ignore\n"
        "from m import b\n"
    )
    assert merge_duplicate_imports(src) is None


def test_refuses_incompatible_alias():
    # Same LOCAL name ``a`` bound from two different import names — merging would
    # silently pick one; keep both lines (refuse the group).
    src = (
        "from m import x as a\n"
        "from m import y as a\n"
    )
    assert merge_duplicate_imports(src) is None


def test_refuses_import_guarded_by_try_block_not_a_top_level_sibling():
    # One import is top-level, the duplicate is inside a ``try`` — the guarded one is
    # conditional and must not be hoisted to a top-level sibling's position.
    src = (
        "from m import a\n"
        "try:\n"
        "    from m import b\n"
        "except ImportError:\n"
        "    b = None\n"
    )
    out = merge_duplicate_imports(src)
    # The top-level group has only ONE member (the guarded one is not a sibling), so
    # there is nothing to merge — a no-op, and the guarded import is untouched.
    assert out is None


def test_refuses_import_inside_if_block():
    src = (
        "from m import a\n"
        "if True:\n"
        "    from m import b\n"
    )
    assert merge_duplicate_imports(src) is None


def test_refuses_import_inside_type_checking_guard():
    src = (
        "from typing import TYPE_CHECKING\n"
        "from m import a\n"
        "if TYPE_CHECKING:\n"
        "    from m import b\n"
    )
    assert merge_duplicate_imports(src) is None


def test_refuses_intervening_executable_code():
    # An assignment runs BETWEEN the two same-module lines; collapsing the second
    # onto the first's position would reorder execution relative to ``side = log()``.
    src = (
        "from m import a\n"
        "side = compute()\n"
        "from m import b\n"
    )
    assert merge_duplicate_imports(src) is None


def test_intervening_disjoint_import_is_safe_to_coalesce_past():
    # An intervening import whose bound names are DISJOINT from the group's names is
    # genuinely safe to coalesce past: re-ordering cached imports is a no-op and no
    # binding is touched. ``import os`` binds ``os``; the group binds ``{a, b}``.
    src = (
        "from m import a\n"
        "import os\n"
        "from m import b\n"
    )
    out = merge_duplicate_imports(src)
    assert out is not None
    assert out.count("from m import") == 1
    assert "from m import a, b" in out
    assert "import os" in out
    assert _bindings(out) == _bindings(src)


def test_intervening_disjoint_from_import_group_is_safe_to_coalesce_past():
    # Same safety with an intervening DIFFERENT from-import group whose names are
    # disjoint from the group being merged — still a binding-identical merge.
    src = (
        "from m import a\n"
        "from other import z\n"
        "from m import b\n"
    )
    out = merge_duplicate_imports(src)
    assert out is not None
    assert out.count("from m import") == 1
    assert "from m import a, b" in out
    assert "from other import z" in out
    assert _bindings(out) == _bindings(src)


def test_refuses_intervening_plain_import_rebinding_a_group_name():
    # PROVEN binding flip: ``import y`` BETWEEN the two ``from a`` lines binds the same
    # local ``y`` that the group's second member also binds. Merging would hoist the
    # ``from a import y`` binding ABOVE ``import y``, flipping ``y``'s final value from
    # ``a.y`` to the module ``y``. Refuse the whole module — leave it unmerged.
    src = (
        "from a import x\n"
        "import y\n"
        "from a import y\n"
    )
    assert merge_duplicate_imports(src) is None


def test_refuses_intervening_from_import_group_rebinding_a_group_name():
    # PROVEN binding flip: ``from pkg.b import x`` between the two ``from pkg.a`` lines
    # binds the same local ``x`` the ``pkg.a`` group binds. Merging the ``pkg.a`` group
    # hoists its second member above ``from pkg.b import x``, flipping ``x`` from
    # ``pkg.a.x`` to ``pkg.b.x``. Refuse — leave the module unmerged.
    src = (
        "from pkg.a import x\n"
        "from pkg.b import x\n"
        "from pkg.a import x\n"
    )
    assert merge_duplicate_imports(src) is None


def test_intervening_aliased_plain_import_disjoint_is_safe():
    # ``import os.path as p`` binds the LOCAL name ``p`` (not ``os``) — disjoint from
    # the group's ``{a, b}``, so it stays safe to coalesce past.
    src = (
        "from m import a\n"
        "import os.path as p\n"
        "from m import b\n"
    )
    out = merge_duplicate_imports(src)
    assert out is not None
    assert "from m import a, b" in out
    assert _bindings(out) == _bindings(src)


def test_refuses_intervening_dotted_import_rebinding_group_top_name():
    # ``import a.b`` binds the LOCAL top name ``a`` (``import a.b`` makes only ``a`` a
    # name). When the group also binds ``a``, hoisting the group's ``a`` member above
    # ``import a.b`` would flip ``a`` from the module ``a`` to ``m.a`` — refuse.
    src = (
        "from m import z\n"
        "import a.b\n"
        "from m import a\n"
    )
    assert merge_duplicate_imports(src) is None


def test_refuses_standalone_comment_between_two_members():
    # A standalone comment line sits in the GAP between two group members. The merge
    # deletes the second member, which would ORPHAN the comment (its referent is
    # gone), so the group is refused even though neither member's own line carries a
    # comment.
    src = (
        "from m import a\n"
        "# we need b for the fallback path\n"
        "from m import b\n"
    )
    assert merge_duplicate_imports(src) is None


def test_merges_across_blank_line_gap():
    # A BLANK line (no comment, no code) between members is not execution-relevant and
    # carries no human note — the merge is still allowed.
    src = (
        "from m import a\n"
        "\n"
        "from m import b\n"
    )
    out = merge_duplicate_imports(src)
    assert out is not None
    assert out.count("from m import") == 1
    assert "from m import a, b" in out
    assert _bindings(out) == _bindings(src)


def test_refuses_syntax_error():
    assert merge_duplicate_imports("from m import (\n") is None


def test_single_already_merged_line_is_noop():
    # Already one statement -> nothing to merge (idempotent base case).
    assert merge_duplicate_imports("from m import a, b\n") is None


def test_empty_source_is_noop():
    assert merge_duplicate_imports("") is None


# --- idempotency / determinism ----------------------------------------------

def test_idempotent_second_run_is_noop():
    once = merge_duplicate_imports(_DUP)
    assert once is not None
    assert merge_duplicate_imports(once) is None  # 2nd run = byte-identical no-op


def test_deterministic_across_two_runs():
    a = merge_duplicate_imports(_DUP)
    b = merge_duplicate_imports(_DUP)
    assert a is not None and a == b


# --- registration / reachability (4 facet-parity assertions) -----------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "merge-duplicate-imports" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["merge-duplicate-imports"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "merge-duplicate-imports"


def test_facet_reachability_parity_invariant_holds():
    # The standing 1:1 invariant: the facet map reaches EXACTLY the registered
    # objectives. Adding this objective to BOTH sides keeps the equality.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_facet_phrase_is_substring_order_safe():
    # The new key must be neither a substring of, nor contain, any other key (with a
    # different objective) — else the first-match scan would mis-route.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    keys = list(FACET_OBJECTIVE_MAP)
    assert _PHRASE in keys
    for other in keys:
        if other == _PHRASE:
            continue
        assert _PHRASE not in other, f"{_PHRASE!r} is a substring of {other!r}"
        assert other not in _PHRASE, f"{other!r} is a substring of {_PHRASE!r}"


def test_manifest_classes_it_tidy_and_reverse_tripwire_clean():
    # Honest classification: this is a TIDY (it merges EXISTING lines; it lands no
    # code that did not exist), so it must NOT inflate the concrete ratio.
    from app.engine.north_star_audit import (
        OBJECTIVE_MANIFEST,
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "merge-duplicate-imports" in buckets["TIDY"]
    assert "merge-duplicate-imports" not in buckets["CONCRETE"]
    assert "merge-duplicate-imports" in OBJECTIVE_MANIFEST["TIDY"]
    # No stale manifest name (a name with no live objective) was introduced.
    assert manifest_subset_of_registry() == []


def test_facet_phrase_lives_in_the_import_direction_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["import direction"]
    assert _PHRASE in ladder
    assert ladder[0] == "an unused import"  # originals still lead


# --- the plan ----------------------------------------------------------------

def test_plan_merges_duplicate_imports(tmp_path: Path):
    _project(tmp_path, "app/mod.py", _DUP)
    plan = plan_merge_duplicate_imports(str(tmp_path), "app/mod.py")
    assert plan.ok
    new = plan.new_contents["app/mod.py"]
    assert "from collections import OrderedDict, defaultdict" in new
    assert plan.originals["app/mod.py"] == _DUP  # original captured for rollback
    assert plan.edits_by_file["app/mod.py"] == 1


def test_plan_noop_when_nothing_to_merge(tmp_path: Path):
    _project(tmp_path, "app/mod.py", "from m import a, b\n")
    plan = plan_merge_duplicate_imports(str(tmp_path), "app/mod.py")
    assert not plan.new_contents
    assert not plan.blockers


def test_plan_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _DUP)
    assert not plan_merge_duplicate_imports(str(tmp_path), "tests/test_x.py").new_contents


def test_plan_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", _DUP)
    assert not plan_merge_duplicate_imports(
        str(tmp_path), "fixtures/sample.py").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_merge_duplicate_imports(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: gated apply, real landing, suite stays green ----------------

def test_end_to_end_lands_merge_and_keeps_green(tmp_path: Path):
    _suite_project(tmp_path)
    (tmp_path / "app" / "mod.py").write_text(
        "from collections import OrderedDict\n"
        "from collections import defaultdict\n"
        "\n"
        "\n"
        "def build():\n"
        "    d = defaultdict(list)\n"
        "    d['k'].append(OrderedDict())\n"
        "    return d\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_mod.py").write_text(
        "from app.mod import build\n"
        "def test_build():\n"
        "    assert list(build()['k'][0]) == []\n",
        encoding="utf-8")

    plan = plan_merge_duplicate_imports(str(tmp_path), "app/mod.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "mod.py").read_text(encoding="utf-8")
    assert "from collections import OrderedDict, defaultdict" in landed
    assert landed.count("from collections import") == 1  # the two lines merged


def test_binding_preservation_every_name_importable_before_is_importable_after(
    tmp_path: Path,
):
    # The binding-preservation oracle: import the module BEFORE and AFTER the merge in
    # a fresh namespace and assert the set of names it binds is byte-for-byte the same
    # (proves no binding was lost or added — the multiset is preserved at RUNTIME, not
    # just structurally).
    src = (
        "from collections import OrderedDict\n"
        "from collections import defaultdict\n"
        "from collections import Counter\n"
    )

    def _bound_names(text: str) -> set[str]:
        ns: dict[str, object] = {}
        exec(compile(text, "<merge-test>", "exec"), ns)  # noqa: S102
        return {k for k in ns if not k.startswith("__")}

    before = _bound_names(src)
    merged = merge_duplicate_imports(src)
    assert merged is not None
    after = _bound_names(merged)
    assert before == after == {"OrderedDict", "defaultdict", "Counter"}
