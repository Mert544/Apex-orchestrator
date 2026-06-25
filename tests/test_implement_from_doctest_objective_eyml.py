"""implement-from-doctest develop objective — fill a STUB's body FROM ITS OWN
docstring ``>>>`` examples, keeping it ONLY when every example passes.

This is the docstring-PRIMARY twin of implement-stub: where implement-stub needs a
pinned ``test_*.py`` file, this objective serves the half-finished case where the
contract is written as a worked example and no test file exists yet. It REUSES the
stub_synthesis template space + doctest oracle read-only; a body is emitted only
after it reproduces every ``>>>`` example, else the stub is REFUSED.

Covers: the trigger (a doctest-only stub is detected; a stub that ALREADY has a
pinned test is DISTINCT — left to implement-stub); the plan LANDING a verified body
+ the docstring kept intact; the never-fake-green REFUSALS (examples no fixed
template reproduces → land nothing; an AMBIGUOUS contract → refuse + disclose "add a
discriminating example" through ``blockers``; a stub with NO doctest → no-op; a
fixture/test/unreadable path → no-op); idempotence + determinism; the cheap
fitness/move scan; the END-TO-END verified apply landing the body; and the
registration / facet 1:1-parity / north-star CONCRETE / soundness-strategy /
scope_verify-allowlist invariants the four registry files must keep in sync.
"""

from __future__ import annotations

import doctest
from pathlib import Path
import types

from app.execution.cross_file_rename import apply_rename
from app.execution.objectives.implement_from_doctest import (
    _doctest_primary_stubs,
    fitness,
    moves,
    plan_implement_from_doctest,
)

_PHRASE = "the worked example to satisfy"

# A doctest-only stub: contract is its OWN ``>>>`` examples, no test file. Two
# distinct witness tuples → a parametric template (``n * 2``) is provable.
_DOUBLE = (
    "def double(n):\n"
    '    """Double n.\n\n'
    "    >>> double(3)\n"
    "    6\n"
    "    >>> double(5)\n"
    "    10\n"
    '    """\n'
    "    raise NotImplementedError\n"
)


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def _doctest_is_green(source: str) -> bool:
    """True when EVERY ``>>>`` example in ``source`` passes — the contract the
    objective claims to have satisfied, re-checked independently with stdlib
    ``doctest`` (the buyer's own verification)."""
    module = types.ModuleType("apex_ifd_mod")
    exec(compile(source, "apex_ifd_mod.py", "exec"), module.__dict__)  # noqa: S102 - test-only
    result = doctest.testmod(module, verbose=False)
    return result.attempted > 0 and result.failed == 0


# --- the trigger: a doctest-only stub is detected (and distinct) --------------

def test_detects_doctest_only_stub(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _DOUBLE)
    stubs = _doctest_primary_stubs(_DOUBLE, tmp_path, "app/calc.py")
    assert [s.name for s in stubs] == ["double"]


def test_stub_with_pinned_test_is_left_to_implement_stub(tmp_path: Path):
    # DISTINCTNESS: a stub that ALREADY has a pinned ``test_*.py`` file is
    # implement-stub's; this objective refuses it, so the two never double-count.
    _project(tmp_path, "app/calc.py", _DOUBLE)
    _project(tmp_path, "tests/test_calc.py",
             "from app.calc import double\n"
             "def test_d():\n    assert double(3) == 6\n")
    assert _doctest_primary_stubs(_DOUBLE, tmp_path, "app/calc.py") == []
    plan = plan_implement_from_doctest(str(tmp_path), "app/calc.py")
    assert not plan.new_contents  # implement-stub owns it — we land nothing


def test_stub_without_examples_is_not_ours(tmp_path: Path):
    src = ('def f(n):\n    """Prose only, no examples."""\n'
           "    raise NotImplementedError\n")
    _project(tmp_path, "app/m.py", src)
    assert _doctest_primary_stubs(src, tmp_path, "app/m.py") == []


# --- the plan: a doctest-only stub gets a verified body ------------------------

