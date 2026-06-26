"""add-dataclass-order develop objective — LAND ``order=True`` on a project's own
``@dataclass`` that does NOT already set ``order=`` and defines NONE of the
comparison dunders ``__lt__``/``__le__``/``__gt__``/``__ge__`` itself.

``@dataclass(order=True)`` generates the four comparison operators from the field
tuple, so instances sort/compare by their fields — the boilerplate-killer a linter
only FLAGS but Apex WRITES. The dataclass sibling of freeze-dataclass (``frozen=True``)
and seal-total-ordering (``@functools.total_ordering``). RUNTIME-ADDITIVE:
``order=True`` only ADDS the four ops (absent today → ``a < b`` raises ``TypeError``);
the false-fill risks are closed STATICALLY (stdlib-dataclass provenance refuses
pydantic/local shadows; no existing comparison dunder in the body — else
``TypeError: Cannot overwrite attribute``; ``eq`` not disabled — else ``ValueError``;
single-line-rewritable decorator — else content loss) and the residual dynamic
field-orderability risk is closed by the full-suite gate + byte rollback.

Covers: the core transform (every decorator form — bare ``@dataclass``,
``@dataclass()``, ``@dataclass(frozen=True)`` splice, ``@dataclasses.dataclass``);
EVERY refusal (already ``order=`` / ``order=False``; ``eq=False``; a body defining
any of the four ordering dunders by ``def`` OR by assignment; ``**opts`` /
multi-line / commented decorator; non-stdlib pydantic / local shadow; non-dataclass;
syntax error; test/fixture); idempotency + determinism + trailing-newline
preservation; objective registration / reachability (available, callable spec,
reachable-from-facet, the facet-map↔registry 1:1 parity invariant, substring
safety, the north-star manifest classing it CONCRETE with the reverse tripwire
clean, the soundness-strategy declared + not scope_verify, the facet ladder
carrying the phrase with the originals still leading); the two RAISE-on-drift
audits PASS; the must-refuse-on-corpus sweep (``provenance_trap`` + ``unpack_decorator``
→ empty plan); the END-TO-END landing (``apply_rename`` verify=True lands the
``order=True`` and the suite — which SORTS instances — stays green); and the
never-fake-green capstone (a class defining ``__lt__`` is REFUSED before any apply,
so ``@dataclass(order=True)`` never reaches the ``TypeError: Cannot overwrite
attribute`` it would raise at import).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.dataclass_order import (
    add_dataclass_order,
    is_ordered_dataclass_decorator,
    orderable_classes,
)
from app.execution.objectives.add_dataclass_order import plan_add_dataclass_order

_PHRASE = "the dataclass to make orderable"

# A @dataclass with no order= and no comparison dunder — orderable.
_UNORDERED = (
    "from dataclasses import dataclass\n"
    "\n"
    "\n"
    "@dataclass\n"
    "class Point:\n"
    "    x: int = 0\n"
    "    y: int = 0\n"
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

def test_orderable_detects_dataclass_with_no_comparison_dunder():
    assert orderable_classes(_UNORDERED) == ["Point"]


def test_orderable_empty_on_syntax_error():
    assert orderable_classes("def (:\n") == []


def test_orderable_empty_once_ordered():
    out = add_dataclass_order(_UNORDERED)
    assert out is not None
    assert orderable_classes(out) == []  # already order=True — not eligible again


def test_is_ordered_decorator_true_when_order_present():
    dec = ast.parse(
        "@dataclass(order=True)\nclass P:\n    x: int = 0\n").body[0].decorator_list[0]
    assert is_ordered_dataclass_decorator(dec)


def test_is_ordered_decorator_false_for_bare_dataclass():
    dec = ast.parse("@dataclass\nclass P:\n    x: int = 0\n").body[0].decorator_list[0]
    assert not is_ordered_dataclass_decorator(dec)


# --- the core transform: rewrite (every decorator form) ---------------------

def test_order_bare_dataclass():
    out = add_dataclass_order(_UNORDERED)
    assert out is not None
    assert "@dataclass(order=True)" in out
    ast.parse(out)  # never lands broken Python


def test_order_called_dataclass_empty_parens():
    src = _UNORDERED.replace("@dataclass\n", "@dataclass()\n")
    out = add_dataclass_order(src)
    assert out is not None and "@dataclass(order=True)" in out


def test_order_called_dataclass_splices_into_existing_keyword():
    src = _UNORDERED.replace("@dataclass\n", "@dataclass(frozen=True)\n")
    out = add_dataclass_order(src)
    assert out is not None
    # The existing keyword is preserved; order is appended after it.
    assert "@dataclass(frozen=True, order=True)" in out


def test_order_dotted_dataclasses_dataclass():
    src = (
        "import dataclasses\n"
        "\n"
        "\n"
        "@dataclasses.dataclass\n"
        "class P:\n"
        "    x: int = 0\n"
    )
    out = add_dataclass_order(src)
    assert out is not None and "@dataclasses.dataclass(order=True)" in out


def test_order_preserves_decorator_indentation_is_top_level():
    out = add_dataclass_order(_UNORDERED)
    assert out is not None
    # The decorator stays at column 0 (the class is top-level).
    assert "\n@dataclass(order=True)\n" in out


# --- the core transform: REFUSALS (honest no-ops) ---------------------------

def test_refuses_already_ordered_idempotent():
    src = _UNORDERED.replace("@dataclass\n", "@dataclass(order=True)\n")
    assert add_dataclass_order(src) is None


def test_refuses_explicit_order_false():
    # An explicit ``order=False`` is a deliberate choice — never override it.
    src = _UNORDERED.replace("@dataclass\n", "@dataclass(order=False)\n")
    assert add_dataclass_order(src) is None


def test_refuses_eq_false():
    # ``order=True`` REQUIRES ``eq=True`` (the default); ``@dataclass(eq=False,
    # order=True)`` raises ``ValueError`` at class-definition time — refuse.
    src = _UNORDERED.replace("@dataclass\n", "@dataclass(eq=False)\n")
    assert add_dataclass_order(src) is None


def test_refuses_class_defining_lt():
    # A hand-written ``__lt__`` — ``@dataclass(order=True)`` would raise
    # ``TypeError: Cannot overwrite attribute __lt__`` at definition time.
    src = (
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int = 0\n"
        "    def __lt__(self, other):\n"
        "        return self.x < other.x\n"
    )
    assert add_dataclass_order(src) is None


def test_refuses_every_one_of_the_four_ordering_dunders():
    for name in ("__lt__", "__le__", "__gt__", "__ge__"):
        src = (
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class P:\n"
            "    x: int = 0\n"
            f"    def {name}(self, other):\n"
            "        return True\n"
        )
        assert add_dataclass_order(src) is None, name


def test_refuses_class_assigning_an_ordering_dunder():
    # ``__gt__ = something`` is also an attribute order=True would overwrite, and
    # an unmodelled binder — refuse.
    src = (
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int = 0\n"
        "    __gt__ = None\n"
    )
    assert add_dataclass_order(src) is None


def test_refuses_class_annassign_ordering_dunder():
    src = (
        "from dataclasses import dataclass\n"
        "from typing import Any\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int = 0\n"
        "    __le__: Any = None\n"
    )
    assert add_dataclass_order(src) is None


def test_refuses_dataclass_with_kwargs_unpacking():
    # ``@dataclass(**opts)`` — the unpacked dict's keys are unknown, so appending
    # ``order=True`` could emit ``@dataclass(**opts, order=True)``, which PARSES
    # but raises ``TypeError: got multiple values for ... 'order'`` at import.
    src = (
        "from dataclasses import dataclass\n"
        "@dataclass(**opts)\n"
        "class A:\n"
        "    x: int = 1\n"
    )
    assert add_dataclass_order(src) is None


def test_refuses_multiline_and_commented_decorators():
    multiline = (
        "from dataclasses import dataclass\n"
        "@dataclass(\n"
        "    frozen=True,\n"
        ")\n"
        "class A:\n"
        "    x: int = 0\n"
    )
    assert add_dataclass_order(multiline) is None

    commented = (
        "from dataclasses import dataclass\n"
        "@dataclass  # keep\n"
        "class A:\n"
        "    x: int = 0\n"
    )
    assert add_dataclass_order(commented) is None


def test_refuses_non_stdlib_pydantic_dataclass():
    # Only a PROVABLY-stdlib ``dataclass`` is ordered; pydantic's same-named
    # decorator is left alone (provenance gate).
    pydantic = (
        "from pydantic.dataclasses import dataclass\n"
        "@dataclass\n"
        "class M:\n"
        "    x: int = 0\n"
    )
    assert add_dataclass_order(pydantic) is None


def test_refuses_local_shadow_dataclass():
    local_def = (
        "def dataclass(c):\n"
        "    return c\n"
        "@dataclass\n"
        "class A:\n"
        "    x: int = 0\n"
    )
    assert add_dataclass_order(local_def) is None


def test_refuses_pydantic_dotted_dataclass():
    pydantic_dotted = (
        "import pydantic\n"
        "@pydantic.dataclasses.dataclass\n"
        "class M:\n"
        "    x: int = 0\n"
    )
    assert add_dataclass_order(pydantic_dotted) is None


def test_refuses_non_dataclass_class():
    assert add_dataclass_order("class P:\n    x = 1\n") is None


def test_refuses_syntax_error():
    assert add_dataclass_order("def (:\n") is None


# --- idempotency / determinism ----------------------------------------------

def test_idempotent_second_run_is_noop():
    once = add_dataclass_order(_UNORDERED)
    assert once is not None
    assert add_dataclass_order(once) is None  # 2nd run = byte-identical no-op


def test_deterministic_across_two_runs():
    a = add_dataclass_order(_UNORDERED)
    b = add_dataclass_order(_UNORDERED)
    assert a is not None and a == b


def test_preserves_trailing_newline_absence():
    out = add_dataclass_order(
        "from dataclasses import dataclass\n@dataclass\nclass P:\n    x: int = 0")
    assert out is not None and not out.endswith("\n")


# --- the runtime-additive proof (in isolation, no project) ------------------

def test_order_true_makes_sorting_work_where_it_raised_before():
    # The whole point: before, ``a < b`` raises ``TypeError``; after, sorting works.
    before_ns: dict = {}
    exec(compile(_UNORDERED, "<before>", "exec"), before_ns)  # noqa: S102
    p_before = before_ns["Point"]
    raised = False
    try:
        sorted([p_before(2, 1), p_before(1, 1)])
    except TypeError:
        raised = True
    assert raised  # comparison was absent → TypeError

    out = add_dataclass_order(_UNORDERED)
    assert out is not None
    after_ns: dict = {}
    exec(compile(out, "<after>", "exec"), after_ns)  # noqa: S102
    p_after = after_ns["Point"]
    s = sorted([p_after(2, 1), p_after(1, 1)])
    assert s[0].x == 1  # sorts by the field tuple now
    assert p_after(1, 1) < p_after(2, 1)  # __lt__ works
    assert p_after(2, 1) >= p_after(1, 1)  # __ge__ works


# --- registration / reachability --------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "add-dataclass-order" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["add-dataclass-order"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_not_expensive_nor_scope_verify():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["add-dataclass-order"]
    assert getattr(spec, "expensive", False) is False
    assert getattr(spec, "scope_verify", False) is False


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "add-dataclass-order"


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

    keys = list(FACET_OBJECTIVE_MAP)
    assert _PHRASE in keys
    for other in keys:
        if other == _PHRASE:
            continue
        assert _PHRASE not in other, f"{_PHRASE!r} is a substring of {other!r}"
        assert other not in _PHRASE, f"{other!r} is a substring of {_PHRASE!r}"


# --- PARITY ROW 1: move_value tier ------------------------------------------

def test_parity_move_value_has_add_dataclass_order_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("add_dataclass_order") == 0.45
    assert objective_value("add-dataclass-order") == 0.45
    assert objective_value("add-dataclass-order") != DEFAULT_VALUE  # not the fallback


# --- PARITY ROW 2: north-star manifest --------------------------------------

def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "add-dataclass-order" in buckets["CONCRETE"]
    # No stale manifest name (a name with no live objective) was introduced.
    assert manifest_subset_of_registry() == []


# --- PARITY ROW 3: soundness-strategy manifest ------------------------------

def test_parity_soundness_strategy_present_and_no_scope_verify_entry():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert SOUNDNESS_STRATEGY["add-dataclass-order"] == (
        "runtime-additive(generated-order-ops)+stdlib-dataclass-provenance"
        "+no-existing-comparison-dunder+static-refusal")
    assert "add-dataclass-order" not in SCOPE_VERIFY_ALLOWLIST  # full-suite gated
    assert strategy_subset_of_registry() == []  # no stale strategy entry


# --- PARITY ROW 4: facet ladder ---------------------------------------------

def test_facet_phrase_lives_in_the_no_op_statements_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["unreachable or no-op statements"]
    assert _PHRASE in ladder
    assert ladder[0] == "redundant pass statement"  # originals still lead
    # The freeze-dataclass sibling phrase still precedes the new one.
    assert ladder.index("a never-mutated dataclass to freeze") < ladder.index(_PHRASE)
    # The seal-total-ordering phrase (appended just before) also still leads it.
    assert ladder.index(
        "the comparison operators to complete from one") < ladder.index(_PHRASE)


# --- PARITY: the two RAISE-on-drift audits PASS -----------------------------

def test_north_star_and_soundness_audits_pass():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"


# --- the plan: an eligible module gets order=True ---------------------------

# A PRIVATE orderable dataclass: not public surface (the objective layer reuses
# plan_source_rewrite, which already refuses non-library files).
_UNORDERED_PRIV = (
    "from dataclasses import dataclass\n"
    "\n"
    "\n"
    "@dataclass\n"
    "class _Point:\n"
    "    x: int = 0\n"
    "    y: int = 0\n"
)


def test_plan_lands_order(tmp_path: Path):
    _project(tmp_path, "app/point.py", _UNORDERED_PRIV)
    plan = plan_add_dataclass_order(str(tmp_path), "app/point.py")
    assert plan.ok
    new = plan.new_contents["app/point.py"]
    assert "@dataclass(order=True)" in new
    assert plan.originals["app/point.py"] == _UNORDERED_PRIV  # captured for rollback
    assert plan.edits_by_file["app/point.py"] == 1


def test_plan_refuses_already_ordered(tmp_path: Path):
    _project(tmp_path, "app/point.py",
             _UNORDERED.replace("@dataclass\n", "@dataclass(order=True)\n"))
    assert not plan_add_dataclass_order(str(tmp_path), "app/point.py").new_contents


def test_plan_refuses_class_defining_lt(tmp_path: Path):
    src = (
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int = 0\n"
        "    def __lt__(self, other):\n"
        "        return self.x < other.x\n"
    )
    _project(tmp_path, "app/p.py", src)
    assert not plan_add_dataclass_order(str(tmp_path), "app/p.py").new_contents


def test_plan_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _UNORDERED)
    assert not plan_add_dataclass_order(str(tmp_path), "tests/test_x.py").new_contents


def test_plan_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", _UNORDERED)
    assert not plan_add_dataclass_order(str(tmp_path), "fixtures/sample.py").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_add_dataclass_order(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- must-refuse on the adversarial soundness corpus ------------------------

def test_refuses_on_python_soundness_corpus():
    # The two shapes this objective is DESIGNED to break (a ``**``-unpacking
    # decorator and a non-stdlib pydantic dataclass) MUST be refused (empty plan).
    from app.engine.soundness_audit import corpus_root, corpus_shapes, repo_root

    root = repo_root()
    shapes = corpus_shapes(root)
    for shape in ("unpack_decorator", "provenance_trap"):
        assert shape in shapes  # the fixture exists
        plan = plan_add_dataclass_order(str(corpus_root(root) / shape), "pkg/mod.py")
        assert not plan.new_contents, shape  # REFUSED — never land on a break shape


# --- end-to-end: gated apply, real landing, suite stays green ---------------

def test_end_to_end_lands_order_and_keeps_green(tmp_path: Path):
    # A PRIVATE (underscore-prefixed) dataclass in a package module: the order=True
    # lands and the suite — which SORTS instances — stays green.
    _suite_project(tmp_path)
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class _Point:\n"
        "    x: int = 0\n"
        "    y: int = 0\n"
    )
    (tmp_path / "app" / "point.py").write_text(src, encoding="utf-8")
    (tmp_path / "tests" / "test_point.py").write_text(
        "from app.point import _Point\n"
        "def test_sortable():\n"
        "    assert sorted([_Point(2, 0), _Point(1, 0)])[0].x == 1\n"
        "def test_lt():\n"
        "    assert _Point(1, 0) < _Point(2, 0)\n",
        encoding="utf-8")

    plan = plan_add_dataclass_order(str(tmp_path), "app/point.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "point.py").read_text(encoding="utf-8")
    assert "@dataclass(order=True)" in landed  # the order=True LANDED
    assert "class _Point:" in landed


def test_never_fake_green_refuses_class_with_existing_lt_before_apply(tmp_path: Path):
    # never-fake-green capstone: a dataclass that already defines ``__lt__`` would
    # raise ``TypeError: Cannot overwrite attribute __lt__`` at import the moment
    # ``@dataclass(order=True)`` were added. The STATIC rail refuses it BEFORE any
    # apply — the plan is empty, so nothing is ever landed (no fake green, no broken
    # import). (The runtime overwrite divergence is closed statically here, not via
    # the suite.)
    _suite_project(tmp_path)
    risky = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class _Ver:\n"
        "    major: int = 0\n"
        "\n"
        "    def __lt__(self, other):\n"
        "        return self.major < other.major\n"
    )
    (tmp_path / "app" / "ver.py").write_text(risky, encoding="utf-8")
    plan = plan_add_dataclass_order(str(tmp_path), "app/ver.py")
    assert not plan.new_contents  # REFUSED before apply — never lands a TypeError
    # The file is untouched on disk.
    assert (tmp_path / "app" / "ver.py").read_text(encoding="utf-8") == risky
