"""enforce-enum-unique develop objective — LAND ``@enum.unique`` on a project's own
top-level ``Enum`` subclass whose members are PROVEN to all carry distinct
simple-literal values.

``@enum.unique`` is a PURE no-op TODAY on an already-distinct enum (it raises
``ValueError`` ONLY on a duplicate value, of which the static proof guarantees there
are none), so the change is behaviour-preserving BY CONSTRUCTION. The only honesty
risk is a FALSE enforce that would raise at import; it is closed STATICALLY, not by
the suite — the seal lands ONLY when every member value is a distinct simple literal,
and the collision scan compares MATERIALISED Python values with ``==`` (not
type-tagged keys), so the footgun ``1 == True == 1.0`` is caught and refused.

Covers: the core transform (fresh ``from enum import unique`` insert; widen an
existing ``from enum import ...``; the dotted ``@enum.unique`` fallback when
``unique`` is shadowed but ``enum`` is bound; decorator/indent preservation;
trailing-newline preservation) plus EVERY refusal — duplicate values, the ``==``
footgun (int/bool, int/float — the load-bearing soundness test), ``auto()``, a
computed/non-literal value, a tuple value, already ``@unique`` / ``@enum.unique``, an
empty enum, a non-enum class, an unmodelled class-body binder, a shadowed ``unique``
with no usable ``enum``, a ``unique`` from another module, a syntax error; plus
idempotency and determinism; objective registration / reachability (available,
callable spec, reachable-from-facet, the facet-map<->registry 1:1 parity invariant,
substring-safety, the north-star manifest classing it CONCRETE with the reverse
tripwire clean, the facet ladder carrying the phrase with the originals still
leading); the plan + END-TO-END landing (``apply_rename`` verify=True adds
``@unique`` in place and the suite stays green); and the never-fake-green capstone (a
module whose enum has ``==``-colliding members is REFUSED before any apply — the
false enforce that would raise at import never lands).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.enum_unique import (
    add_enum_unique_decorator,
    enum_has_unique_decorator,
    uniqueable_enums,
)
from app.execution.objectives.enforce_enum_unique import plan_enforce_enum_unique

# A distinct-literal enum with only ``from enum import Enum``: gains ``unique``
# widened into the import + ``@unique`` directly above the class.
_ENUM = (
    '"""A colour enum."""\n'
    "\n"
    "from enum import Enum\n"
    "\n"
    "\n"
    "class Color(Enum):\n"
    "    RED = 1\n"
    "    GREEN = 2\n"
    "    BLUE = 3\n"
)

_PHRASE = "an enum to enforce unique values on"


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

def test_uniqueable_detects_distinct_literal_enum():
    src = "from enum import Enum\n\n\nclass Color(Enum):\n    RED = 1\n    GREEN = 2\n    BLUE = 3\n"
    assert uniqueable_enums(src) == ["Color"]


def test_uniqueable_detects_intenum_strenum():
    int_src = "from enum import IntEnum\n\n\nclass N(IntEnum):\n    A = 1\n    B = 2\n"
    str_src = "from enum import StrEnum\n\n\nclass S(StrEnum):\n    A = 'a'\n    B = 'b'\n"
    dotted_src = "import enum\n\n\nclass D(enum.IntEnum):\n    A = 1\n    B = 2\n"
    assert uniqueable_enums(int_src) == ["N"]
    assert uniqueable_enums(str_src) == ["S"]
    assert uniqueable_enums(dotted_src) == ["D"]


def test_enum_has_unique_true_bare():
    cls = ast.parse("@unique\nclass C(Enum):\n    A = 1\n").body[0]
    assert enum_has_unique_decorator(cls)


def test_enum_has_unique_true_dotted():
    cls = ast.parse("@enum.unique\nclass C(Enum):\n    A = 1\n").body[0]
    assert enum_has_unique_decorator(cls)


def test_enum_has_unique_false_when_absent():
    cls = ast.parse("@register\nclass C(Enum):\n    A = 1\n").body[0]
    assert not enum_has_unique_decorator(cls)


# --- the core transform: rewrite --------------------------------------------

def test_adds_unique_and_fresh_enum_import():
    out = add_enum_unique_decorator(_ENUM)
    assert out is not None
    lines = out.splitlines()
    assert lines[0] == '"""A colour enum."""'  # docstring stays first
    # The enum import is widened in place to add ``unique`` (no second line).
    assert out.count("from enum import") == 1
    assert "from enum import Enum, unique" in lines
    assert "@unique" in out
    assert "class Color(Enum):" in out
    ast.parse(out)  # never lands broken Python


def test_unique_sits_directly_above_the_class():
    out = add_enum_unique_decorator(_ENUM)
    assert out is not None
    assert "\n@unique\nclass Color(Enum):\n" in out


def test_widens_existing_enum_import_in_place():
    src = "from enum import Enum\n\n\nclass C(Enum):\n    A = 1\n    B = 2\n"
    out = add_enum_unique_decorator(src)
    assert out is not None
    assert out.count("from enum import") == 1  # widened, not a second line
    assert out.splitlines()[0] == "from enum import Enum, unique"
    assert "@unique" in out
    ast.parse(out)


def test_uses_dotted_enum_unique_when_unique_shadowed():
    # ``unique`` is shadowed by a local def, but ``enum`` is bound bare — so the
    # dotted ``@enum.unique`` is provable and used (and NO ``from enum import
    # unique`` is added, which would re-bind the shadowed name).
    src = (
        "import enum\n"
        "\n"
        "\n"
        "def unique(c):\n"
        "    return c\n"
        "\n"
        "\n"
        "class C(enum.IntEnum):\n"
        "    A = 1\n"
        "    B = 2\n"
    )
    out = add_enum_unique_decorator(src)
    assert out is not None
    assert "@enum.unique" in out
    assert "from enum import unique" not in out  # the shadow is not re-imported
    ast.parse(out)


def test_inserts_fresh_import_when_no_clean_enum_import():
    # A parenthesized multi-line ``from enum import (...)`` is NOT cleanly widenable,
    # so a fresh ``from enum import unique`` line is inserted (the block is not
    # corrupted), the seal LANDS, and the decorated class still constructs and
    # rejects a duplicate at definition time.
    src = (
        "from enum import (\n"
        "    Enum,\n"
        ")\n"
        "\n"
        "\n"
        "class Color(Enum):\n"
        "    RED = 1\n"
        "    GREEN = 2\n"
    )
    out = add_enum_unique_decorator(src)
    assert out is not None
    assert "@unique" in out
    ast.parse(out)
    assert "from enum import (" in out  # original block untouched
    assert "from enum import unique" in out  # fresh second import line
    ns: dict[str, object] = {}
    exec(compile(out, "<enum_fresh>", "exec"), ns)  # noqa: S102 - test-only
    assert ns["Color"].RED.value == 1  # the enum still constructs


def test_preserves_existing_decorator():
    src = "from enum import Enum\n\n\n@register\nclass C(Enum):\n    A = 1\n    B = 2\n"
    out = add_enum_unique_decorator(src)
    assert out is not None
    # The existing decorator stays; @unique is added directly above the class.
    assert "@register\n@unique\nclass C(Enum):" in out
    ast.parse(out)


def test_preserves_trailing_newline_absence():
    out = add_enum_unique_decorator("from enum import Enum\nclass C(Enum):\n    A = 1\n    B = 2")
    assert out is not None and not out.endswith("\n")


# --- the core transform: REFUSALS (honest no-ops, the soundness surface) ----

def test_refuses_duplicate_values():
    src = "from enum import Enum\n\n\nclass E(Enum):\n    A = 1\n    B = 1\n"
    assert add_enum_unique_decorator(src) is None  # intentional alias


def test_refuses_equality_colliding_int_and_bool():
    # THE load-bearing soundness test: ``1 == True`` so ``@unique`` WOULD raise at
    # import — the type-tagged key would (wrongly) distinguish them, but the ``==``
    # scan catches it and the enum is REFUSED.
    src = "from enum import Enum\n\n\nclass E(Enum):\n    A = 1\n    B = True\n"
    assert add_enum_unique_decorator(src) is None


def test_refuses_equality_colliding_int_and_float():
    src = "from enum import Enum\n\n\nclass E(Enum):\n    A = 1\n    B = 1.0\n"
    assert add_enum_unique_decorator(src) is None


def test_refuses_auto_valued_enum():
    src = "from enum import Enum, auto\n\n\nclass E(Enum):\n    A = auto()\n    B = auto()\n"
    assert add_enum_unique_decorator(src) is None  # un-provable distinctness


def test_refuses_computed_value():
    binop = "from enum import Enum\n\n\nclass E(Enum):\n    A = 1\n    B = 1 + 1\n"
    call = "from enum import Enum\n\n\nclass E(Enum):\n    A = compute()\n    B = 2\n"
    name = "from enum import Enum\n\n\nOTHER = 3\n\n\nclass E(Enum):\n    A = 1\n    B = OTHER\n"
    assert add_enum_unique_decorator(binop) is None
    assert add_enum_unique_decorator(call) is None
    assert add_enum_unique_decorator(name) is None


def test_refuses_tuple_valued_enum():
    src = "from enum import Enum\n\n\nclass E(Enum):\n    A = (1, 2)\n    B = (3, 4)\n"
    assert add_enum_unique_decorator(src) is None  # non-scalar literal


def test_refuses_already_unique_bare_idempotent():
    src = "from enum import Enum, unique\n\n\n@unique\nclass E(Enum):\n    A = 1\n    B = 2\n"
    assert add_enum_unique_decorator(src) is None


def test_refuses_already_enum_unique_idempotent():
    src = "import enum\n\n\n@enum.unique\nclass E(enum.Enum):\n    A = 1\n    B = 2\n"
    assert add_enum_unique_decorator(src) is None


def test_refuses_empty_enum():
    src = "from enum import Enum\n\n\nclass E(Enum):\n    pass\n"
    assert add_enum_unique_decorator(src) is None  # no members — nothing to make unique


def test_refuses_non_enum_class():
    src = "class C:\n    A = 1\n    B = 2\n"
    assert add_enum_unique_decorator(src) is None  # not an enum base


def test_refuses_unmodelled_class_body_binder():
    for_body = "from enum import Enum\n\n\nclass E(Enum):\n    A = 1\n    for i in range(2):\n        pass\n"
    if_body = "from enum import Enum\n\n\nclass E(Enum):\n    A = 1\n    if True:\n        B = 2\n"
    aug = "from enum import Enum\n\n\nclass E(Enum):\n    A = 1\n    A += 1\n"
    assert add_enum_unique_decorator(for_body) is None
    assert add_enum_unique_decorator(if_body) is None
    assert add_enum_unique_decorator(aug) is None


def test_refuses_when_unique_shadowed_and_no_usable_enum():
    # ``unique`` shadowed by a local def and ``enum`` not bound bare — no provable
    # spelling of ``enum.unique``, so refuse.
    src = "from enum import Enum\n\n\ndef unique(c):\n    return c\n\n\nclass E(Enum):\n    A = 1\n    B = 2\n"
    assert add_enum_unique_decorator(src) is None


def test_refuses_when_unique_bound_to_another_module():
    # ``unique`` imported from a DIFFERENT module — a bare ``@unique`` would not be
    # ``enum.unique``, so refuse.
    src = "from enum import Enum\nfrom foo import unique\n\n\nclass E(Enum):\n    A = 1\n    B = 2\n"
    assert add_enum_unique_decorator(src) is None


def test_refuses_syntax_error():
    assert add_enum_unique_decorator("def (:\n") is None


# --- idempotency / determinism ----------------------------------------------

def test_idempotent_second_run_is_noop():
    once = add_enum_unique_decorator(_ENUM)
    assert once is not None
    assert add_enum_unique_decorator(once) is None  # 2nd run = byte-identical no-op


def test_deterministic_across_two_runs():
    a = add_enum_unique_decorator(_ENUM)
    b = add_enum_unique_decorator(_ENUM)
    assert a is not None and a == b


# --- registration / reachability --------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "enforce-enum-unique" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["enforce-enum-unique"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "enforce-enum-unique"


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


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "enforce-enum-unique" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_facet_phrase_lives_in_the_property_invariants_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["property invariants"]
    assert _PHRASE in ladder
    assert ladder[0] == "idempotence"  # originals still lead


# --- the plan: a distinct-literal enum gets @unique --------------------------

def test_plan_lands_unique(tmp_path: Path):
    _project(tmp_path, "app/colors.py", _ENUM)
    plan = plan_enforce_enum_unique(str(tmp_path), "app/colors.py")
    assert plan.ok
    new = plan.new_contents["app/colors.py"]
    assert "@unique" in new
    assert "from enum import Enum, unique" in new
    assert plan.originals["app/colors.py"] == _ENUM  # original captured for rollback
    assert plan.edits_by_file["app/colors.py"] == 1


def test_plan_refuses_duplicate_value_enum(tmp_path: Path):
    _project(tmp_path, "app/colors.py",
             "from enum import Enum\n\n\nclass E(Enum):\n    A = 1\n    B = 1\n")
    assert not plan_enforce_enum_unique(str(tmp_path), "app/colors.py").new_contents


def test_plan_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _ENUM)
    assert not plan_enforce_enum_unique(str(tmp_path), "tests/test_x.py").new_contents


def test_plan_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", _ENUM)
    assert not plan_enforce_enum_unique(str(tmp_path), "fixtures/sample.py").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_enforce_enum_unique(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: gated apply, real landing, suite stays green ----------------

def test_end_to_end_lands_unique_and_keeps_green(tmp_path: Path):
    _suite_project(tmp_path)
    (tmp_path / "app" / "colors.py").write_text(_ENUM, encoding="utf-8")
    (tmp_path / "tests" / "test_colors.py").write_text(
        "from app.colors import Color\n"
        "def test_values():\n"
        "    assert Color.RED.value == 1\n"
        "    assert Color.BLUE.value == 3\n"
        "def test_distinct():\n"
        "    assert len(set(Color)) == 3\n",
        encoding="utf-8")

    plan = plan_enforce_enum_unique(str(tmp_path), "app/colors.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "colors.py").read_text(encoding="utf-8")
    assert "@unique" in landed  # the decorator LANDED
    assert "from enum import Enum, unique" in landed
    # Behaviour preserved (proven green by the apply gate): the enum still constructs.
    assert "class Color(Enum):" in landed


def test_never_lands_breaking_unique_on_colliding_values(tmp_path: Path):
    # The behavioural soundness capstone. ``@enum.unique`` on an enum whose members
    # are ``==``-colliding (``1`` and ``True``) would RAISE ``ValueError`` at import.
    # The static proof REFUSES it before any apply, so the false enforce that would
    # crash at import never lands — the analogue of add-final's never-fake-green.
    _project(tmp_path, "app/flags.py",
             "from enum import Enum\n\n\nclass Flag(Enum):\n    ON = 1\n    YES = True\n")
    plan = plan_enforce_enum_unique(str(tmp_path), "app/flags.py")
    assert not plan.new_contents  # the false enforce is refused before any apply
