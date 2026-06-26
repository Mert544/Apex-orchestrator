"""seal-total-ordering develop objective — LAND ``@functools.total_ordering`` on a
project's own regular class that defines ``__eq__`` AND EXACTLY ONE of the ordering
dunders ``__lt__`` / ``__le__`` / ``__gt__`` / ``__ge__`` but is MISSING the other
three.

``@functools.total_ordering`` FILLS the three absent comparison operators from the one
the author wrote plus ``__eq__`` (and explicitly SKIPS any operator already present),
so the change is RUNTIME-ADDITIVE: ``a <= b`` / ``a > b`` / ``a >= b`` start behaving
consistently where they were previously absent → ``TypeError``. The honesty risk —
landing it where the author intended an asymmetric / partial comparison — is closed by
the STATIC RAIL (refuse unless ``__eq__`` is defined in THIS class body AND exactly ONE
order op is defined AND none of the other three are) PLUS the suite gate + auto-rollback.

Covers: the core transform (fresh ``from functools import total_ordering`` insert;
widen an existing ``from functools import ...``; the dotted
``@functools.total_ordering`` fallback when ``total_ordering`` is shadowed but
``functools`` is bound; decorator/indent preservation; trailing-newline preservation)
plus EVERY refusal — no body-``__eq__``, an inherited-only ``__eq__``, zero / two /
all-four order ops, an already-``@total_ordering`` class, ``functools`` not spellable, a
lambda/assignment-defined dunder, an unmodelled class-body binder, a syntax error; plus
idempotency and determinism; objective registration / reachability (available, callable
spec, reachable-from-facet, the facet-map<->registry 1:1 parity invariant,
substring-safety, the north-star manifest classing it CONCRETE with the reverse tripwire
clean, the move-value tier + no-phantom-row, the soundness strategy declared + not
scope_verify, the facet ladder carrying the phrase with the originals still leading);
the plan + END-TO-END landing (``apply_rename`` verify=True adds the decorator in place,
the suite stays green, and the three filled operators actually work); the must-refuse
sweep over the Python soundness corpus; and the never-fake-green capstone (a refusal
case lands nothing before any apply).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.objectives.seal_total_ordering import plan_seal_total_ordering
from app.execution.total_ordering import (
    class_has_total_ordering_decorator,
    orderable_classes,
    seal_total_ordering,
)

# An eligible class with only ``from functools import reduce``: gains ``total_ordering``
# widened into the import + ``@total_ordering`` directly above the class.
_CLS = (
    '"""A point class."""\n'
    "\n"
    "from functools import reduce\n"
    "\n"
    "\n"
    "class Point:\n"
    "    def __init__(self, x):\n"
    "        self.x = x\n"
    "\n"
    "    def __eq__(self, other):\n"
    "        return self.x == other.x\n"
    "\n"
    "    def __lt__(self, other):\n"
    "        return self.x < other.x\n"
)

_PHRASE = "the comparison operators to complete from one"

# Reusable body fragments (one method per fragment).
_EQ = "    def __eq__(self, o):\n        return self.x == o.x\n"
_LT = "    def __lt__(self, o):\n        return self.x < o.x\n"
_LE = "    def __le__(self, o):\n        return self.x <= o.x\n"
_GT = "    def __gt__(self, o):\n        return self.x > o.x\n"
_GE = "    def __ge__(self, o):\n        return self.x >= o.x\n"


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

def test_orderable_detects_eq_plus_one_order_op():
    src = "from functools import total_ordering\nclass C:\n" + _EQ + _LT
    assert orderable_classes(src) == ["C"]


def test_orderable_detects_each_single_order_op():
    base = "from functools import total_ordering\nclass C:\n" + _EQ
    assert orderable_classes(base + _LT) == ["C"]
    assert orderable_classes(base + _LE) == ["C"]
    assert orderable_classes(base + _GT) == ["C"]
    assert orderable_classes(base + _GE) == ["C"]


def test_has_total_ordering_true_bare():
    cls = ast.parse("@total_ordering\nclass C:\n    pass\n").body[0]
    assert class_has_total_ordering_decorator(cls)


def test_has_total_ordering_true_dotted():
    cls = ast.parse("@functools.total_ordering\nclass C:\n    pass\n").body[0]
    assert class_has_total_ordering_decorator(cls)


def test_has_total_ordering_false_when_absent():
    cls = ast.parse("@register\nclass C:\n    pass\n").body[0]
    assert not class_has_total_ordering_decorator(cls)


# --- the core transform: rewrite --------------------------------------------

def test_adds_total_ordering_and_widens_functools_import():
    out = seal_total_ordering(_CLS)
    assert out is not None
    lines = out.splitlines()
    assert lines[0] == '"""A point class."""'  # docstring stays first
    # The functools import is widened in place to add ``total_ordering`` (no 2nd line).
    assert out.count("from functools import") == 1
    assert "from functools import reduce, total_ordering" in lines
    assert "@total_ordering" in out
    assert "class Point:" in out
    ast.parse(out)  # never lands broken Python


def test_total_ordering_sits_directly_above_the_class():
    out = seal_total_ordering(_CLS)
    assert out is not None
    assert "\n@total_ordering\nclass Point:\n" in out


def test_inserts_fresh_functools_import_when_none_present():
    src = "class C:\n" + _EQ + _GT
    out = seal_total_ordering(src)
    assert out is not None
    assert out.splitlines()[0] == "from functools import total_ordering"
    assert "@total_ordering" in out
    ast.parse(out)


def test_inserts_fresh_import_when_no_clean_functools_import():
    # A parenthesized multi-line ``from functools import (...)`` is NOT cleanly
    # widenable, so a fresh ``from functools import total_ordering`` line is inserted
    # (the block is not corrupted) and the seal LANDS.
    src = (
        "from functools import (\n"
        "    reduce,\n"
        ")\n"
        "\n"
        "\n"
        "class C:\n" + _EQ + _LT
    )
    out = seal_total_ordering(src)
    assert out is not None
    assert "@total_ordering" in out
    ast.parse(out)
    assert "from functools import (" in out  # original block untouched
    assert "from functools import total_ordering" in out  # fresh 2nd import line


def test_uses_dotted_total_ordering_when_name_shadowed():
    # ``total_ordering`` is shadowed by a local def, but ``functools`` is bound bare —
    # so the dotted ``@functools.total_ordering`` is provable and used (and NO
    # ``from functools import total_ordering`` is added, which would re-bind the
    # shadowed name).
    src = (
        "import functools\n"
        "\n"
        "\n"
        "def total_ordering(c):\n"
        "    return c\n"
        "\n"
        "\n"
        "class C:\n" + _EQ + _LT
    )
    out = seal_total_ordering(src)
    assert out is not None
    assert "@functools.total_ordering" in out
    assert "from functools import total_ordering" not in out  # shadow not re-imported
    ast.parse(out)


def test_preserves_existing_decorator():
    src = "from functools import total_ordering\n@register\nclass C:\n" + _EQ + _LT
    out = seal_total_ordering(src)
    assert out is not None
    # The existing decorator stays; @total_ordering is added directly above the class.
    assert "@register\n@total_ordering\nclass C:" in out
    ast.parse(out)


def test_preserves_trailing_newline_absence():
    src = ("from functools import total_ordering\nclass C:\n"
           "    def __eq__(self, o): return self.x == o.x\n"
           "    def __lt__(self, o): return self.x < o.x")
    out = seal_total_ordering(src)
    assert out is not None and not out.endswith("\n")


# --- the core transform: REFUSALS (honest no-ops, the soundness surface) -----

def test_refuses_no_eq_in_body():
    src = "from functools import total_ordering\nclass C:\n" + _LT
    assert seal_total_ordering(src) is None  # no provable __eq__ — refuse


def test_refuses_inherited_only_eq():
    # ``__eq__`` lives on a BASE class, not in this body — not provably present here
    # (mirroring synthesize-dunders' inherited-eq rail), so refuse.
    src = (
        "from functools import total_ordering\n"
        "class B:\n" + _EQ +
        "class C(B):\n" + _LT
    )
    # The base ``B`` has __eq__ but no order op (refused); the derived ``C`` has an
    # order op but only an inherited __eq__ (refused) — nothing lands.
    assert seal_total_ordering(src) is None


def test_refuses_zero_order_ops():
    src = "from functools import total_ordering\nclass C:\n" + _EQ + "    pass\n"
    assert seal_total_ordering(src) is None  # has __eq__ but no order op


def test_refuses_two_order_ops():
    src = "from functools import total_ordering\nclass C:\n" + _EQ + _LT + _GT
    assert seal_total_ordering(src) is None  # already has more than one — ambiguous


def test_refuses_all_four_order_ops():
    src = ("from functools import total_ordering\nclass C:\n"
           + _EQ + _LT + _LE + _GT + _GE)
    assert seal_total_ordering(src) is None  # already total — nothing to fill


def test_refuses_already_total_ordering_bare_idempotent():
    src = ("from functools import total_ordering\n@total_ordering\nclass C:\n"
           + _EQ + _LT)
    assert seal_total_ordering(src) is None


def test_refuses_already_functools_total_ordering_idempotent():
    src = "import functools\n@functools.total_ordering\nclass C:\n" + _EQ + _LT
    assert seal_total_ordering(src) is None


def test_refuses_lambda_assigned_order_op():
    # ``__lt__`` bound by a lambda assignment, not a ``def`` — unmodelled, refuse.
    src = ("from functools import total_ordering\nclass C:\n" + _EQ +
           "    __lt__ = lambda self, o: True\n")
    assert seal_total_ordering(src) is None


def test_refuses_assignment_defined_eq():
    # ``__eq__`` bound by assignment, not a ``def`` — not a provable body def, refuse.
    src = ("from functools import total_ordering\nclass C:\n"
           "    __eq__ = object.__eq__\n" + _LT)
    assert seal_total_ordering(src) is None


def test_refuses_unmodelled_class_body_binder():
    for_body = ("from functools import total_ordering\nclass C:\n" + _EQ + _LT +
                "    for i in range(2):\n        pass\n")
    if_body = ("from functools import total_ordering\nclass C:\n" + _EQ + _LT +
               "    if True:\n        __gt__ = None\n")
    while_body = ("from functools import total_ordering\nclass C:\n" + _EQ + _LT +
                  "    while False:\n        pass\n")
    assert seal_total_ordering(for_body) is None
    assert seal_total_ordering(if_body) is None
    assert seal_total_ordering(while_body) is None


def test_refuses_when_total_ordering_shadowed_and_no_usable_functools():
    # ``total_ordering`` shadowed by a local def and ``functools`` not bound bare — no
    # provable spelling of ``functools.total_ordering``, so refuse.
    src = ("def total_ordering(c):\n    return c\n\n\nclass C:\n" + _EQ + _LT)
    assert seal_total_ordering(src) is None


def test_refuses_when_total_ordering_bound_to_another_module():
    # ``total_ordering`` imported from a DIFFERENT module — a bare ``@total_ordering``
    # would not be ``functools.total_ordering``, and ``functools`` is not bound — refuse.
    src = ("from foo import total_ordering\n\n\nclass C:\n" + _EQ + _LT)
    assert seal_total_ordering(src) is None


def test_refuses_syntax_error():
    assert seal_total_ordering("def (:\n") is None


def test_refuses_plain_non_comparison_class():
    src = "from functools import total_ordering\nclass C:\n    x = 1\n"
    assert seal_total_ordering(src) is None  # no __eq__, no order op


# --- idempotency / determinism ----------------------------------------------

def test_idempotent_second_run_is_noop():
    once = seal_total_ordering(_CLS)
    assert once is not None
    assert seal_total_ordering(once) is None  # 2nd run = byte-identical no-op


def test_deterministic_across_two_runs():
    a = seal_total_ordering(_CLS)
    b = seal_total_ordering(_CLS)
    assert a is not None and a == b


# --- registration / reachability --------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "seal-total-ordering" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["seal-total-ordering"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "seal-total-ordering"


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
    assert "seal-total-ordering" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_move_value_tier_matches_synthesize_dunders():
    from app.engine.move_value import move_value, objective_value

    # Tier-2 structural value, the same 0.50 band as its sibling synthesize_dunders.
    assert move_value("seal_total_ordering") == 0.50
    assert move_value("seal_total_ordering") == move_value("synthesize_dunders")
    assert objective_value("seal-total-ordering") == 0.50


def test_move_value_table_has_no_phantom_and_covers_operator():
    # Reuse the authoritative drift checks: the operator is tiered and the table has
    # no stale row (the dash->underscore convention needs no OBJECTIVE_OPERATOR).
    from tests.test_move_value import _emitted_operators
    from app.engine.move_value import OPERATOR_VALUE

    ops = _emitted_operators()
    assert "seal_total_ordering" in ops
    assert sorted(op for op in ops if op not in OPERATOR_VALUE) == []
    assert sorted(op for op in OPERATOR_VALUE if op not in ops) == []


def test_soundness_strategy_declared_and_not_scope_verify():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert "seal-total-ordering" in SOUNDNESS_STRATEGY
    assert SOUNDNESS_STRATEGY["seal-total-ordering"]  # non-empty strategy string
    assert "seal-total-ordering" not in SCOPE_VERIFY_ALLOWLIST  # full-suite gated
    assert strategy_subset_of_registry() == []  # no stale strategy entry


def test_facet_phrase_lives_in_the_noop_statements_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["unreachable or no-op statements"]
    assert _PHRASE in ladder
    assert ladder[0] == "redundant pass statement"  # originals still lead


def test_north_star_and_soundness_audits_pass():
    # The two RAISE-on-drift audits both PASS with the new objective wired (parity 1:1).
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"


def test_refuses_on_python_soundness_corpus():
    # Every adversarial corpus shape: seal-total-ordering must REFUSE (none carries the
    # body-eq + exactly-one-order-op shape) — never land a change.
    from app.engine.soundness_audit import (
        corpus_refusal_findings,
        repo_root,
    )

    findings = corpus_refusal_findings(repo_root())
    verdicts = findings.get("seal-total-ordering", {})
    assert verdicts  # the objective was swept
    for shape, verdict in verdicts.items():
        assert verdict in ("refused", "behavior-identical"), (shape, verdict)
        assert not verdict.startswith("VIOLATION"), (shape, verdict)


# --- the plan: an eligible class gets @total_ordering ------------------------

def test_plan_lands_total_ordering(tmp_path: Path):
    _project(tmp_path, "app/point.py", _CLS)
    plan = plan_seal_total_ordering(str(tmp_path), "app/point.py")
    assert plan.ok
    new = plan.new_contents["app/point.py"]
    assert "@total_ordering" in new
    assert "from functools import reduce, total_ordering" in new
    assert plan.originals["app/point.py"] == _CLS  # original captured for rollback
    assert plan.edits_by_file["app/point.py"] == 1


def test_plan_refuses_no_order_op_class(tmp_path: Path):
    _project(tmp_path, "app/point.py",
             "from functools import total_ordering\nclass C:\n" + _EQ + "    pass\n")
    assert not plan_seal_total_ordering(str(tmp_path), "app/point.py").new_contents


def test_plan_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _CLS)
    assert not plan_seal_total_ordering(str(tmp_path), "tests/test_x.py").new_contents


def test_plan_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", _CLS)
    assert not plan_seal_total_ordering(str(tmp_path), "fixtures/sample.py").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_seal_total_ordering(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: gated apply, real landing, suite stays green ----------------

def test_end_to_end_lands_total_ordering_and_keeps_green(tmp_path: Path):
    _suite_project(tmp_path)
    src = (
        "from functools import total_ordering\n"
        "\n"
        "\n"
        "class Measure:\n"
        "    def __init__(self, n):\n"
        "        self.n = n\n"
        "\n"
        "    def __eq__(self, other):\n"
        "        return self.n == other.n\n"
        "\n"
        "    def __lt__(self, other):\n"
        "        return self.n < other.n\n"
    )
    (tmp_path / "app" / "measure.py").write_text(src, encoding="utf-8")
    (tmp_path / "tests" / "test_measure.py").write_text(
        "from app.measure import Measure\n"
        "def test_ops():\n"
        "    a, b = Measure(1), Measure(2)\n"
        "    assert a < b and a <= b\n"
        "    assert b > a and b >= a\n"
        "    assert a != b\n",
        encoding="utf-8")

    plan = plan_seal_total_ordering(str(tmp_path), "app/measure.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "measure.py").read_text(encoding="utf-8")
    assert "@total_ordering" in landed  # the decorator LANDED

    # The three filled operators actually WORK now (proven green by the apply gate):
    # exec the landed module and exercise <=, >, >= consistently with __eq__/__lt__.
    ns: dict[str, object] = {}
    exec(compile(landed, "<landed>", "exec"), ns)  # noqa: S102 - test-only
    cls = ns["Measure"]
    a, b = cls(1), cls(2)  # type: ignore[operator]
    assert (a <= b) and (b > a) and (b >= a)  # newly filled by @total_ordering
    assert not (a > b) and not (a >= b)
    assert (a < b) and (a != b)  # the author's original ops still hold


def test_never_lands_total_ordering_on_ineligible_class(tmp_path: Path):
    # The behavioural soundness capstone. A class with NO body-``__eq__`` (only an
    # inherited one) is NOT provably eligible, so the static rail REFUSES it before any
    # apply — the false fill that could mis-state a partial order never lands.
    _project(tmp_path, "app/ineligible.py",
             "from functools import total_ordering\nclass C:\n" + _LT)
    plan = plan_seal_total_ordering(str(tmp_path), "app/ineligible.py")
    assert not plan.new_contents  # refused before any apply
