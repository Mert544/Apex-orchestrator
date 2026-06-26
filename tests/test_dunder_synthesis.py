"""synthesize-dunders develop objective — LAND the canonical ``__repr__`` / ``__eq__`` /
``__hash__`` over a class's PROVEN field set. The SIBLING of dataclassify for the regular
(non-``@dataclass``) classes dataclassify must REFUSE — a class whose ``__init__`` is pure
``self.x = x`` copies but that has a base, an extra method, or a real ``__init__`` body —
but that still deserves the value semantics ``@dataclass`` would have given it for free.

It splices ONLY the canonical TOTAL forms ``@dataclass`` itself emits (already trusted via
dataclassify) over the PROVEN pure-copy field set, so the change is an honest under-claim.
A wrong synthesized ``__eq__`` is a RUNTIME difference the suite catches (and
``apply_rename`` byte-rolls-back); the static honesty rail is the INHERITED-``__eq__``
refusal — a class that would silently override an inherited (or external / un-resolvable)
``__eq__`` is refused that dunder.

Covers: the core transform (a plumbing class missing both dunders -> ``__repr__`` +
``__eq__`` + ``__hash__`` spliced, output re-parses, RUNTIME behaviour correct;
idempotent 2nd run; only-``__repr__``-missing -> only repr, NO ``__hash__``, ``__eq__``
untouched; single-field trailing-comma tuple; reverse-source-order multi-class splice);
EVERY refusal (a base that defines ``__eq__`` -> ``__eq__`` refused but ``__repr__`` still
added; an external / un-resolvable base -> same; a clean resolvable base -> both added;
``setattr`` / ``**kwargs`` non-enumerable -> refused entirely; an already-``@dataclass``
class -> refused; an ``__eq__ = ...`` binding present -> ``__eq__`` refused; an empty proven
field set -> refused; unparseable source -> ``None``); idempotency and determinism (across
``PYTHONHASHSEED``); objective registration / reachability (available, callable spec, not
expensive / not scope_verify, reachable-from-facet, the facet-map<->registry 1:1 parity
invariant, substring-safety, the north-star manifest classing it CONCRETE with the reverse
tripwire clean, the soundness-strategy manifest carrying it with NO SCOPE_VERIFY_ALLOWLIST
entry, the facet ladder carrying the phrase with the originals still leading, the move-value
tier); and the END-TO-END landing (``apply_rename`` verify=True splices the dunders in place
and the suite stays green).
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.dunder_synthesis import synthesize_dunders, synthesizable_classes
from app.execution.objectives.synthesize_dunders import plan_synthesize_dunders

_PHRASE = "the repr and eq to synthesize from fields"

# A regular plumbing class that dataclassify REFUSES (it has a real method beyond the
# copies) but whose pure ``self.x = x`` copies are a provable field set, missing both
# ``__repr__`` and ``__eq__``.
_PLUMBING = (
    '"""A vector module."""\n'
    "\n"
    "\n"
    "class Vector:\n"
    "    def __init__(self, x, y):\n"
    "        self.x = x\n"
    "        self.y = y\n"
    "\n"
    "    def length(self):\n"
    "        return (self.x ** 2 + self.y ** 2) ** 0.5\n"
)


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def _exec(source: str) -> dict:
    """Compile + exec ``source`` and return its namespace — to assert RUNTIME behaviour
    of the spliced dunders, not just their text."""
    ns: dict = {}
    exec(compile(source, "<synth>", "exec"), ns)
    return ns


# --- the core transform: both dunders over a proven field set ----------------

def test_both_dunders_spliced_and_reparse():
    out = synthesize_dunders(_PLUMBING, [_PLUMBING])
    assert out is not None
    ast.parse(out)  # never lands broken Python
    assert "def __repr__(self) -> str:" in out
    assert 'return f"{type(self).__name__}(x={self.x!r}, y={self.y!r})"' in out
    assert "def __eq__(self, other: object) -> bool:" in out
    assert "if not isinstance(other, type(self)):" in out
    assert "return NotImplemented" in out
    assert "return (self.x, self.y) == (other.x, other.y)" in out
    assert "def __hash__(self) -> int:" in out
    assert "return hash((self.x, self.y))" in out
    # the original body (docstring, __init__, the extra method) is preserved
    assert '"""A vector module."""' in out
    assert "def length(self):" in out


def test_spliced_dunders_have_correct_runtime_behaviour():
    out = synthesize_dunders(_PLUMBING, [_PLUMBING])
    assert out is not None
    cls = _exec(out)["Vector"]
    assert repr(cls(1, 2)) == "Vector(x=1, y=2)"
    assert cls(1, 2) == cls(1, 2)  # value equality
    assert cls(1, 2) != cls(3, 4)
    assert (cls(1, 2) == 5) is False  # NotImplemented -> falls back to identity -> False
    assert hash(cls(1, 2)) == hash(cls(1, 2))  # hashable + consistent


def test_idempotent_second_run_is_byte_identical_noop():
    once = synthesize_dunders(_PLUMBING, [_PLUMBING])
    assert once is not None
    # a second run sees the landed dunders -> nothing to do
    assert synthesize_dunders(once, [once]) is None


def test_only_repr_missing_adds_repr_only_no_hash():
    src = (
        "class C:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "\n"
        "    def __eq__(self, other):\n"
        "        return isinstance(other, C) and self.a == other.a\n"
    )
    out = synthesize_dunders(src, [src])
    assert out is not None
    assert "def __repr__(self) -> str:" in out
    assert out.count("def __eq__") == 1  # the existing __eq__ is untouched
    assert "__hash__" not in out  # __hash__ rides ONLY with a NEWLY-added __eq__


def test_single_field_emits_trailing_comma_tuple():
    src = (
        "class C:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "\n"
        "    def note(self):\n"
        "        return self.a\n"
    )
    out = synthesize_dunders(src, [src])
    assert out is not None
    assert "(x={self.x!r})" not in out
    assert "return f\"{type(self).__name__}(a={self.a!r})\"" in out
    assert "return (self.a,) == (other.a,)" in out  # 1-tuple stays a tuple
    assert "return hash((self.a,))" in out
    cls = _exec(out)["C"]
    assert cls(1) == cls(1) and cls(1) != cls(2)


def test_reverse_source_order_multi_class_splice():
    src = (
        "class A:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "\n"
        "    def m(self):\n"
        "        return self.a\n"
        "\n"
        "\n"
        "class B:\n"
        "    def __init__(self, b):\n"
        "        self.b = b\n"
        "\n"
        "    def n(self):\n"
        "        return self.b\n"
    )
    out = synthesize_dunders(src, [src])
    assert out is not None
    ast.parse(out)
    ns = _exec(out)
    assert repr(ns["A"](1)) == "A(a=1)"
    assert repr(ns["B"](2)) == "B(b=2)"
    assert out.count("def __repr__") == 2
    assert out.count("def __eq__") == 2


# --- the inherited-__eq__ soundness gate -------------------------------------

def test_base_defines_eq_refuses_eq_but_adds_repr():
    base = (
        "class Base:\n"
        "    def __eq__(self, other):\n"
        "        return True\n"
    )
    child = (
        "class Child(Base):\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "\n"
        "    def m(self):\n"
        "        return self.a\n"
    )
    out = synthesize_dunders(child, [base, child])
    assert out is not None
    assert "def __repr__(self) -> str:" in out  # repr has no inherited contract
    assert "def __eq__" not in out  # would override the inherited __eq__ -> refused
    assert "__hash__" not in out  # rides with the (refused) __eq__


def test_transitive_base_eq_refuses_eq():
    # Child <- Mid <- Base, and Base defines __eq__ -> the transitive scan refuses __eq__.
    base = "class Base:\n    def __eq__(self, other):\n        return True\n"
    mid = "class Mid(Base):\n    pass\n"
    child = (
        "class Child(Mid):\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "\n"
        "    def m(self):\n"
        "        return self.a\n"
    )
    out = synthesize_dunders(child, [base, mid, child])
    assert out is not None
    assert "def __eq__" not in out
    assert "def __repr__(self) -> str:" in out


def test_external_unresolvable_base_refuses_eq_but_adds_repr():
    src = (
        "class Child(SomeExternal):\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "\n"
        "    def m(self):\n"
        "        return self.a\n"
    )
    out = synthesize_dunders(src, [src])  # SomeExternal not in the project scan
    assert out is not None
    assert "def __repr__(self) -> str:" in out
    assert "def __eq__" not in out  # un-resolvable base -> cannot prove safe -> refused


def test_clean_resolvable_base_without_eq_adds_both():
    base = "class Base:\n    def greet(self):\n        return 'hi'\n"
    child = (
        "class Child(Base):\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "\n"
        "    def m(self):\n"
        "        return self.a\n"
    )
    out = synthesize_dunders(child, [base, child])
    assert out is not None
    assert "def __repr__(self) -> str:" in out
    assert "def __eq__(self, other: object) -> bool:" in out  # base has no __eq__ -> safe
    assert "def __hash__(self) -> int:" in out


# --- refusals: nothing provable to splice ------------------------------------

def test_kwargs_capture_refused():
    src = (
        "class C:\n"
        "    def __init__(self, **kwargs):\n"
        "        for k, v in kwargs.items():\n"
        "            setattr(self, k, v)\n"
    )
    assert synthesize_dunders(src, [src]) is None  # not enumerable -> refused


def test_setattr_in_signature_refused():
    # ``*args`` makes the field set non-enumerable (``_init_params`` returns None).
    src = (
        "class C:\n"
        "    def __init__(self, *args):\n"
        "        self.args = args\n"
    )
    assert synthesize_dunders(src, [src]) is None


def test_already_dataclass_refused():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class C:\n"
        "    a: int\n"
    )
    assert synthesize_dunders(src, [src]) is None  # dataclassify / freeze own it


def test_eq_binding_present_refuses_eq():
    src = (
        "class C:\n"
        "    __eq__ = object.__eq__\n"
        "\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
    )
    out = synthesize_dunders(src, [src])
    assert out is not None
    assert out.count("def __eq__") == 0  # the binding counts as present -> not re-added
    assert "__hash__" not in out
    assert "def __repr__(self) -> str:" in out  # repr still added


def test_empty_field_set_is_noop():
    # An __init__ that stores no pure ``self.x = x`` copy has an empty proven field set.
    src = (
        "class C:\n"
        "    def __init__(self, a):\n"
        "        self.b = a + 1\n"
    )
    assert synthesize_dunders(src, [src]) is None


def test_no_init_is_noop():
    src = "class C:\n    pass\n"
    assert synthesize_dunders(src, [src]) is None


def test_unparseable_source_returns_none():
    assert synthesize_dunders("class C(:\n    pass\n", ["class C(:"]) is None


def test_synthesizable_classes_lists_eligible_in_isolation():
    assert synthesizable_classes(_PLUMBING) == ["Vector"]
    assert synthesizable_classes("def f():\n    return 1\n") == []
    assert synthesizable_classes("class C(:\n") == []  # syntax error -> []


# --- determinism --------------------------------------------------------------

def test_transform_is_deterministic_across_hashseed():
    snippet = (
        "from app.execution.dunder_synthesis import synthesize_dunders\n"
        "src = (\n"
        "    'class C:\\n'\n"
        "    '    def __init__(self, p, q, r):\\n'\n"
        "    '        self.p = p\\n'\n"
        "    '        self.q = q\\n'\n"
        "    '        self.r = r\\n'\n"
        "    '\\n'\n"
        "    '    def m(self):\\n'\n"
        "    '        return self.p\\n'\n"
        ")\n"
        "print(synthesize_dunders(src, [src]))\n"
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


# --- registration / reachability ---------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "synthesize-dunders" in set(available_objectives())


def test_objective_spec_is_callable_and_default_flags():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["synthesize-dunders"]
    assert callable(spec.fitness) and callable(spec.moves)
    # NOT expensive, NOT scope_verify — the in-process AST base scan is cheap and a
    # wrong dunder is a runtime mismatch the full default suite gate catches.
    assert getattr(spec, "expensive", False) is False
    assert getattr(spec, "scope_verify", False) is False


# --- PARITY ROW 1: move_value tier -------------------------------------------

def test_parity_move_value_has_synthesize_dunders_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("synthesize_dunders") == 0.50  # Tier-2, = dataclassify
    assert objective_value("synthesize-dunders") == 0.50
    assert objective_value("synthesize-dunders") != DEFAULT_VALUE  # not the unknown fallback


# --- PARITY ROW 2: north-star manifest ---------------------------------------

def test_parity_manifest_classifies_concrete():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())  # raises if unclassified
    assert "synthesize-dunders" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


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
    assert "synthesize-dunders" in sc
    assert (
        SOUNDNESS_STRATEGY["synthesize-dunders"]
        == "suite-catches-runtime+canonical-total-dunders-over-proven-fields+inherited-eq-refusal"
    )
    assert "synthesize-dunders" not in SCOPE_VERIFY_ALLOWLIST  # scope_verify stays off
    assert strategy_subset_of_registry() == []  # no stale strategy name


# --- PARITY ROW 4 + 5: facet map and ladder ----------------------------------

def test_parity_facet_routes_and_one_to_one_holds():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP, facet_to_objective
    from app.engine.objective_compiler import available_objectives

    assert facet_to_objective(_PHRASE) == "synthesize-dunders"
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


def test_parity_facet_phrase_lives_in_ladder_with_originals_leading():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["unreachable or no-op statements"]
    assert _PHRASE in ladder
    # synthesize-dunders was appended after the originals; a LATER objective
    # (seal-total-ordering) appended its own phrase after this one, so this phrase is
    # no longer the very last entry — but it stays strictly after every original.
    assert ladder.index(_PHRASE) >= 2  # the two originals still lead
    assert ladder[0] == "redundant pass statement"  # originals still lead
    # the add-slots sibling stays directly before it.
    assert ladder[ladder.index(_PHRASE) - 1] == "the closed-attribute class to give slots"


# --- the plan: an eligible module gets dunders -------------------------------

def test_plan_lands_dunders_on_eligible_module(tmp_path: Path):
    _project(tmp_path, "app/vector.py", _PLUMBING)
    plan = plan_synthesize_dunders(str(tmp_path), "app/vector.py")
    assert plan.new_contents
    new = plan.new_contents["app/vector.py"]
    assert "def __repr__(self) -> str:" in new
    assert "def __eq__(self, other: object) -> bool:" in new
    assert "def __hash__(self) -> int:" in new
    ast.parse(new)
    assert plan.originals["app/vector.py"] == _PLUMBING  # original captured for rollback
    assert plan.edits_by_file["app/vector.py"] == 1


def test_plan_refuses_test_file(tmp_path: Path):
    # plan_source_rewrite refuses a test/fixture file outright (an honest no-op).
    _project(tmp_path, "tests/test_vector.py", _PLUMBING)
    plan = plan_synthesize_dunders(str(tmp_path), "tests/test_vector.py")
    assert not plan.new_contents


def test_plan_empty_on_clean_module(tmp_path: Path):
    # A module with no eligible class is a no-op, not a failure.
    _project(tmp_path, "app/clean.py", "def f():\n    return 1\n")
    plan = plan_synthesize_dunders(str(tmp_path), "app/clean.py")
    assert not plan.new_contents


def test_plan_uses_project_scan_for_inherited_eq(tmp_path: Path):
    # Base in a SEPARATE own module defines __eq__ -> the project scan resolves it and
    # refuses adding __eq__ to the child, while still adding __repr__.
    _project(tmp_path, "app/base.py",
             "class Base:\n    def __eq__(self, other):\n        return True\n")
    child = (
        "from app.base import Base\n"
        "\n"
        "\n"
        "class Child(Base):\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "\n"
        "    def m(self):\n"
        "        return self.a\n"
    )
    _project(tmp_path, "app/child.py", child)
    plan = plan_synthesize_dunders(str(tmp_path), "app/child.py")
    new = plan.new_contents["app/child.py"]
    assert "def __repr__(self) -> str:" in new
    assert "def __eq__" not in new  # inherited __eq__ resolved across modules -> refused


# --- END-TO-END: apply_rename lands the dunders, suite stays green ------------

def test_end_to_end_apply_rename_lands_and_stays_green(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    src = (
        "class Vector:\n"
        "    def __init__(self, x, y):\n"
        "        self.x = x\n"
        "        self.y = y\n"
        "\n"
        "    def length(self):\n"
        "        return (self.x ** 2 + self.y ** 2) ** 0.5\n"
    )
    (tmp_path / "app" / "vector.py").write_text(src, encoding="utf-8")
    (tmp_path / "tests" / "test_vector.py").write_text(
        "from app.vector import Vector\n"
        "def test_repr():\n"
        "    assert repr(Vector(1, 2)) == 'Vector(x=1, y=2)'\n"
        "def test_eq():\n"
        "    assert Vector(1, 2) == Vector(1, 2)\n"
        "    assert Vector(1, 2) != Vector(3, 4)\n"
        "def test_hashable():\n"
        "    assert hash(Vector(1, 2)) == hash(Vector(1, 2))\n",
        encoding="utf-8")

    plan = plan_synthesize_dunders(str(tmp_path), "app/vector.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "vector.py").read_text(encoding="utf-8")
    assert "def __repr__(self) -> str:" in landed  # the dunders LANDED
    assert "def length(self):" in landed  # the original method preserved (proven green)