def test_plan_lands_verified_body(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _DOUBLE)
    plan = plan_implement_from_doctest(str(tmp_path), "app/calc.py")
    assert plan.ok
    filled = plan.new_contents["app/calc.py"]
    assert "return n * 2" in filled
    assert ">>> double(3)" in filled  # the docstring contract is kept intact
    assert _doctest_is_green(filled)
    assert plan.originals["app/calc.py"] == _DOUBLE  # original captured for rollback
    assert plan.edits_by_file["app/calc.py"] == 1


def test_plan_scan_does_not_mutate_the_tree(tmp_path: Path):
    # The plan derivation is pure in-memory — the file on disk is unchanged (the
    # verified-apply engine, not the planner, performs the real write).
    _project(tmp_path, "app/calc.py", _DOUBLE)
    plan_implement_from_doctest(str(tmp_path), "app/calc.py")
    assert (tmp_path / "app" / "calc.py").read_text(encoding="utf-8") == _DOUBLE


def test_string_returning_stub_lands_from_examples(tmp_path: Path):
    # The template space covers f-string formatting, so a string contract written
    # as examples lands too — a real, working body from the author's own example.
    src = (
        "def greet(name):\n"
        '    """Greet someone.\n\n'
        "    >>> greet('Bob')\n"
        "    'Hello, Bob!'\n"
        "    >>> greet('Al')\n"
        "    'Hello, Al!'\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    _project(tmp_path, "app/g.py", src)
    plan = plan_implement_from_doctest(str(tmp_path), "app/g.py")
    assert plan.ok
    assert _doctest_is_green(plan.new_contents["app/g.py"])


# --- never-fake-green REFUSALS (honest no-ops) --------------------------------

def test_unsatisfiable_examples_land_nothing(tmp_path: Path):
    # Examples no single fixed template reproduces (1->100, 2->7, 3->42) pin no
    # synthesizable contract — REFUSE (an under-claim, never a fake-green guess).
    src = (
        "def lookup(n):\n"
        '    """\n'
        "    >>> lookup(1)\n"
        "    100\n"
        "    >>> lookup(2)\n"
        "    7\n"
        "    >>> lookup(3)\n"
        "    42\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    _project(tmp_path, "app/m.py", src)
    plan = plan_implement_from_doctest(str(tmp_path), "app/m.py")
    assert not plan.ok
    assert "app/m.py" not in plan.new_contents
    assert plan.blockers == []  # unsatisfiable (not ambiguous) — nothing to disclose


def test_ambiguous_examples_refuse_and_disclose(tmp_path: Path):
    # Thin examples matched by >=2 templates that DIVERGE off-example
    # (``n > 5`` vs ``n % 2 == 0``) are ambiguous — REFUSE and disclose WHY+HOW
    # through the plan's ``blockers`` channel ("add a discriminating test").
    src = (
        "def f(n):\n"
        '    """\n'
        "    >>> f(5)\n"
        "    False\n"
        "    >>> f(200)\n"
        "    True\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    _project(tmp_path, "app/m.py", src)
    plan = plan_implement_from_doctest(str(tmp_path), "app/m.py")
    assert not plan.new_contents  # nothing lands on an ambiguous contract
    assert any("ambiguous" in b and "f" in b for b in plan.blockers)
    assert any("discriminating" in b for b in plan.blockers)


def test_no_doctest_stub_is_a_noop(tmp_path: Path):
    src = ('def f(n):\n    """No examples here."""\n    raise NotImplementedError\n')
    _project(tmp_path, "app/m.py", src)
    plan = plan_implement_from_doctest(str(tmp_path), "app/m.py")
    assert not plan.new_contents
    assert not plan.blockers


def test_non_stub_is_untouched(tmp_path: Path):
    # A function that is ALREADY implemented (even with examples) is not a stub —
    # idempotence: nothing to do.
    src = (
        "def double(n):\n"
        '    """Double.\n\n    >>> double(3)\n    6\n    """\n'
        "    return n * 2\n"
    )
    _project(tmp_path, "app/m.py", src)
    assert _doctest_primary_stubs(src, tmp_path, "app/m.py") == []
    assert not plan_implement_from_doctest(str(tmp_path), "app/m.py").new_contents


def test_fixture_and_test_paths_refused(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _DOUBLE)
    _project(tmp_path, "fixtures/sample.py", _DOUBLE)
    assert not plan_implement_from_doctest(str(tmp_path), "tests/test_x.py").new_contents
    assert not plan_implement_from_doctest(str(tmp_path), "fixtures/sample.py").new_contents


def test_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_implement_from_doctest(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- idempotence / determinism ------------------------------------------------

def test_idempotent_second_plan_is_noop(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _DOUBLE)
    plan = plan_implement_from_doctest(str(tmp_path), "app/calc.py")
    filled = plan.new_contents["app/calc.py"]
    # Re-deriving against the ALREADY-FILLED source is a no-op (not a stub anymore).
    _project(tmp_path, "app/calc.py", filled)
    assert not plan_implement_from_doctest(str(tmp_path), "app/calc.py").new_contents


def test_deterministic_across_two_runs(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _DOUBLE)
    a = plan_implement_from_doctest(str(tmp_path), "app/calc.py").new_contents
    b = plan_implement_from_doctest(str(tmp_path), "app/calc.py").new_contents
    assert a and a == b


# --- the cheap fitness / move scan --------------------------------------------

def test_fitness_counts_doctest_fillable_modules(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    (tmp_path / "app" / "calc.py").write_text(_DOUBLE, encoding="utf-8")
    assert fitness(str(tmp_path)) == 1.0
    targets = [m.target for m in moves(str(tmp_path))]
    assert "app/calc.py:implement-from-doctest" in targets


def test_fitness_zero_when_nothing_doctest_fillable(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    (tmp_path / "app" / "done.py").write_text(
        "def f(n):\n    return n\n", encoding="utf-8")
    assert fitness(str(tmp_path)) == 0.0
    assert moves(str(tmp_path)) == []


# --- end-to-end: gated apply, real landing, doctest-green ---------------------

def test_end_to_end_lands_body_and_is_doctest_green(tmp_path: Path):
    # The full verified-apply engine writes the doctest-verified fill and keeps it
    # (no test regresses), so the body genuinely LANDS on disk — a real
    # contribution, not just a plan.
    (tmp_path / "m.py").write_text(_DOUBLE, encoding="utf-8")
    plan = plan_implement_from_doctest(str(tmp_path), "m.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=True)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)
    landed = (tmp_path / "m.py").read_text(encoding="utf-8")
    assert "return n * 2" in landed
    assert _doctest_is_green(landed)


def test_verified_apply_rolls_back_when_impacted_suite_red(tmp_path: Path):
    # never-fake-green at the engine level: even a correctly doctest-verified fill
    # is ROLLED BACK if a co-located, currently-green pytest test regresses. A
    # sibling's test imports the module and is red, so the impacted-scope gate fails
    # after the (doctest-correct) fill and the engine restores the stub byte-for-byte.
    src = _DOUBLE + "\n\ndef other():\n    return 1\n"
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    (tmp_path / "test_m.py").write_text(
        "from m import other\n"
        "def test_other():\n"
        "    assert other() == 2\n",  # RED: other() returns 1
        encoding="utf-8")
    plan = plan_implement_from_doctest(str(tmp_path), "m.py")
    assert plan.ok  # the doctest fill IS synthesizable + verified
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=True)
    assert result.get("rolled_back") is True
    assert (tmp_path / "m.py").read_text(encoding="utf-8") == src  # restored exactly


# --- registration / reachability / the four-registry parity invariants --------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "implement-from-doctest" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["implement-from-doctest"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is True and spec.scope_verify is True


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "implement-from-doctest"


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
    assert "implement-from-doctest" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_soundness_strategy_declared_and_scope_verify_allowed():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        check_scope_verify_allowlist,
        strategy_completeness,
        strategy_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    names = list(available_objectives())
    table = strategy_completeness(names)  # raises if undeclared
    assert "implement-from-doctest" in table
    assert strategy_subset_of_registry() == []
    assert "implement-from-doctest" in SCOPE_VERIFY_ALLOWLIST
    ok, reasons = check_scope_verify_allowlist()
    assert ok, reasons


def test_facet_phrase_lives_in_the_contract_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["the missing operation on the contract"]
    assert _PHRASE in ladder
    assert ladder[0] == "the operation signature"  # originals still lead


def test_both_self_audits_pass():
    # The denetçi must stay green with the new objective wired in.
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    root = repo_root()
    assert north_star_report(root)["verdict"] == "PASS"
    assert soundness_report(root)["verdict"] == "PASS"
