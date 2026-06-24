"""freeze-dataclass develop objective — LAND ``frozen=True`` on a project's own
``@dataclass`` whose fields are NEVER mutated anywhere in the project's own source.

A frozen dataclass is immutable + hashable; freezing a never-mutated dataclass is
a behaviour-preserving modernization a linter only FLAGS but Apex WRITES. The
suite gate ALONE is insufficient (an untested mutation path would stay green yet
raise ``FrozenInstanceError`` once frozen), so the engine statically
OVER-APPROXIMATES mutation across the WHOLE project and refuses conservatively.

Covers: the core transform (every decorator form — bare ``@dataclass``,
``@dataclass()``, ``@dataclass(eq=True)``, ``@dataclasses.dataclass`` — plus EVERY
refusal: already-frozen, ``frozen=False`` left alone, a base class, used-as-a-base
elsewhere, a field mutated by ``=`` / ``+=`` / ``del`` / ``setattr`` / a mutating
``__post_init__``, no fields, ClassVar-only, syntax error, test/fixture; plus
idempotency and determinism); the whole-project mutation over-approximation
(``mutated_attribute_names``); objective registration / reachability (available,
callable spec, reachable-from-facet, the facet-map<->registry 1:1 parity invariant,
substring-safety, the north-star manifest classing it CONCRETE with the reverse
tripwire clean, the facet ladder carrying the phrase with the originals still
leading); the END-TO-END landing (``apply_rename`` verify=True freezes the class in
place and the suite stays green); and the never-fake-green ROLLBACK (a frozen-
incompatible mutation only an UNTESTED path performs — the gate restores the file
byte-for-byte rather than landing a freeze that breaks the suite at runtime).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.freeze_dataclass import (
    dataclass_field_names,
    freeze_dataclass_decorator,
    freezable_classes,
    is_frozen_dataclass_decorator,
    mutated_attribute_names,
)
from app.execution.objectives.freeze_dataclass import plan_freeze_dataclass

# A never-mutated dataclass that lacks ``frozen=True``.
_UNFROZEN = (
    "from dataclasses import dataclass\n"
    "\n"
    "\n"
    "@dataclass\n"
    "class Point:\n"
    "    x: int\n"
    "    y: int\n"
    "\n"
    "\n"
    "def total(p: Point) -> int:\n"
    "    return p.x + p.y\n"
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


# --- the core transform: detection ------------------------------------------

def test_freezable_detects_never_mutated_dataclass():
    assert freezable_classes(_UNFROZEN) == ["Point"]


def test_field_names_skip_classvar_and_methods():
    cls = ast.parse(
        "@dataclass\n"
        "class P:\n"
        "    n: int\n"
        "    kind: ClassVar[str] = 'p'\n"
        "    def f(self):\n        return self.n\n"
    ).body[0]
    assert dataclass_field_names(cls) == ["n"]


def test_field_names_typing_classvar_attribute_form():
    cls = ast.parse(
        "@dataclass\nclass P:\n    a: int\n    b: typing.ClassVar[int] = 0\n"
    ).body[0]
    assert dataclass_field_names(cls) == ["a"]


def test_is_frozen_decorator_true_when_frozen_present():
    dec = ast.parse("@dataclass(frozen=True)\nclass P:\n    x: int\n").body[0].decorator_list[0]
    assert is_frozen_dataclass_decorator(dec)


def test_is_frozen_decorator_false_for_bare_dataclass():
    dec = ast.parse("@dataclass\nclass P:\n    x: int\n").body[0].decorator_list[0]
    assert not is_frozen_dataclass_decorator(dec)


# --- the whole-project mutation over-approximation --------------------------

def test_mutated_attribute_names_plain_store():
    assert "x" in mutated_attribute_names("o.x = 1\n")


def test_mutated_attribute_names_augmented():
    assert "x" in mutated_attribute_names("o.x += 1\n")


def test_mutated_attribute_names_del():
    assert "x" in mutated_attribute_names("del o.x\n")


def test_mutated_attribute_names_setattr_literal():
    assert "x" in mutated_attribute_names('setattr(o, "x", 1)\n')


def test_mutated_attribute_names_setattr_dynamic_not_resolved():
    # A non-literal setattr name cannot be resolved statically — it contributes
    # nothing here (the suite gate is the backstop for that dynamic case).
    assert mutated_attribute_names("setattr(o, k, 1)\n") == set()


def test_mutated_attribute_names_read_is_not_a_mutation():
    assert "x" not in mutated_attribute_names("y = o.x\n")


def test_mutated_attribute_names_syntax_error_is_empty():
    assert mutated_attribute_names("def (:\n") == set()


# --- the core transform: rewrite (every decorator form) ---------------------

def test_freeze_bare_dataclass():
    out = freeze_dataclass_decorator(_UNFROZEN)
    assert out is not None
    assert "@dataclass(frozen=True)" in out
    ast.parse(out)  # never lands broken Python


def test_freeze_called_dataclass_empty_parens():
    src = _UNFROZEN.replace("@dataclass\n", "@dataclass()\n")
    out = freeze_dataclass_decorator(src)
    assert out is not None and "@dataclass(frozen=True)" in out


def test_freeze_called_dataclass_keeps_existing_keyword():
    src = _UNFROZEN.replace("@dataclass\n", "@dataclass(eq=True)\n")
    out = freeze_dataclass_decorator(src)
    assert out is not None
    # The existing keyword is preserved; frozen is appended after it.
    assert "@dataclass(eq=True, frozen=True)" in out


def test_freeze_dotted_dataclasses_dataclass():
    src = (
        "import dataclasses\n"
        "\n"
        "\n"
        "@dataclasses.dataclass\n"
        "class P:\n"
        "    x: int\n"
    )
    out = freeze_dataclass_decorator(src)
    assert out is not None and "@dataclasses.dataclass(frozen=True)" in out


def test_freeze_preserves_decorator_indentation_is_top_level():
    out = freeze_dataclass_decorator(_UNFROZEN)
    assert out is not None
    # The decorator stays at column 0 (the class is top-level).
    assert "\n@dataclass(frozen=True)\n" in out


# --- the core transform: REFUSALS (honest no-ops) ---------------------------

def test_refuses_already_frozen_idempotent():
    src = _UNFROZEN.replace("@dataclass\n", "@dataclass(frozen=True)\n")
    assert freeze_dataclass_decorator(src) is None


def test_refuses_explicit_frozen_false():
    # An explicit ``frozen=False`` is a deliberate choice — never override it.
    src = _UNFROZEN.replace("@dataclass\n", "@dataclass(frozen=False)\n")
    assert freeze_dataclass_decorator(src) is None


def test_refuses_class_with_a_base():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P(Base):\n"
        "    x: int\n"
    )
    assert freeze_dataclass_decorator(src) is None


def test_allows_explicit_object_base():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P(object):\n"
        "    x: int\n"
    )
    out = freeze_dataclass_decorator(src)
    assert out is not None and "@dataclass(frozen=True)" in out


def test_refuses_metaclass_keyword():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P(metaclass=Meta):\n"
        "    x: int\n"
    )
    assert freeze_dataclass_decorator(src) is None


def test_refuses_class_used_as_a_base_elsewhere():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int\n"
        "\n"
        "\n"
        "class Q(P):\n"
        "    pass\n"
    )
    assert freeze_dataclass_decorator(src) is None


def test_refuses_field_mutated_by_assignment():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int\n"
        "\n"
        "\n"
        "def move(p: P) -> None:\n"
        "    p.x = 5\n"
    )
    assert freeze_dataclass_decorator(src) is None


def test_refuses_field_mutated_by_augmented_assignment():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int\n"
        "\n"
        "\n"
        "def bump(p: P) -> None:\n"
        "    p.x += 1\n"
    )
    assert freeze_dataclass_decorator(src) is None


def test_refuses_field_mutated_by_del():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int\n"
        "\n"
        "\n"
        "def drop(p: P) -> None:\n"
        "    del p.x\n"
    )
    assert freeze_dataclass_decorator(src) is None


def test_refuses_field_mutated_by_setattr():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int\n"
        "\n"
        "\n"
        "def set_it(p: P) -> None:\n"
        '    setattr(p, "x", 7)\n'
    )
    assert freeze_dataclass_decorator(src) is None


def test_refuses_mutating_post_init():
    # A mutating ``__post_init__`` (``self.x = ...``) is caught automatically —
    # the field name appears as a Store target on ``self``.
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int\n"
        "\n"
        "    def __post_init__(self):\n"
        "        self.x = self.x + 1\n"
    )
    assert freeze_dataclass_decorator(src) is None


def test_refuses_no_fields():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P:\n"
        "    pass\n"
    )
    assert freeze_dataclass_decorator(src) is None


def test_refuses_classvar_only_no_real_field():
    src = (
        "from dataclasses import dataclass\n"
        "from typing import ClassVar\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P:\n"
        "    kind: ClassVar[str] = 'p'\n"
    )
    assert freeze_dataclass_decorator(src) is None


def test_refuses_non_dataclass_class():
    assert freeze_dataclass_decorator(
        "class P:\n    x = 1\n") is None


def test_refuses_syntax_error():
    assert freeze_dataclass_decorator("def (:\n") is None


# --- idempotency / determinism ----------------------------------------------

def test_idempotent_second_run_is_noop():
    once = freeze_dataclass_decorator(_UNFROZEN)
    assert once is not None
    assert freeze_dataclass_decorator(once) is None  # 2nd run = byte-identical no-op


def test_deterministic_across_two_runs():
    a = freeze_dataclass_decorator(_UNFROZEN)
    b = freeze_dataclass_decorator(_UNFROZEN)
    assert a is not None and a == b


def test_preserves_trailing_newline_absence():
    # No trailing newline on the final field line. The proving import is present
    # so the bare ``@dataclass`` is recognised as the stdlib one (see FIX 3).
    out = freeze_dataclass_decorator(
        "from dataclasses import dataclass\n@dataclass\nclass P:\n    x: int")
    assert out is not None and not out.endswith("\n")


def test_project_scan_can_only_add_refusals():
    # A class freezable in isolation REFUSES once a SIBLING module mutates a field
    # of the same name — the whole-project over-approximation is strictly more
    # conservative than the single-module one.
    assert freezable_classes(_UNFROZEN) == ["Point"]
    out = freeze_dataclass_decorator(_UNFROZEN, [_UNFROZEN, "other.x = 9\n"])
    assert out is None


# --- registration / reachability --------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "freeze-dataclass" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["freeze-dataclass"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(
        "a never-mutated dataclass to freeze"
    ) == "freeze-dataclass"


def test_facet_reachability_parity_invariant_holds():
    # The standing 1:1 invariant: the facet map reaches EXACTLY the registered
    # objectives. Adding this objective to BOTH sides keeps the equality.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_facet_phrase_is_substring_order_safe():
    # The new key must be neither a substring of, nor contain, any other key
    # (with a different objective) — else the first-match scan would mis-route.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    new = "a never-mutated dataclass to freeze"
    keys = list(FACET_OBJECTIVE_MAP)
    assert new in keys
    for other in keys:
        if other == new:
            continue
        assert new not in other, f"{new!r} is a substring of {other!r}"
        assert other not in new, f"{other!r} is a substring of {new!r}"


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "freeze-dataclass" in buckets["CONCRETE"]
    # No stale manifest name (a name with no live objective) was introduced.
    assert manifest_subset_of_registry() == []


def test_facet_phrase_lives_in_the_no_op_statements_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["unreachable or no-op statements"]
    assert "a never-mutated dataclass to freeze" in ladder
    assert ladder[0] == "redundant pass statement"  # originals still lead
    # The sibling dataclassify phrase still precedes the new one.
    assert ladder.index("a boilerplate constructor to make a dataclass") < ladder.index(
        "a never-mutated dataclass to freeze")


# --- the plan: a never-mutated dataclass gets frozen=True --------------------

def test_plan_lands_frozen(tmp_path: Path):
    _project(tmp_path, "app/point.py", _UNFROZEN)
    plan = plan_freeze_dataclass(str(tmp_path), "app/point.py")
    assert plan.ok
    new = plan.new_contents["app/point.py"]
    assert "@dataclass(frozen=True)" in new
    assert plan.originals["app/point.py"] == _UNFROZEN  # original captured for rollback
    assert plan.edits_by_file["app/point.py"] == 1


def test_plan_uses_whole_project_mutation_scan(tmp_path: Path):
    # The dataclass is never mutated in its OWN module, but a SIBLING module
    # mutates a field of the same name — the whole-project scan must refuse.
    _project(tmp_path, "app/point.py", _UNFROZEN)
    _project(tmp_path, "app/other.py",
             "def f(thing):\n    thing.x = 0\n")
    plan = plan_freeze_dataclass(str(tmp_path), "app/point.py")
    assert not plan.new_contents  # refused by the cross-module mutation


def test_plan_refuses_already_frozen(tmp_path: Path):
    _project(tmp_path, "app/point.py",
             _UNFROZEN.replace("@dataclass\n", "@dataclass(frozen=True)\n"))
    assert not plan_freeze_dataclass(str(tmp_path), "app/point.py").new_contents


def test_plan_refuses_field_mutated_in_same_module(tmp_path: Path):
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int\n"
        "\n"
        "\n"
        "def move(p: P) -> None:\n"
        "    p.x = 5\n"
    )
    _project(tmp_path, "app/p.py", src)
    assert not plan_freeze_dataclass(str(tmp_path), "app/p.py").new_contents


def test_plan_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _UNFROZEN)
    assert not plan_freeze_dataclass(str(tmp_path), "tests/test_x.py").new_contents


def test_plan_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", _UNFROZEN)
    assert not plan_freeze_dataclass(str(tmp_path), "fixtures/sample.py").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_freeze_dataclass(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: gated apply, real landing, suite stays green ----------------

def test_end_to_end_lands_frozen_and_keeps_green(tmp_path: Path):
    _suite_project(tmp_path)
    (tmp_path / "app" / "point.py").write_text(_UNFROZEN, encoding="utf-8")
    (tmp_path / "tests" / "test_point.py").write_text(
        "from app.point import Point, total\n"
        "def test_total():\n"
        "    assert total(Point(2, 3)) == 5\n"
        "def test_hashable():\n"
        "    assert hash(Point(1, 2)) == hash(Point(1, 2))\n",
        encoding="utf-8")

    plan = plan_freeze_dataclass(str(tmp_path), "app/point.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "point.py").read_text(encoding="utf-8")
    assert "@dataclass(frozen=True)" in landed  # the freeze LANDED
    # Behaviour preserved: construction + read still work (proven green by the
    # apply gate running the test above), and the class is now hashable.
    assert "class Point:" in landed


def test_end_to_end_auto_rollback_when_untested_mutation_breaks_frozen(tmp_path: Path):
    # never-fake-green at the engine level. The static over-approximation is SOUND
    # for the mutation shapes it covers, but a truly DYNAMIC ``setattr`` whose
    # attribute NAME is a runtime variable (``setattr(c, attr, ...)``) escapes it —
    # the scan cannot tie ``attr`` to the field ``value`` (verified above:
    # ``test_mutated_attribute_names_setattr_dynamic_not_resolved``). So the plan
    # PROPOSES the freeze, but at runtime ``setattr`` on a now-frozen instance
    # raises ``FrozenInstanceError`` — the suite (which exercises ``bump``) goes red
    # and the file is rolled back byte-for-byte. This is exactly the residual the
    # full-suite gate is the backstop for. (Divergence verified independently:
    # ``setattr(frozen, var, v)`` raises ``FrozenInstanceError``.)
    _suite_project(tmp_path)
    risky = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class Counter:\n"
        "    value: int\n"
        "\n"
        "\n"
        "def bump(c: Counter) -> None:\n"
        "    # DYNAMIC setattr — the attribute name is a runtime variable, so the\n"
        "    # static field-name scan cannot tie it to ``value`` and (wrongly)\n"
        "    # proposes the freeze; the suite below catches the runtime break.\n"
        "    attr = 'value'\n"
        "    setattr(c, attr, c.value + 1)\n"
    )
    target = tmp_path / "app" / "counter.py"
    target.write_text(risky, encoding="utf-8")
    (tmp_path / "tests" / "test_counter.py").write_text(
        "from app.counter import Counter, bump\n"
        "def test_bump():\n"
        "    c = Counter(0)\n"
        "    bump(c)\n"  # frozen -> dynamic setattr raises FrozenInstanceError -> red
        "    assert c.value == 1\n",
        encoding="utf-8")

    plan = plan_freeze_dataclass(str(tmp_path), "app/counter.py")
    assert plan.ok  # the static scan did NOT see the __dict__ mutation, so it proposes
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is False
    assert result.get("rolled_back") is True
    # The file is restored byte-for-byte — a freeze that would break the suite at
    # runtime is NEVER left landed (never-fake-green).
    assert target.read_text(encoding="utf-8") == risky


# --- CONFIRMED code-review fixes (one regression test per soundness hole) ----

def test_fix1_refuses_dataclass_with_kwargs_unpacking():
    # FIX 1: ``@dataclass(**opts)`` — the unpacked dict's keys are unknown, so
    # appending ``frozen=True`` could emit ``@dataclass(**opts, frozen=True)``,
    # which PARSES but raises ``TypeError: got multiple values for ... 'frozen'``
    # at import. We conservatively refuse (an honest no-op).
    src = (
        "from dataclasses import dataclass\n"
        "@dataclass(**opts)\n"
        "class A:\n"
        "    x: int = 1\n"
    )
    assert freeze_dataclass_decorator(src) is None


def test_fix2_refuses_class_subclassed_via_dotted_base_cross_module():
    # FIX 2: a sibling module subclasses the dataclass through a DOTTED base
    # (``a.Point``). Freezing ``Point`` would make importing the subclass raise
    # ``TypeError: cannot inherit non-frozen dataclass from a frozen one``, so the
    # whole-project used-as-base scan must see the dotted base and refuse.
    point_src = (
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class Point:\n"
        "    x: int = 0\n"
    )
    b_src = (
        "import a\n"
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class Sub(a.Point):\n"
        "    y: int = 0\n"
    )
    assert freezable_classes(point_src) == ["Point"]  # freezable in isolation
    assert freeze_dataclass_decorator(point_src, [point_src, b_src]) is None


def test_fix3_decorator_provenance_only_freezes_stdlib_dataclass():
    # FIX 3: only a PROVABLY-stdlib ``dataclass`` is frozen; a same-named decorator
    # from elsewhere (pydantic, a local def) is left alone.
    pydantic = (
        "from pydantic.dataclasses import dataclass\n"
        "@dataclass\n"
        "class M:\n"
        "    x: int = 0\n"
    )
    assert freeze_dataclass_decorator(pydantic) is None  # not stdlib — refused

    local_def = (
        "def dataclass(c):\n"
        "    return c\n"
        "@dataclass\n"
        "class A:\n"
        "    x: int = 0\n"
    )
    assert freeze_dataclass_decorator(local_def) is None  # local shadow — refused

    # A pydantic DOTTED form (``pydantic.dataclasses.dataclass``) is rejected too:
    # its value is an Attribute, not the bare ``Name`` ``dataclasses``.
    pydantic_dotted = (
        "import pydantic\n"
        "@pydantic.dataclasses.dataclass\n"
        "class M:\n"
        "    x: int = 0\n"
    )
    assert freeze_dataclass_decorator(pydantic_dotted) is None

    # The genuine stdlib forms STILL freeze.
    bare = (
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class A:\n"
        "    x: int = 0\n"
    )
    out_bare = freeze_dataclass_decorator(bare)
    assert out_bare is not None and "@dataclass(frozen=True)" in out_bare

    dotted = (
        "import dataclasses\n"
        "@dataclasses.dataclass\n"
        "class A:\n"
        "    x: int = 0\n"
    )
    out_dotted = freeze_dataclass_decorator(dotted)
    assert out_dotted is not None and "@dataclasses.dataclass(frozen=True)" in out_dotted


def test_fix4_setattr_method_form_not_misread_as_field_mutation():
    # FIX 4: only the BUILTIN ``setattr(obj, "name", value)`` contributes a field
    # name. A method call ``obj.setattr("name", "x")`` has a DIFFERENT arg layout —
    # reading ``args[1]`` would wrongly pick up the value ``"x"`` as a mutated
    # field. The builtin still contributes; the method form contributes nothing.
    assert "x" in mutated_attribute_names('setattr(self, "x", v)\n')
    # ``args[1]`` of the method call is the string ``"x"`` — must NOT be harvested.
    assert mutated_attribute_names('o.setattr("name", "x")\n') == set()


def test_fix5_project_sources_is_public():
    # FIX 5: the cross-module helper is now a public, ``__all__``-exported name.
    import app.execution.freeze_dataclass as engine

    assert "project_sources" in engine.__all__
    assert hasattr(engine, "project_sources")
    assert not hasattr(engine, "_project_sources")  # the private name is gone


def test_fix6_refuses_multiline_and_commented_decorators():
    # FIX 6: the ``ast.unparse`` re-emit drops comments and collapses a multi-line
    # decorator onto one line, so we refuse anything not a single uncommented
    # physical line rather than risk silent content loss.
    multiline = (
        "from dataclasses import dataclass\n"
        "@dataclass(\n"
        "    eq=True,\n"
        ")\n"
        "class A:\n"
        "    x: int = 0\n"
    )
    assert freeze_dataclass_decorator(multiline) is None

    commented = (
        "from dataclasses import dataclass\n"
        "@dataclass  # keep\n"
        "class A:\n"
        "    x: int = 0\n"
    )
    assert freeze_dataclass_decorator(commented) is None

    # A plain single-line decorator still freezes.
    single = (
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class A:\n"
        "    x: int = 0\n"
    )
    out = freeze_dataclass_decorator(single)
    assert out is not None and "@dataclass(frozen=True)" in out


def test_fix7_refuses_class_subclassed_via_subscripted_base():
    # FIX A (soundness, shared used-as-base helper): a SUBSCRIPTED base
    # ``class Sub(Base[int])`` really subclasses ``Base`` — the base expr is an
    # ``ast.Subscript`` whose head ``Base`` must be recorded as used-as-base.
    # Freezing ``Base`` would make ``class Sub(Base[int])`` a
    # ``TypeError: cannot inherit non-frozen dataclass from a frozen one`` at the
    # subclass's definition time, so the whole-project scan must see the subscript
    # head and REFUSE. (Previously ``_base_name`` returned None for a Subscript, so
    # the head was never recorded and the freeze wrongly landed.)
    base_src = (
        "from dataclasses import dataclass\n"
        "from typing import Generic, TypeVar\n"
        "T = TypeVar('T')\n"
        "@dataclass\n"
        "class Base:\n"
        "    x: int = 0\n"
    )
    sub_src = (
        "from m import Base\n"
        "from typing import Generic\n"
        "\n"
        "\n"
        "class Sub(Base[int]):\n"
        "    pass\n"
    )
    # ``Base`` is freezable in isolation (its own module never subclasses it) ...
    assert freezable_classes(base_src) == ["Base"]
    # ... but the whole-project scan sees ``class Sub(Base[int])`` (a Subscript base
    # whose head is ``Base``) and refuses — freezing ``Base`` would make defining
    # ``Sub`` a TypeError.
    assert freeze_dataclass_decorator(base_src, [base_src, sub_src]) is None


def test_fix7_refuses_class_subclassed_via_dotted_subscripted_base():
    # FIX A: the dotted-AND-subscripted form ``class Sub(pkg.Base[int])`` — the
    # subscript head is itself a dotted ``Attribute`` (``pkg.Base``), resolved to
    # its final ``.attr`` ``"Base"``. Must also be recorded as used-as-base.
    base_src = (
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class Base:\n"
        "    x: int = 0\n"
    )
    sub_src = (
        "import pkg\n"
        "from typing import Any\n"
        "class Sub(pkg.Base[Any]):\n"
        "    pass\n"
    )
    assert freezable_classes(base_src) == ["Base"]
    assert freeze_dataclass_decorator(base_src, [base_src, sub_src]) is None


def test_fix7_subscripted_base_recorded_in_used_as_base_names():
    # FIX A, the helper directly: a subscripted base contributes its head name to
    # the used-as-base set (the bug was a silent omission here).
    from app.execution.freeze_dataclass import _used_as_base_names

    names = _used_as_base_names(["class Sub(Base[int]):\n    pass\n"])
    assert "Base" in names
    dotted = _used_as_base_names(["class Sub(pkg.Base[int]):\n    pass\n"])
    assert "Base" in dotted
