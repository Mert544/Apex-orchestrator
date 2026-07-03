"""finalize-module-constant develop objective — LAND ``typing.Final`` on a
project's own top-level module CONSTANT (``NAME = <literal>``, UPPER_SNAKE) that is
PROVABLY never REBOUND anywhere in the project.

``typing.Final`` is a PURE runtime no-op (CPython does NOT enforce it — it is a
type-checker-only marker), so annotating a never-rebound constant ``Final`` is
behaviour-preserving BY CONSTRUCTION — there is nothing at runtime to break, UNLIKE
a ``let``->``const`` rewrite which throws at runtime if wrong. This is the Python
analogue of the shipped ``add-final`` (class ``@final``) / ``java-final-local``
family. The only honesty risk is a FALSE "final" on a name that IS rebound; that is
closed STRUCTURALLY by a whole-project over-approximate REBIND scan (tests INCLUDED),
NOT by the suite — which is exactly why the never-fake-green guard is structural: a
rebound name is never annotated even though the no-op ``Final`` would keep the suite
green (a fake-green the structural scan forbids).

Covers: the core transform (fresh import insert; widen an existing ``from typing
import ...``; the dotted ``typing.Final`` fallback when ``Final`` is shadowed but
``typing`` is bound; preserving an existing declared type as ``Final[T]``;
indentation / trailing-newline preservation) plus EVERY refusal — rebound anywhere
(plain ``NAME = ...``, augmented, ``global`` inside a function, another module),
already ``Final`` / ``typing.Final``, lower-case / dunder name, non-literal value,
tuple-unpack / multi-target, annotation-only ``NAME: T``, a shadowed ``Final`` with
no usable ``typing``, test/fixture, syntax error; plus in-place mutation being FINE
(``Final`` forbids rebinding, not mutation); idempotency and determinism; the
whole-project rebind over-approximation; objective registration / reachability (the
SIX parity registries the new objective must appear in); the END-TO-END landing
(``apply_rename`` verify=True adds ``Final`` in place and the suite stays green); the
never-fake-green guarantee (a rebound constant is NOT annotated); and the must-refuse
on the soundness corpus's ``reassigned_constant`` trap.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.final_constant import (
    add_final_constant,
    assignment_is_final_annotated,
    finalizable_constants,
    rebound_names,
)
from app.execution.objectives.finalize_constant import plan_finalize_constant

# A module with one never-rebound UPPER_SNAKE literal constant: gains a fresh
# ``from typing import Final`` + ``MAX_RETRIES: Final``.
_LEAF = (
    '"""A leaf module."""\n'
    "\n"
    "\n"
    "MAX_RETRIES = 3\n"
    "\n"
    "\n"
    "def attempt() -> int:\n"
    "    return MAX_RETRIES\n"
)

_PHRASE = "the never-rebound python module constant to seal as final"


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


# --- the core transform: detection ------------------------------------------

def test_finalizable_detects_never_rebound_constant():
    assert finalizable_constants(_LEAF) == ["MAX_RETRIES"]


def test_assignment_is_final_annotated_true_for_bare_final():
    node = ast.parse("MAX: Final = 3\n").body[0]
    assert assignment_is_final_annotated(node)


def test_assignment_is_final_annotated_true_for_dotted_and_subscript():
    dotted = ast.parse("MAX: typing.Final = 3\n").body[0]
    subscript = ast.parse("MAX: Final[int] = 3\n").body[0]
    assert assignment_is_final_annotated(dotted)
    assert assignment_is_final_annotated(subscript)


def test_assignment_is_final_annotated_false_for_plain_and_other_annotation():
    plain = ast.parse("MAX = 3\n").body[0]
    typed = ast.parse("MAX: int = 3\n").body[0]
    assert not assignment_is_final_annotated(plain)
    assert not assignment_is_final_annotated(typed)


# --- the core transform: rewrite --------------------------------------------

def test_adds_final_and_fresh_typing_import():
    out = add_final_constant(_LEAF)
    assert out is not None
    lines = out.splitlines()
    assert lines[0] == '"""A leaf module."""'  # docstring stays first
    assert "from typing import Final" in lines
    # import lands before the annotated constant
    assert lines.index("from typing import Final") < lines.index("MAX_RETRIES: Final = 3")
    assert "MAX_RETRIES: Final = 3" in out
    ast.parse(out)  # never lands broken Python


def test_widens_existing_typing_import_in_place():
    src = "from typing import Any\n\n\nMAX = 3\n"
    out = add_final_constant(src)
    assert out is not None
    assert out.count("from typing import") == 1  # widened, not a second line
    assert out.splitlines()[0] == "from typing import Any, Final"
    assert "MAX: Final = 3" in out
    ast.parse(out)


def test_preserves_existing_declared_type_as_final_subscript():
    src = "from typing import Final\n\nTIMEOUT: int = 5\n"
    out = add_final_constant(src)
    assert out is not None
    # the declared ``int`` is carried inside ``Final[int]`` (not discarded)
    assert "TIMEOUT: Final[int] = 5" in out
    ast.parse(out)


def test_uses_dotted_typing_final_when_final_name_is_shadowed():
    # ``Final`` is shadowed by a module-level assignment, but ``typing`` is bound
    # bare — so the dotted ``typing.Final`` is provable and used, and NO ``from
    # typing import Final`` is added (which would re-bind the shadowed name).
    src = "import typing\n\nFinal = object()\n\nMAX = 3\n"
    out = add_final_constant(src)
    assert out is not None
    assert "MAX: typing.Final = 3" in out
    assert "from typing import Final" not in out
    ast.parse(out)


def test_handles_negative_numeric_literal():
    out = add_final_constant("OFFSET = -5\n")
    assert out is not None
    assert "OFFSET: Final = -5" in out
    ast.parse(out)


def test_preserves_trailing_newline_absence():
    # No trailing newline in, none out (the rejoin guard preserves it).
    assert add_final_constant("MAX = 3").endswith("MAX: Final = 3")


# --- refusals (the never-fake-green boundary), one shape per test ------------

def test_refuses_rebound_by_later_plain_assignment():
    # A later ``MAX = 4`` in the SAME module rebinds it — ``Final`` would be a type
    # error. Non-tautological: WITHOUT the rebind scan the first ``MAX = 3`` looks
    # finalizable.
    assert add_final_constant("MAX = 3\nMAX = 4\n") is None
    assert finalizable_constants("MAX = 3\nMAX = 4\n") == []


def test_refuses_rebound_by_global_assignment_in_function():
    src = "MAX = 3\n\n\ndef bump() -> None:\n    global MAX\n    MAX = 9\n"
    assert add_final_constant(src) is None


def test_refuses_rebound_by_augmented_assignment():
    src = "MAX = 3\n\n\ndef bump() -> None:\n    global MAX\n    MAX += 1\n"
    assert add_final_constant(src) is None


def test_refuses_already_final_annotated():
    src = "from typing import Final\n\nMAX: Final = 3\n"
    assert add_final_constant(src) is None  # idempotent no-op


def test_refuses_lowercase_and_dunder_names():
    assert add_final_constant("config = 3\n") is None       # not UPPER_SNAKE
    assert add_final_constant("__version__ = '1'\n") is None  # dunder metadata


def test_refuses_non_literal_value():
    assert add_final_constant("MAX = compute()\n") is None
    assert add_final_constant("OTHER = MAX\n") is None
    assert add_final_constant("ITEMS = [1, 2]\n") is None  # container is not a plain literal


def test_refuses_tuple_unpack_and_multi_target():
    assert add_final_constant("A, B = 1, 2\n") is None       # unpack
    assert add_final_constant("A = B = 1\n") is None         # chained targets


def test_refuses_annotation_only_no_value():
    assert add_final_constant("MAX: int\n") is None  # no value to seal


def test_refuses_final_name_shadowed_with_no_usable_typing():
    # ``Final`` is shadowed AND ``typing`` is not bound bare, so neither the bare nor
    # the dotted spelling is provable — refuse rather than annotate under an
    # unprovable ``Final`` name.
    src = "Final = object()\n\nMAX = 3\n"
    assert add_final_constant(src) is None


def test_refuses_constant_defined_inside_function_or_class():
    # A ``NAME = <literal>`` inside a function/class body is NOT a top-level module
    # constant — out of scope (only ``tree.body`` statements are candidates).
    assert add_final_constant("def f():\n    MAX = 3\n    return MAX\n") is None
    assert add_final_constant("class C:\n    MAX = 3\n") is None


def test_refuses_syntax_error():
    assert add_final_constant("MAX = (\n") is None
    assert finalizable_constants("MAX = (\n") == []


# --- in-place mutation is FINE (Final forbids REBINDING, not mutation) -------

def test_in_place_mutation_is_not_a_rebind():
    # ``NAMES = ("a",)`` is a tuple literal — but tuples are ``ast.Constant`` only
    # when empty; a non-empty tuple is a ``Tuple`` node, NOT a plain literal, so it
    # is out of scope for a different reason. To isolate the MUTATION point we use a
    # scalar the rebind scan tracks: an attribute/subscript STORE whose base is the
    # constant name must NOT count as a rebind of the name itself.
    src = (
        "CONFIG = 3\n"
        "\n"
        "\n"
        "def touch(obj) -> None:\n"
        "    obj.CONFIG = 9      # attribute store on an UNRELATED object, not CONFIG\n"
    )
    out = add_final_constant(src)
    assert out is not None  # the attribute store is not a rebind of the name CONFIG
    assert "CONFIG: Final = 3" in out
    # rebound_names must NOT contain CONFIG from an attribute-store on some object
    rebound = rebound_names([src], src, ast.parse(src).body[0])
    assert "CONFIG" not in rebound


# --- whole-project rebind over-approximation --------------------------------

def test_rebind_scan_spans_multiple_sources():
    # ``MAX`` is declared in one module and REBOUND in another — the whole-project
    # scan sees the cross-module reassignment and refuses.
    own = "MAX = 3\n"
    other = "from pkg.a import MAX as _M\nMAX = 4\n"  # a rebind in another file
    rebound = rebound_names([own, other], own, ast.parse(own).body[0])
    assert "MAX" in rebound


def test_rebind_scan_excludes_the_declaration_itself():
    own = "MAX = 3\n"
    rebound = rebound_names([own], own, ast.parse(own).body[0])
    assert "MAX" not in rebound  # its OWN declaration is not a rebind of itself


# --- idempotency + determinism ----------------------------------------------

def test_idempotent_second_run_lands_next_then_noops():
    src = '"""m."""\n\n\nMAX = 3\nTIMEOUT = 5\n'
    first = add_final_constant(src)
    assert first is not None and "MAX: Final = 3" in first
    second = add_final_constant(first)  # lands the NEXT constant
    assert second is not None and "TIMEOUT: Final = 5" in second
    assert add_final_constant(second) is None  # both sealed — a byte-identical no-op


def test_deterministic_repeated_calls_identical():
    assert add_final_constant(_LEAF) == add_final_constant(_LEAF)


# --- the plan (refuses test/fixture, captures original) ---------------------

def test_plan_lands_on_own_module(tmp_path: Path):
    _project(tmp_path, "app/core.py", _LEAF)
    plan = plan_finalize_constant(str(tmp_path), "app/core.py")
    assert plan.new_contents
    landed = plan.new_contents["app/core.py"]
    assert "MAX_RETRIES: Final = 3" in landed
    assert plan.originals["app/core.py"] == _LEAF  # original captured for rollback


def test_plan_refuses_test_file(tmp_path: Path):
    _project(tmp_path, "tests/test_thing.py", _LEAF)
    plan = plan_finalize_constant(str(tmp_path), "tests/test_thing.py")
    assert not plan.new_contents  # never rewrite a test file


def test_planning_never_touches_the_real_tree(tmp_path: Path):
    _project(tmp_path, "app/core.py", _LEAF)
    before = (tmp_path / "app" / "core.py").read_text(encoding="utf-8")
    plan = plan_finalize_constant(str(tmp_path), "app/core.py")
    assert plan.new_contents
    assert (tmp_path / "app" / "core.py").read_text(encoding="utf-8") == before


# --- registration / facet+manifest+soundness 1:1 parity (always runs) --------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "finalize-module-constant" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["finalize-module-constant"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is False    # pure-Python AST scan; no subprocess
    assert spec.scope_verify is False  # runtime-noop annotation; no red-baseline veto


def test_objective_total_is_ninety_five():
    from app.engine.objective_compiler import available_objectives

    # 95 after finalize-module-constant (the Python module-constant sibling of the
    # add-final / java-final-* runtime-noop-seal family).
    assert len(set(available_objectives())) == 96  # 95 -> 96: dedup-guarded-return


# --- PARITY ROW 1: move_value tier (matches add-final's runtime-noop tier) ---

def test_parity_move_value_matches_add_final_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("finalize_module_constant") == 0.34
    assert move_value("finalize_module_constant") == move_value("add_final")
    assert move_value("finalize_module_constant") == move_value("java_final_local")
    assert objective_value("finalize-module-constant") == 0.34
    assert objective_value("finalize-module-constant") != DEFAULT_VALUE


# --- PARITY ROW 2: north-star manifest ---------------------------------------

def test_parity_manifest_classifies_concrete():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())  # raises if unclassified
    assert "finalize-module-constant" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


def test_parity_concrete_count_is_fifty():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert len(buckets["CONCRETE"]) == 50  # finalize-module-constant (50th CONCRETE)


# --- PARITY ROW 3: soundness-strategy manifest -------------------------------

def test_parity_soundness_strategy_present_and_no_scope_verify_entry():
    from app.engine.objective_compiler import available_objectives
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_completeness,
        strategy_subset_of_registry,
    )

    sc = strategy_completeness(available_objectives())  # raises if undeclared
    assert "finalize-module-constant" in sc
    assert SOUNDNESS_STRATEGY["finalize-module-constant"]  # non-empty strategy string
    assert "finalize-module-constant" not in SCOPE_VERIFY_ALLOWLIST  # scope_verify off
    assert strategy_subset_of_registry() == []  # no stale strategy name


# --- PARITY ROW 4 + 5: facet map and ladder ----------------------------------

def test_parity_facet_routes_and_one_to_one_holds():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP, facet_to_objective
    from app.engine.objective_compiler import available_objectives

    assert facet_to_objective(_PHRASE) == "finalize-module-constant"
    # the standing 1:1 invariant: the facet map reaches EXACTLY the registry.
    assert len(set(FACET_OBJECTIVE_MAP.values())) == len(set(available_objectives()))
    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_parity_facet_phrase_is_substring_order_safe():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    keys = list(FACET_OBJECTIVE_MAP)
    assert _PHRASE in keys
    for other in keys:
        if other == _PHRASE:
            continue
        assert _PHRASE not in other, f"{_PHRASE!r} is a substring of {other!r}"
        assert other not in _PHRASE, f"{other!r} is a substring of {_PHRASE!r}"


def test_parity_facet_phrase_lives_in_extension_points_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["extension points"]
    assert _PHRASE in ladder
    # the java-final-local sibling stays directly before it (appended right after).
    assert ladder[ladder.index(_PHRASE) - 1] == (
        "the never-reassigned java local variable to finalize")


# --- PARITY ROW 6: vocabulary concept routing --------------------------------

def test_parity_vocabulary_final_concept_includes_the_new_slug():
    from app.intent.vocabulary import CONCEPT_VOCAB

    final_entry = next(objs for phrase, objs in CONCEPT_VOCAB if phrase == "final")
    assert "finalize-module-constant" in final_entry


# --- the two RAISE-on-drift audits both pass ---------------------------------

def test_north_star_and_soundness_audits_pass():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


# --- must-refuse on the soundness-corpus fixture (the reassigned-constant trap) --

def test_refuses_on_reassigned_constant_corpus_shape():
    # The standing soundness corpus carries a Python reassigned-constant trap: a
    # top-level UPPER_SNAKE constant that LOOKS never-rebound from its declaration
    # alone but is REASSIGNED later in the SAME module (via a ``global`` bump, and a
    # plain module-scope rebind of a second constant) — so ``typing.Final`` would be
    # a TYPE ERROR. finalize-module-constant MUST refuse it — the whole-project
    # rebind scan catches both reassignments. Non-tautological: WITHOUT the rebind
    # scan the constants would wrongly be sealed ``Final``.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), only={"finalize-module-constant"})
    cells = corpus.get("finalize-module-constant", {})
    assert cells, "finalize-module-constant should be swept in the corpus"
    assert cells.get("reassigned_constant") == "refused"
    # Every OTHER shape must also stay a clean refusal (none carries a top-level
    # never-rebound UPPER_SNAKE literal constant eligible for the seal).
    for shape, verdict in cells.items():
        assert verdict == "refused", f"{shape}: {verdict}"


# --- END-TO-END: the seal lands and the suite stays green --------------------

def test_end_to_end_lands_final_and_keeps_green(tmp_path: Path):
    _suite_project(tmp_path)
    src = (
        '"""A leaf module."""\n'
        "\n"
        "\n"
        "MAX_RETRIES = 3\n"
        "\n"
        "\n"
        "def attempt() -> int:\n"
        "    return MAX_RETRIES\n"
    )
    (tmp_path / "app" / "core.py").write_text(src, encoding="utf-8")
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import MAX_RETRIES, attempt\n"
        "def test_attempt():\n"
        "    assert attempt() == 3\n"
        "def test_value():\n"
        "    assert MAX_RETRIES == 3\n",
        encoding="utf-8")

    plan = plan_finalize_constant(str(tmp_path), "app/core.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "core.py").read_text(encoding="utf-8")
    assert "MAX_RETRIES: Final = 3" in landed  # the annotation LANDED
    assert "from typing import Final" in landed
    # Behaviour preserved (proven green by the apply gate running the tests above):
    # the constant still holds 3 and the function still reads it.
    assert "def attempt() -> int:" in landed


def test_never_fake_green_rebound_constant_is_not_finalized(tmp_path: Path):
    # never-fake-green, STRUCTURAL form. ``typing.Final`` is a pure runtime no-op, so
    # annotating a REBOUND constant would NOT break the suite — the suite would stay
    # green on a FALSE "final" claim (a type checker would later reject the
    # reassignment). The honesty guard is therefore the whole-project rebind scan,
    # not the suite: ``MAX_RETRIES`` is provably rebound (a ``global`` bump), so the
    # engine REFUSES to annotate it.
    src = (
        "MAX_RETRIES = 3\n"
        "\n"
        "\n"
        "def bump() -> int:\n"
        "    global MAX_RETRIES\n"
        "    MAX_RETRIES = MAX_RETRIES + 1\n"
        "    return MAX_RETRIES\n"
    )
    _project(tmp_path, "app/core.py", src)
    plan = plan_finalize_constant(str(tmp_path), "app/core.py")
    assert not plan.new_contents  # refused — the rebind scan forbids the false seal
