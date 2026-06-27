"""seal-hashable-eq develop objective — RESTORE the canonical field-based ``__hash__``
on a project's own regular (non-``@dataclass``) class that defines ``__eq__`` in its OWN
body but does NOT define ``__hash__`` and is NOT already deliberately unhashable.

THE PYTHON RULE: defining ``__eq__`` sets ``__hash__ = None`` IMPLICITLY, so instances
become UNHASHABLE (``TypeError: unhashable type`` in a ``set`` / ``dict`` key). Authors
routinely forget to restore the ``__hash__`` that pairs with their ``__eq__``. This lands
the canonical ``def __hash__(self): return hash((self.f1, self.f2, ...))`` over the SAME
proven pure-copy field set ``synthesize_dunders`` already trusts — RESTORING set/dict-key
usability where instances currently raise at runtime (a real landed capability, the
``__hash__`` sibling of synthesize-dunders). The change is RUNTIME-ADDITIVE (it re-enables
a hard ``TypeError``); the residual (a field whose own value is unhashable) is caught by
the suite gate + auto-rollback. The honesty rail is PURELY INTRA-MODULE: a body-``__eq__``
``def`` present, NO ``__hash__`` (def OR binding, incl. ``__hash__ = None``), NO base other
than ``object`` (so the hash contract is the class's OWN), and a non-empty enumerable
pure-copy field set.

Covers: the core transform (canonical ``__hash__`` over the copy fields; field order
matches ``__init__``; single-field trailing-comma tuple; indentation / docstring preserved;
reverse-source-order multi-class splice; trailing-newline preservation) plus EVERY refusal —
no body-``__eq__``, an inherited-only ``__eq__``, an already-present ``def __hash__``,
``__hash__ = None`` (deliberate unhashable), ``__hash__ = other`` (hand-written hash),
``@dataclass``, a base other than ``object``, an Enum base, a non-enumerable
(``*args`` / ``**kwargs``) signature, an empty proven field set, no ``__init__``, an
``__eq__`` bound by assignment / lambda, a syntax error; plus idempotency and determinism
(across ``PYTHONHASHSEED``); objective registration / reachability (available, callable
spec, NOT expensive / NOT scope_verify, reachable-from-facet, the facet-map<->registry 1:1
parity invariant, substring-safety, the north-star manifest classing it CONCRETE with the
reverse tripwire clean, the move-value tier + no-phantom-row, the soundness strategy
declared + not scope_verify, the facet ladder carrying the phrase with the originals still
leading, both RAISE-on-drift audits PASS, the 30/72 counts); the plan + END-TO-END landing
(``apply_rename`` verify=True splices the ``__hash__`` in place, the suite stays green, and
an instance becomes set-insertable where it raised before); the must-refuse sweep over the
Python soundness corpus; and the never-fake-green capstone (a refusal case lands nothing
before any apply).
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from app.execution.cross_file_rename import apply_rename
from app.execution.hashable_eq import hashable_eq_classes, seal_hashable_eq
from app.execution.objectives.seal_hashable_eq import plan_seal_hashable_eq

_PHRASE = "the hash to restore from the eq fields"

# A regular plumbing class (non-@dataclass) that defines a value-``__eq__`` in its own
# body but no ``__hash__`` — so its instances are UNHASHABLE (``__hash__ = None``
# implicitly) until seal-hashable-eq restores the canonical ``__hash__`` over the proven
# ``self.x`` / ``self.y`` copy fields.
_UNHASHABLE = (
    '"""A point module."""\n'
    "\n"
    "\n"
    "class Point:\n"
    "    def __init__(self, x, y):\n"
    "        self.x = x\n"
    "        self.y = y\n"
    "\n"
    "    def __eq__(self, other):\n"
    "        return isinstance(other, Point) and (self.x, self.y) == (other.x, other.y)\n"
)

# Reusable body fragments.
_INIT = "    def __init__(self, x):\n        self.x = x\n"
_EQ = "    def __eq__(self, o):\n        return isinstance(o, type(self)) and self.x == o.x\n"


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


def _exec(source: str) -> dict:
    """Compile + exec ``source`` and return its namespace — to assert RUNTIME behaviour
    of the restored ``__hash__``, not just its text."""
    ns: dict = {}
    exec(compile(source, "<hash>", "exec"), ns)  # noqa: S102 - test-only
    return ns


# --- the core transform: detection ------------------------------------------

def test_detects_eq_without_hash():
    assert hashable_eq_classes(_UNHASHABLE) == ["Point"]


def test_detects_explicit_object_base():
    src = "class C(object):\n" + _INIT + _EQ
    assert hashable_eq_classes(src) == ["C"]


def test_detects_none_when_already_hashable():
    src = "class C:\n" + _INIT + _EQ + "    def __hash__(self):\n        return 1\n"
    assert hashable_eq_classes(src) == []


# --- the core transform: rewrite --------------------------------------------

def test_restores_canonical_hash_over_copy_fields():
    out = seal_hashable_eq(_UNHASHABLE)
    assert out is not None
    ast.parse(out)  # never lands broken Python
    assert "def __hash__(self) -> int:" in out
    assert "return hash((self.x, self.y))" in out
    # the original body (docstring, __init__, __eq__) is preserved untouched
    assert '"""A point module."""' in out
    assert "def __init__(self, x, y):" in out
    assert out.count("def __eq__") == 1


def test_restored_hash_makes_instance_set_and_dict_usable():
    out = seal_hashable_eq(_UNHASHABLE)
    assert out is not None
    cls = _exec(out)["Point"]
    # value-equal instances collapse in a set and key the same dict slot.
    assert len({cls(1, 2), cls(1, 2), cls(3, 4)}) == 2
    assert {cls(1, 2): "a"}[cls(1, 2)] == "a"
    assert hash(cls(1, 2)) == hash(cls(1, 2))  # consistent with __eq__


def test_field_order_matches_init():
    src = (
        "class C:\n"
        "    def __init__(self, p, q, r):\n"
        "        self.p = p\n"
        "        self.q = q\n"
        "        self.r = r\n" + _EQ
    )
    out = seal_hashable_eq(src)
    assert out is not None
    assert "return hash((self.p, self.q, self.r))" in out  # source order, not sorted


def test_single_field_emits_trailing_comma_tuple():
    src = "class C:\n" + _INIT + _EQ
    out = seal_hashable_eq(src)
    assert out is not None
    assert "return hash((self.x,))" in out  # 1-tuple stays a tuple
    cls = _exec(out)["C"]
    assert hash(cls(1)) == hash(cls(1))


def test_preserves_indentation_and_docstring():
    src = (
        "class C:\n"
        '    """A doc."""\n'
        "\n" + _INIT + _EQ
    )
    out = seal_hashable_eq(src)
    assert out is not None
    assert '    """A doc."""' in out  # docstring untouched
    assert "    def __hash__(self) -> int:" in out  # 4-space class-body indent


def test_reverse_source_order_multi_class_splice():
    src = (
        "class A:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "    def __eq__(self, o):\n"
        "        return isinstance(o, A) and self.a == o.a\n"
        "\n"
        "\n"
        "class B:\n"
        "    def __init__(self, b):\n"
        "        self.b = b\n"
        "    def __eq__(self, o):\n"
        "        return isinstance(o, B) and self.b == o.b\n"
    )
    out = seal_hashable_eq(src)
    assert out is not None
    ast.parse(out)
    assert out.count("def __hash__(self) -> int:") == 2
    ns = _exec(out)
    assert hash(ns["A"](1)) == hash(ns["A"](1))
    assert hash(ns["B"](2)) == hash(ns["B"](2))


def test_preserves_trailing_newline_absence():
    src = ("class C:\n    def __init__(self, x):\n        self.x = x\n"
           "    def __eq__(self, o): return self.x == o.x")
    out = seal_hashable_eq(src)
    assert out is not None and not out.endswith("\n")


# --- the core transform: REFUSALS (honest no-ops, the soundness surface) -----

def test_refuses_no_eq_in_body():
    src = "class C:\n" + _INIT + "    pass\n"
    assert seal_hashable_eq(src) is None  # no body-__eq__ — instances stayed hashable


def test_refuses_inherited_only_eq():
    # ``__eq__`` lives on a BASE class, not in this body — not provably present here, and
    # the base also means the hash contract is not the class's own — refuse.
    src = (
        "class B:\n    def __eq__(self, o):\n        return True\n"
        "class C(B):\n" + _INIT
    )
    assert seal_hashable_eq(src) is None


def test_refuses_existing_def_hash():
    src = ("class C:\n" + _INIT + _EQ
           + "    def __hash__(self):\n        return id(self)\n")
    assert seal_hashable_eq(src) is None  # author wrote their own hash — never overwrite


def test_refuses_hash_none_deliberate_unhashable():
    # ``__hash__ = None`` is the author's DELIBERATE unhashable choice — re-enabling it
    # would reverse an intended decision, so REFUSE.
    src = "class C:\n" + _INIT + _EQ + "    __hash__ = None\n"
    assert seal_hashable_eq(src) is None


def test_refuses_hash_bound_to_other_function():
    # ``__hash__ = object.__hash__`` is a hand-written hash binding — present, refuse.
    src = "class C:\n" + _INIT + _EQ + "    __hash__ = object.__hash__\n"
    assert seal_hashable_eq(src) is None


def test_refuses_dataclass_decorated():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class C:\n"
        "    x: int\n"
        "    def __eq__(self, o):\n"
        "        return self.x == o.x\n"
    )
    assert seal_hashable_eq(src) is None  # dataclassify / freeze own the eq=/hash story


def test_refuses_base_other_than_object():
    src = "class B:\n    pass\nclass C(B):\n" + _INIT + _EQ
    assert seal_hashable_eq(src) is None  # a base — the hash contract is not the class's own


def test_refuses_enum_subclass():
    src = (
        "from enum import Enum\n"
        "class Color(Enum):\n"
        "    RED = 1\n"
        "    def __eq__(self, o):\n"
        "        return True\n"
    )
    assert seal_hashable_eq(src) is None  # Enum base — out of scope


def test_refuses_class_keyword_metaclass():
    src = "class C(metaclass=type):\n" + _INIT + _EQ
    assert seal_hashable_eq(src) is None  # a class keyword — refuse (not the class's own)


def test_refuses_kwargs_capture_non_enumerable():
    src = (
        "class C:\n"
        "    def __init__(self, **kwargs):\n"
        "        for k, v in kwargs.items():\n"
        "            setattr(self, k, v)\n" + _EQ
    )
    assert seal_hashable_eq(src) is None  # not enumerable — refuse


def test_refuses_varargs_non_enumerable():
    src = "class C:\n    def __init__(self, *args):\n        self.args = args\n" + _EQ
    assert seal_hashable_eq(src) is None  # *args makes the field set non-enumerable


def test_refuses_empty_field_set():
    # An __init__ that stores no pure ``self.x = x`` copy has an empty proven field set.
    src = "class C:\n    def __init__(self, a):\n        self.b = a + 1\n" + _EQ
    assert seal_hashable_eq(src) is None  # nothing to hash over


def test_refuses_no_init():
    src = "class C:\n" + _EQ
    assert seal_hashable_eq(src) is None  # no constructor — no enumerable field set


def test_refuses_lambda_assigned_eq():
    src = "class C:\n" + _INIT + "    __eq__ = lambda self, o: True\n"
    assert seal_hashable_eq(src) is None  # __eq__ bound by lambda, not a def — refuse


def test_refuses_assignment_defined_eq():
    src = "class C:\n" + _INIT + "    __eq__ = object.__eq__\n"
    assert seal_hashable_eq(src) is None  # __eq__ bound by assignment, not a def — refuse


def test_refuses_syntax_error():
    assert seal_hashable_eq("class C(:\n") is None


def test_hashable_eq_classes_empty_on_syntax_error():
    assert hashable_eq_classes("class C(:\n") == []
    assert hashable_eq_classes("def f():\n    return 1\n") == []


# --- idempotency / determinism ----------------------------------------------

def test_idempotent_second_run_is_byte_identical_noop():
    once = seal_hashable_eq(_UNHASHABLE)
    assert once is not None
    # a second run sees the landed __hash__ -> nothing to do
    assert seal_hashable_eq(once) is None


def test_deterministic_across_two_runs():
    a = seal_hashable_eq(_UNHASHABLE)
    b = seal_hashable_eq(_UNHASHABLE)
    assert a is not None and a == b


def test_transform_is_deterministic_across_hashseed():
    snippet = (
        "from app.execution.hashable_eq import seal_hashable_eq\n"
        "src = (\n"
        "    'class C:\\n'\n"
        "    '    def __init__(self, p, q, r):\\n'\n"
        "    '        self.p = p\\n'\n"
        "    '        self.q = q\\n'\n"
        "    '        self.r = r\\n'\n"
        "    '    def __eq__(self, o):\\n'\n"
        "    '        return self.p == o.p\\n'\n"
        ")\n"
        "print(seal_hashable_eq(src))\n"
    )

    def _run(seed: str) -> str:
        env = {"PYTHONHASHSEED": seed, "PATH": __import__("os").environ.get("PATH", "")}
        out = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True, text=True, env=env,
            cwd=str(Path(__file__).resolve().parents[1]), check=True)
        return out.stdout

    first = _run("0")
    second = _run("12345")
    assert first == second
    assert "return hash((self.p, self.q, self.r))" in first


# --- registration / reachability --------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "seal-hashable-eq" in set(available_objectives())


def test_objective_spec_is_callable_and_default_flags():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["seal-hashable-eq"]
    assert callable(spec.fitness) and callable(spec.moves)
    # NOT expensive, NOT scope_verify — the in-process AST gate is cheap and a wrong
    # hash residual is a runtime mismatch the full default suite gate catches.
    assert getattr(spec, "expensive", False) is False
    assert getattr(spec, "scope_verify", False) is False


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "seal-hashable-eq"


def test_facet_reachability_parity_invariant_holds():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    # the standing 1:1 invariant: the facet map reaches EXACTLY the registry.
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


def test_facet_phrase_distinct_from_dunder_siblings():
    # Explicit spec check: substring-order-safe versus its two nearest siblings.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    repr_eq = "the repr and eq to synthesize from fields"
    cmp_ops = "the comparison operators to complete from one"
    assert FACET_OBJECTIVE_MAP[repr_eq] == "synthesize-dunders"
    assert FACET_OBJECTIVE_MAP[cmp_ops] == "seal-total-ordering"
    assert _PHRASE not in repr_eq and repr_eq not in _PHRASE
    assert _PHRASE not in cmp_ops and cmp_ops not in _PHRASE


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())  # raises if unclassified
    assert "seal-hashable-eq" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


def test_move_value_tier_matches_synthesize_dunders():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    # Tier-2 structural value, the same 0.50 band as its sibling synthesize_dunders.
    assert move_value("seal_hashable_eq") == 0.50
    assert move_value("seal_hashable_eq") == move_value("synthesize_dunders")
    assert objective_value("seal-hashable-eq") == 0.50
    assert objective_value("seal-hashable-eq") != DEFAULT_VALUE  # not the unknown fallback


def test_move_value_table_has_no_phantom_and_covers_operator():
    # Reuse the authoritative drift checks: the operator is tiered and the table has no
    # stale row (the dash->underscore convention needs no OBJECTIVE_OPERATOR).
    from tests.test_move_value import _emitted_operators
    from app.engine.move_value import OPERATOR_VALUE

    ops = _emitted_operators()
    assert "seal_hashable_eq" in ops
    assert sorted(op for op in ops if op not in OPERATOR_VALUE) == []
    assert sorted(op for op in OPERATOR_VALUE if op not in ops) == []


def test_soundness_strategy_declared_and_not_scope_verify():
    from app.engine.objective_compiler import available_objectives
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_completeness,
        strategy_subset_of_registry,
    )

    sc = strategy_completeness(available_objectives())  # raises if undeclared
    assert "seal-hashable-eq" in sc
    assert (
        SOUNDNESS_STRATEGY["seal-hashable-eq"]
        == "runtime-additive(restored-__hash__)+own-body-eq-present+no-__hash__-defined"
        "+canonical-over-proven-fields+static-refusal"
    )
    assert "seal-hashable-eq" not in SCOPE_VERIFY_ALLOWLIST  # full-suite gated
    assert strategy_subset_of_registry() == []  # no stale strategy entry


def test_facet_phrase_lives_in_the_noop_statements_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["unreachable or no-op statements"]
    assert _PHRASE in ladder
    assert ladder[0] == "redundant pass statement"  # originals still lead
    # The synthesize-dunders sibling phrase still precedes the new one.
    assert ladder.index(
        "the repr and eq to synthesize from fields") < ladder.index(_PHRASE)


def test_counts_are_thirty_six_concrete_of_seventy_eight():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    names = set(available_objectives())
    assert len(names) == 80  # 80 after document-returns (38th concrete) registered
    assert len(classify_objectives(names)["CONCRETE"]) == 38


def test_north_star_and_soundness_audits_pass():
    # The two RAISE-on-drift audits both PASS with the new objective wired (parity 1:1).
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"


def test_refuses_on_python_soundness_corpus():
    # Every adversarial corpus shape: seal-hashable-eq must REFUSE (none carries the
    # body-eq + no-__hash__ + no-base shape) — never land a change.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    findings = corpus_refusal_findings(repo_root())
    verdicts = findings.get("seal-hashable-eq", {})
    assert verdicts  # the objective was swept
    for shape, verdict in verdicts.items():
        assert verdict in ("refused", "behavior-identical"), (shape, verdict)
        assert not verdict.startswith("VIOLATION"), (shape, verdict)


# --- the plan: an eligible module gets the restored __hash__ -----------------

def test_plan_lands_hash_on_eligible_module(tmp_path: Path):
    _project(tmp_path, "app/point.py", _UNHASHABLE)
    plan = plan_seal_hashable_eq(str(tmp_path), "app/point.py")
    assert plan.new_contents
    new = plan.new_contents["app/point.py"]
    assert "def __hash__(self) -> int:" in new
    assert "return hash((self.x, self.y))" in new
    ast.parse(new)
    assert plan.originals["app/point.py"] == _UNHASHABLE  # original captured for rollback
    assert plan.edits_by_file["app/point.py"] == 1


def test_plan_refuses_no_eq_class(tmp_path: Path):
    _project(tmp_path, "app/point.py", "class C:\n" + _INIT + "    pass\n")
    assert not plan_seal_hashable_eq(str(tmp_path), "app/point.py").new_contents


def test_plan_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _UNHASHABLE)
    assert not plan_seal_hashable_eq(str(tmp_path), "tests/test_x.py").new_contents


def test_plan_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", _UNHASHABLE)
    assert not plan_seal_hashable_eq(str(tmp_path), "fixtures/sample.py").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_seal_hashable_eq(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: gated apply, real landing, suite stays green ----------------

def test_end_to_end_lands_hash_and_instance_becomes_set_insertable(tmp_path: Path):
    _suite_project(tmp_path)
    src = (
        "class Coord:\n"
        "    def __init__(self, x, y):\n"
        "        self.x = x\n"
        "        self.y = y\n"
        "\n"
        "    def __eq__(self, other):\n"
        "        return isinstance(other, Coord) and (self.x, self.y) == (other.x, other.y)\n"
    )
    (tmp_path / "app" / "coord.py").write_text(src, encoding="utf-8")
    # The test PINS the restored capability: a Coord must be usable as a set member /
    # dict key. On the ORIGINAL (unhashable) source this test would raise TypeError —
    # so the apply gate's green run proves the __hash__ genuinely landed.
    (tmp_path / "tests" / "test_coord.py").write_text(
        "from app.coord import Coord\n"
        "def test_set_and_dict_usable():\n"
        "    s = {Coord(1, 2), Coord(1, 2), Coord(3, 4)}\n"
        "    assert len(s) == 2\n"
        "    assert {Coord(1, 2): 'a'}[Coord(1, 2)] == 'a'\n",
        encoding="utf-8")

    plan = plan_seal_hashable_eq(str(tmp_path), "app/coord.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "coord.py").read_text(encoding="utf-8")
    assert "def __hash__(self) -> int:" in landed  # the __hash__ LANDED

    # Prove the capability directly: the landed class is set-insertable where the
    # ORIGINAL (no __hash__) raised TypeError.
    orig_ns = _exec(src)
    with pytest.raises(TypeError):
        {orig_ns["Coord"](1, 2)}  # noqa: B015 - asserting the unhashable baseline raised
    cls = _exec(landed)["Coord"]
    assert len({cls(1, 2), cls(1, 2), cls(3, 4)}) == 2  # now hashable + value-deduped


def test_never_lands_hash_on_ineligible_class(tmp_path: Path):
    # The behavioural soundness capstone. A class that deliberately set ``__hash__ =
    # None`` is NOT eligible (the author chose unhashable), so the static rail REFUSES it
    # before any apply — the change that would reverse the author's decision never lands.
    _project(tmp_path, "app/ineligible.py",
             "class C:\n" + _INIT + _EQ + "    __hash__ = None\n")
    plan = plan_seal_hashable_eq(str(tmp_path), "app/ineligible.py")
    assert not plan.new_contents  # refused before any apply
