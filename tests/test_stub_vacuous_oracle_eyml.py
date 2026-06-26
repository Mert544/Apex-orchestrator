"""P0 soundness: refuse to synthesize a body when NO witness pins a value.

The vacuous-oracle fake-green: a pinned test may merely REFERENCE the stub by
name (``assert callable(fn)``) — clearing the enforceable-contract floor (the
name appears in an enforced test) and the ambiguity floor (zero witness-derived
shapes can't be >=2) — yet assert NOTHING about the stub's return value. The
value-free ``passthrough`` template (``return x``) then passes that oracle for
ANY body, so a guessed body would be stamped "verified" while the suite stays
green. That violates Apex's never-fake-green property: ``implement-stub`` /
``tdd-implement`` are CONCRETE objectives that LAND working code, so landing an
ARBITRARY body when the test pins no value is the worst failure mode.

These tests pin that:

* ``synthesize_stub_body`` REFUSES (returns ``None``) when no witness pins a value
  — and ``plan_implement_stub`` lands nothing (honest no-op, no blocker);
* the ``tdd-implement`` path (which delegates body synthesis to the same engine)
  refuses too: a RED test that only proves the function EXISTS / is callable does
  not justify an arbitrary body;
* the cheap in-process scan already AGREED the stub is not fillable — the apply
  now agrees with the scan (the unsafe disagreement is what tipped off the bug);
* the LEGITIMATE witnessed path is untouched — ``double(3)==6, double(5)==10``
  STILL lands ``n * 2`` (the regression guard that proves the floor doesn't
  over-refuse), as do the constant last-resorts (no-arg ``answer()==42`` and the
  >=2-distinct-tuple ``const``), all of which DO carry a value-pinning witness.

Deterministic, offline, stdlib-only — same project, same verdict.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.stub_synthesis import (
    StubFunction,
    _pins_a_value,
    can_fill_stub_in_process,
    pinned_test_files,
    synthesize_expr_from_witnesses,
    synthesize_stub_body,
)
from app.skills.execution.run_tests import RunTestsSkill


def _write(root: Path, rel: str, src: str) -> None:
    (root / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(src, encoding="utf-8")


def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


# --- the helper itself --------------------------------------------------------

def test_pins_a_value_false_for_callable_only_reference(tmp_path: Path):
    # ``assert callable(compute)`` references the name but pins no return value:
    # _function_witnesses is empty AND no constant is witnessed, so no value.
    _write(tmp_path, "tests/test_core.py",
           "from mylib.core import compute\n"
           "def test_callable():\n    assert callable(compute)\n")
    stub = StubFunction("compute", ("x",), 1, 2, "", False)
    assert _pins_a_value(tmp_path, ["tests/test_core.py"], stub) is False


def test_pins_a_value_true_for_equality_witness(tmp_path: Path):
    # An ``== 6`` assertion pins the return value, so the floor lets the search run.
    _write(tmp_path, "tests/test_d.py",
           "from app.d import double\n"
           "def test():\n    assert double(3) == 6\n    assert double(5) == 10\n")
    stub = StubFunction("double", ("n",), 1, 2, "", False)
    assert _pins_a_value(tmp_path, ["tests/test_d.py"], stub) is True


def test_pins_a_value_true_for_no_arg_constant(tmp_path: Path):
    # A no-arg module function's ``answer() == 42`` is a value-pinning witness
    # (empty-arg tuple), and the constant last-resort is legitimate — keep it.
    _write(tmp_path, "tests/test_ans.py",
           "from app.ans import answer\n"
           "def test_a():\n    assert answer() == 42\n")
    fn = StubFunction("answer", (), 1, 2, "", False)
    assert _pins_a_value(tmp_path, ["tests/test_ans.py"], fn) is True


def test_pins_a_value_true_for_is_none_singleton(tmp_path: Path):
    # The ``is None`` identity-equality idiom is a value-pinning witness too.
    _write(tmp_path, "tests/test_g.py",
           "from app.g import get\n"
           "def test():\n    assert get({}, 'k') is None\n")
    stub = StubFunction("get", ("d", "k"), 1, 2, "", False)
    assert _pins_a_value(tmp_path, ["tests/test_g.py"], stub) is True


# --- the engine: vacuous oracle REFUSES --------------------------------------

def test_synthesize_refuses_when_no_value_pinned(tmp_path: Path):
    # The core fix: with only ``assert callable(compute)`` pinning the stub,
    # synthesize_stub_body must REFUSE rather than stamp ``return x`` verified.
    _suite_project(tmp_path)
    _write(tmp_path, "mylib/__init__.py", "")
    _write(tmp_path, "mylib/core.py", "def compute(x):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_core.py",
           "from mylib.core import compute\n"
           "def test_callable():\n    assert callable(compute)\n")
    stub = StubFunction("compute", ("x",), 1, 2, "", False)
    tf = pinned_test_files(tmp_path, "mylib/core.py", "compute")
    assert tf == ["tests/test_core.py"]
    body = synthesize_stub_body(tmp_path, "mylib/core.py", stub, tf, RunTestsSkill())
    assert body is None  # REFUSE: no witness constrains the return


def test_apply_now_agrees_with_scan_on_vacuous_oracle(tmp_path: Path):
    # The tell-tale of the bug was the apply DISAGREEING with the scan in the
    # UNSAFE direction: the scan said NOT fillable, yet the apply landed a body.
    # After the fix both refuse — the in-process synth, the scan, and the apply.
    _suite_project(tmp_path)
    _write(tmp_path, "mylib/__init__.py", "")
    _write(tmp_path, "mylib/core.py", "def compute(x):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_core.py",
           "from mylib.core import compute\n"
           "def test_callable():\n    assert callable(compute)\n")
    stub = StubFunction("compute", ("x",), 1, 2, "", False)
    tf = pinned_test_files(tmp_path, "mylib/core.py", "compute")
    assert can_fill_stub_in_process(tmp_path, tf, stub) is False  # scan: no
    assert synthesize_expr_from_witnesses(tmp_path, tf, stub) is None  # in-proc: no
    assert synthesize_stub_body(tmp_path, "mylib/core.py", stub, tf,
                                RunTestsSkill()) is None  # apply: now no too


def test_plan_implement_stub_refuses_vacuous_oracle(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # End-of-objective view: the plan lands NOTHING and discloses no blocker
    # (an honest no-op, same as the no-spec / unsatisfiable refusal family — the
    # contract is real but it pins no value, which is not an ambiguity).
    _suite_project(tmp_path)
    _write(tmp_path, "mylib/__init__.py", "")
    original = "def compute(x):\n    raise NotImplementedError\n"
    _write(tmp_path, "mylib/core.py", original)
    _write(tmp_path, "tests/test_core.py",
           "from mylib.core import compute\n"
           "def test_callable():\n    assert callable(compute)\n")
    plan = plan_implement_stub(str(tmp_path), "mylib/core.py")
    assert not plan.new_contents and not plan.blockers
    assert (tmp_path / "mylib" / "core.py").read_text() == original  # untouched


def test_plan_implement_stub_refuses_vacuous_oracle_end_to_end(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    # End-to-end through the gated apply: even though ``return x`` keeps the
    # vacuous suite green, the objective refuses outright — nothing lands.
    _suite_project(tmp_path)
    _write(tmp_path, "mylib/__init__.py", "")
    original = "def compute(x):\n    raise NotImplementedError\n"
    _write(tmp_path, "mylib/core.py", original)
    _write(tmp_path, "tests/test_core.py",
           "from mylib.core import compute\n"
           "def test_callable():\n    assert callable(compute)\n")
    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    assert not result.steps  # nothing landed
    assert (tmp_path / "mylib" / "core.py").read_text() == original  # untouched


def test_assert_isinstance_only_reference_also_refuses(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # A second vacuous shape: the test calls the stub and only checks the result's
    # TYPE, never its value (``isinstance(parse('x'), str)`` would pass for any
    # str-returning body). No ``== expected`` witness, so REFUSE.
    _suite_project(tmp_path)
    _write(tmp_path, "mylib/__init__.py", "")
    original = "def parse(x):\n    raise NotImplementedError\n"
    _write(tmp_path, "mylib/p.py", original)
    _write(tmp_path, "tests/test_p.py",
           "from mylib.p import parse\n"
           "def test_type():\n    assert isinstance(parse('x'), str)\n")
    plan = plan_implement_stub(str(tmp_path), "mylib/p.py")
    assert not plan.new_contents and not plan.blockers
    assert (tmp_path / "mylib" / "p.py").read_text() == original


# --- the tdd-implement path: vacuous RED test REFUSES ------------------------

def test_tdd_implement_refuses_existence_only_red_test(tmp_path: Path):
    from app.execution.objectives.tdd_implement import (
        detect_missing_symbols, plan_tdd_implement,
    )

    # A RED test that only proves the function EXISTS / is callable
    # (``greet("world")`` with no assertion on the result) currently stops
    # raising the moment ANY body is inserted — but no witness pins a value, so
    # the body would be arbitrary. The delegated synthesizer now refuses.
    _suite_project(tmp_path)
    _write(tmp_path, "mylib/__init__.py", "")
    original = "VALUE = 1\n"  # greet does NOT exist yet
    _write(tmp_path, "mylib/core.py", original)
    _write(tmp_path, "tests/test_core.py",
           "from mylib.core import greet\n"
           "def test_greet_exists():\n    greet('world')\n")
    runner = RunTestsSkill()
    missing = detect_missing_symbols(tmp_path, runner)
    assert [m.name for m in missing] == ["greet"]  # detection still attributes it
    plan = plan_tdd_implement(str(tmp_path), missing[0], runner)
    assert not plan.new_contents  # REFUSE: existence alone does not pin a body
    assert (tmp_path / "mylib" / "core.py").read_text() == original  # untouched


# --- regression guard: the LEGITIMATE witnessed path STILL lands -------------

def test_legitimate_witnessed_double_still_lands(tmp_path: Path):
    # The over-refusal guard the bug report demands: witnesses ``== 6`` and
    # ``== 10`` for inputs 3 and 5 must STILL land ``n * 2``.
    _suite_project(tmp_path)
    _write(tmp_path, "app/d.py", "def double(n):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_d.py",
           "from app.d import double\n"
           "def test():\n    assert double(3) == 6\n    assert double(5) == 10\n")
    stub = StubFunction("double", ("n",), 1, 2, "", False)
    tf = pinned_test_files(tmp_path, "app/d.py", "double")
    body = synthesize_stub_body(tmp_path, "app/d.py", stub, tf, RunTestsSkill())
    assert body is not None and "return n * 2" in body


def test_legitimate_witnessed_double_lands_via_plan(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    _write(tmp_path, "app/d.py", "def double(n):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_d.py",
           "from app.d import double\n"
           "def test():\n    assert double(3) == 6\n    assert double(5) == 10\n")
    body = plan_implement_stub(str(tmp_path), "app/d.py").new_contents.get("app/d.py")
    assert body is not None and "return n * 2" in body


def test_no_arg_constant_still_lands(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # The constant last-resort path is witnessed (``answer() == 42`` is a value
    # witness), so the value-pinning floor must NOT refuse it.
    _suite_project(tmp_path)
    _write(tmp_path, "app/ans.py", "def answer():\n    ...\n")
    _write(tmp_path, "tests/test_ans.py",
           "from app.ans import answer\n"
           "def test_a():\n    assert answer() == 42\n")
    body = plan_implement_stub(str(tmp_path), "app/ans.py").new_contents.get("app/ans.py")
    assert body is not None and "return 42" in body


def test_two_distinct_tuple_constant_still_lands(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # The >=2-distinct-tuple constant (const(1)==9, const(2)==9) carries value
    # witnesses, so the floor lets it through and it still lands ``return 9``.
    _suite_project(tmp_path)
    _write(tmp_path, "app/m.py", "def const(x):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_m.py",
           "from app.m import const\n"
           "def test():\n    assert const(1) == 9\n    assert const(2) == 9\n")
    body = plan_implement_stub(str(tmp_path), "app/m.py").new_contents.get("app/m.py")
    assert body is not None and "return 9" in body


def test_genuine_passthrough_still_lands(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # A GENUINE passthrough is pinned by a VALUE witness (``echo(7) == 7``), not a
    # vacuous reference — so the floor passes and ``return x`` legitimately lands.
    # This separates "passthrough that fake-greens a vacuous oracle" (refused)
    # from "passthrough the witnesses actually determine" (landed).
    _suite_project(tmp_path)
    _write(tmp_path, "app/p.py", "def echo(x):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_p.py",
           "from app.p import echo\n"
           "def test_p():\n    assert echo(7) == 7\n    assert echo('hi') == 'hi'\n")
    body = plan_implement_stub(str(tmp_path), "app/p.py").new_contents.get("app/p.py")
    assert body is not None and "return x" in body


def test_refusal_is_deterministic(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # Same vacuous project twice -> identically refused (no time/random).
    _suite_project(tmp_path)
    _write(tmp_path, "mylib/__init__.py", "")
    _write(tmp_path, "mylib/core.py", "def compute(x):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_core.py",
           "from mylib.core import compute\n"
           "def test_callable():\n    assert callable(compute)\n")
    a = plan_implement_stub(str(tmp_path), "mylib/core.py").new_contents.get("mylib/core.py")
    b = plan_implement_stub(str(tmp_path), "mylib/core.py").new_contents.get("mylib/core.py")
    assert a is None and b is None and a == b
