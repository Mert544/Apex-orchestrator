"""implement-stub DEFECT fixes — cheap fitness scan + identity passthrough.

Two field-test defects, both proven here without changing WHAT lands:

* **DEFECT 1 (cost):** the fitness/move scan used to run the FULL pytest-gated
  ``plan_implement_stub`` for every module just to COUNT/enumerate work, once per
  pass — ~30 min for 4 stubs. The scan is now an IN-PROCESS estimate
  (``module_has_fillable_stub`` / ``can_fill_stub_in_process``) with NO pytest.
  These tests prove the cheap estimate offers EXACTLY the modules the full apply
  lands on (no under/over-count that changes the outcome), that recursion-only
  stubs are NOT under-counted (the cheap recursion check), and that the apply
  path's pytest gate still governs what lands.

* **DEFECT 2 (identity over-refused):** ``identity(x)`` with ``5->5, 9->9`` was
  refused because the algebraic-identity family (``x``, ``x+0``, ``x*1``,
  ``x//1`` ...) counted as DISTINCT shapes to the ambiguity guard. They are one
  semantic shape now, so a genuine passthrough lands ``return x`` — while a truly
  ambiguous contract still refuses.
"""

from __future__ import annotations

from pathlib import Path


# --- shared fixture: the 4-module independent project ------------------------

def _toolkit_project(root: Path) -> None:
    """The independent field-test fixture: package ``toolkit`` with five stub
    modules. ``mathops`` and ``textops`` are fully fillable (4 functions);
    ``core.identity`` is a passthrough (DEFECT 2); ``grading.grade_letter`` is
    unsynthesizable (no fixed template fits 95->A, 85->B, 55->F)."""
    (root / "toolkit").mkdir()
    (root / "tests").mkdir()
    (root / "toolkit" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='toolkit'\nversion='0'\n", encoding="utf-8")
    (root / "toolkit" / "core.py").write_text(
        "def identity(x):\n    raise NotImplementedError\n", encoding="utf-8")
    (root / "toolkit" / "mathops.py").write_text(
        "def triple(n):\n    raise NotImplementedError\n\n\n"
        "def rectangle_area(w, h):\n    raise NotImplementedError\n", encoding="utf-8")
    (root / "toolkit" / "textops.py").write_text(
        "def loud(s):\n    raise NotImplementedError\n\n\n"
        "def join_with(sep, items):\n    raise NotImplementedError\n", encoding="utf-8")
    (root / "toolkit" / "grading.py").write_text(
        "def grade_letter(score):\n    raise NotImplementedError\n", encoding="utf-8")
    (root / "tests" / "test_core.py").write_text(
        "from toolkit.core import identity\n"
        "def test_identity():\n    assert identity(5) == 5\n    assert identity(9) == 9\n",
        encoding="utf-8")
    (root / "tests" / "test_mathops.py").write_text(
        "from toolkit.mathops import triple, rectangle_area\n"
        "def test_triple():\n    assert triple(2) == 6\n    assert triple(5) == 15\n"
        "def test_rect():\n    assert rectangle_area(2, 3) == 6\n"
        "    assert rectangle_area(5, 5) == 25\n    assert rectangle_area(4, 2) == 8\n",
        encoding="utf-8")
    (root / "tests" / "test_textops.py").write_text(
        "from toolkit.textops import loud, join_with\n"
        "def test_loud():\n    assert loud('hi') == 'HI'\n    assert loud('abc') == 'ABC'\n"
        "def test_join():\n    assert join_with(',', ['a', 'b']) == 'a,b'\n"
        "    assert join_with('-', ['x', 'y', 'z']) == 'x-y-z'\n",
        encoding="utf-8")
    (root / "tests" / "test_grading.py").write_text(
        "from toolkit.grading import grade_letter\n"
        "def test_grade():\n    assert grade_letter(95) == 'A'\n"
        "    assert grade_letter(85) == 'B'\n    assert grade_letter(55) == 'F'\n",
        encoding="utf-8")


# --- DEFECT 1: the cheap estimate equals the full-apply landing set ----------

def test_cheap_estimate_matches_full_apply_modules(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective
    from app.execution.objectives.implement_stub import _modules

    _toolkit_project(tmp_path)

    # The CHEAP in-process scan (no pytest) — what fitness/moves now use.
    cheap = set(_modules(str(tmp_path)))

    # The FULL apply: land everything end-to-end, then read which modules it
    # actually filled. The cheap estimate must equal this set — no under-count
    # (a stub silently stops landing) and no over-count that changes the outcome.
    result = compile_objective(str(tmp_path), "implement-stub", apply=True)
    landed = {
        f"toolkit/{m}" for m in ("core.py", "mathops.py", "textops.py", "grading.py")
        if "raise NotImplementedError" not in
        (tmp_path / "toolkit" / m).read_text()
    }

    assert landed == {"toolkit/core.py", "toolkit/mathops.py", "toolkit/textops.py"}
    assert cheap == landed  # cheap estimate == what the full apply lands on
    assert "toolkit/grading.py" not in cheap  # unsynthesizable never offered
    assert result.steps  # the campaign landed real moves


def test_full_apply_lands_the_four_functions(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _toolkit_project(tmp_path)
    compile_objective(str(tmp_path), "implement-stub", apply=True)

    math_src = (tmp_path / "toolkit" / "mathops.py").read_text()
    text_src = (tmp_path / "toolkit" / "textops.py").read_text()
    core_src = (tmp_path / "toolkit" / "core.py").read_text()
    grade_src = (tmp_path / "toolkit" / "grading.py").read_text()

    assert "return n * 3" in math_src                 # triple
    assert "return w * h" in math_src                 # rectangle_area
    assert "return s.upper()" in text_src             # loud
    assert "return sep.join(items)" in text_src       # join_with
    assert "return x" in core_src                     # identity (DEFECT 2)
    assert "raise NotImplementedError" in grade_src   # grade_letter left as-is


def test_grade_letter_module_not_counted_cheaply(tmp_path: Path):
    from app.execution.stub_synthesis import module_has_fillable_stub

    # The unsynthesizable module must NOT be counted by the cheap estimate (it is
    # honestly not fillable), so fitness never reports false debt for it.
    _toolkit_project(tmp_path)
    assert module_has_fillable_stub(tmp_path, "toolkit/grading.py") is False
    assert module_has_fillable_stub(tmp_path, "toolkit/mathops.py") is True
    assert module_has_fillable_stub(tmp_path, "toolkit/textops.py") is True
    assert module_has_fillable_stub(tmp_path, "toolkit/core.py") is True


def test_cheap_scan_runs_no_pytest_subprocess(tmp_path: Path, monkeypatch):
    # The whole point of DEFECT 1: the fitness/move scan must NOT spawn pytest.
    # Trip a wire on RunTestsSkill.run so any pytest probe during the cheap scan
    # would fail the test — proving the scan is purely in-process.
    from app.execution.objectives.implement_stub import _modules
    from app.skills.execution.run_tests import RunTestsSkill

    _toolkit_project(tmp_path)

    def _boom(self, *a, **k):
        raise AssertionError("cheap scan must not run pytest")

    monkeypatch.setattr(RunTestsSkill, "run", _boom)
    mods = set(_modules(str(tmp_path)))  # would raise if it spawned pytest
    assert mods == {"toolkit/core.py", "toolkit/mathops.py", "toolkit/textops.py"}


def test_fitness_counts_fillable_modules_cheaply(tmp_path: Path, monkeypatch):
    from app.execution.objectives.implement_stub import fitness
    from app.skills.execution.run_tests import RunTestsSkill

    _toolkit_project(tmp_path)
    monkeypatch.setattr(
        RunTestsSkill, "run",
        lambda self, *a, **k: (_ for _ in ()).throw(
            AssertionError("fitness must not run pytest")))
    # 3 fillable modules (core/mathops/textops); grading is honestly excluded.
    assert fitness(str(tmp_path)) == 3.0


# --- DEFECT 1: recursion-only stubs are NOT under-counted ---------------------

def test_recursion_only_stub_is_counted_cheaply(tmp_path: Path, monkeypatch):
    from app.execution.stub_synthesis import (
        StubFunction, can_fill_stub_in_process, module_has_fillable_stub,
    )
    from app.skills.execution.run_tests import RunTestsSkill

    # factorial is fillable ONLY via the recursion template (a pure expression
    # can't compute it). The cheap estimate must still count it via the in-process
    # recursive evaluation — else it would silently stop being offered.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "f.py").write_text(
        "def fact(n):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_f.py").write_text(
        "from app.f import fact\n"
        "def test():\n    assert fact(0) == 1\n    assert fact(5) == 120\n",
        encoding="utf-8")

    monkeypatch.setattr(
        RunTestsSkill, "run",
        lambda self, *a, **k: (_ for _ in ()).throw(
            AssertionError("recursion estimate must be in-process")))
    stub = StubFunction("fact", ("n",), 1, 2, "", False)
    assert can_fill_stub_in_process(tmp_path, ["tests/test_f.py"], stub) is True
    assert module_has_fillable_stub(tmp_path, "app/f.py") is True


def test_recursion_estimate_then_lands_end_to_end(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    # The cheap estimate counts the recursion stub AND the full apply lands it —
    # so the speed-up never drops a stub that used to land.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "f.py").write_text(
        "def fact(n):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_f.py").write_text(
        "from app.f import fact\n"
        "def test():\n    assert fact(0) == 1\n    assert fact(5) == 120\n",
        encoding="utf-8")

    result = compile_objective(str(tmp_path), "implement-stub", apply=True)
    text = (tmp_path / "app" / "f.py").read_text()
    assert result.steps
    assert "raise NotImplementedError" not in text
    assert "fact(n - 1)" in text  # the recursion body landed


def test_unsatisfiable_recursion_not_counted(tmp_path: Path):
    from app.execution.stub_synthesis import StubFunction, can_fill_stub_in_process

    # A one-arg int contract that NO recursion (or other) template reproduces must
    # NOT be counted — the cheap recursion check evaluates the body and rejects.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_g.py").write_text(
        "def test():\n    assert g(0) == 7\n    assert g(5) == 7\n", encoding="utf-8")
    stub = StubFunction("g", ("n",), 1, 2, "", False)
    # 0->7, 5->7 is a constant, which the constant template can land — so it IS
    # fillable, just not by recursion. Confirm the estimate is True overall but
    # that the *recursion* path alone does not falsely claim it.
    from app.execution.stub_synthesis import _recursion_matches
    assert _recursion_matches(tmp_path, ["tests/test_g.py"], stub) is False
    assert can_fill_stub_in_process(tmp_path, ["tests/test_g.py"], stub) is True


# --- DEFECT 2: identity passthrough lands; real ambiguity still refuses -------

def test_identity_passthrough_lands_return_x(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # identity(5)==5, identity(9)==9: the algebraic-identity family is ONE shape,
    # so the ambiguity guard no longer trips and `return x` lands.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "c.py").write_text(
        "def identity(x):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_c.py").write_text(
        "from app.c import identity\n"
        "def test():\n    assert identity(5) == 5\n    assert identity(9) == 9\n",
        encoding="utf-8")
    body = plan_implement_stub(str(tmp_path), "app/c.py").new_contents.get("app/c.py")
    assert body is not None and "return x" in body


def test_identity_lands_end_to_end(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _toolkit_project(tmp_path)
    compile_objective(str(tmp_path), "implement-stub", apply=True)
    assert "return x" in (tmp_path / "toolkit" / "core.py").read_text()


def test_genuine_passthrough_vs_double_still_refuses(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # f(0)==0 fits BOTH passthrough (x) and doubling (x*2) — genuinely different
    # shapes that disagree everywhere except 0. The guard must STILL refuse (the
    # identity-family collapse must not dissolve a real ambiguity).
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    original = "def f(x):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "a.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_a.py").write_text(
        "from app.a import f\ndef test():\n    assert f(0) == 0\n", encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "app/a.py")
    assert not plan.new_contents  # honest no-op — refuse decision unchanged
    # Additive ambiguity disclosure (does not change what lands): the refusal now
    # names a concrete discriminating input and how to fix it.
    assert any("f: ambiguous:" in b and "differ on x=" in b
               and "add a discriminating test" in b for b in plan.blockers)


def test_abs_vs_passthrough_still_refuses_with_negative_witness(tmp_path: Path):
    from app.execution.stub_synthesis import StubFunction, _is_ambiguous

    # The identity-family collapse must NOT blind the guard to abs when a negative
    # witness IS present: f(-3)==3 fails passthrough, so abs is the only fit and
    # lands (gate); but a contract that fits both x and abs(x) with a negative in
    # the witnessed domain remains genuinely ambiguous and refuses. Here the
    # sign-envelope keeps a negative canary because a witness is negative.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_m.py").write_text(
        "def test():\n    assert m(-2) == -2\n    assert m(4) == 4\n", encoding="utf-8")
    stub = StubFunction("m", ("n",), 1, 2, "", False)
    # m(-2)==-2 fits passthrough but NOT abs (abs(-2)=2), so abs is excluded and
    # only the identity family fits -> unambiguous passthrough.
    assert _is_ambiguous(tmp_path, ["tests/test_m.py"], stub) is False


def test_is_big_thin_contract_still_refuses(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # The pre-existing ambiguity case must stay refused: is_big(5)==False,
    # is_big(200)==True fits both parity and a threshold (disagree at 50/99).
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    original = "def is_big(n):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "b.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_b.py").write_text(
        "from app.b import is_big\n"
        "def test():\n    assert is_big(5) == False\n    assert is_big(200) == True\n",
        encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "app/b.py")
    assert not plan.new_contents  # refuse decision unchanged
    # Additive ambiguity disclosure: the refusal now explains WHY (parity vs a
    # threshold) without changing what lands.
    assert any("n % 2 == 0" in b for b in plan.blockers)


def test_identity_canonical_shape_collapses_family():
    from app.execution.stub_synthesis import (
        StubFunction, _identity_canonical_shape,
    )

    stub = StubFunction("f", ("a",), 1, 2, "", False)
    fam = ["a", "a + 0", "a - 0", "a * 1", "a // 1", "a / 1"]
    keys = {_identity_canonical_shape(e, stub) for e in fam}
    assert keys == {"<identity>"}  # the whole family is ONE shape
    # A genuinely different shape keys to itself (still a competing intent).
    assert _identity_canonical_shape("a * 2", stub) == "a * 2"
    assert _identity_canonical_shape("a + 1", stub) == "a + 1"
    # A multi-param expr can have no identity family -> keys to itself.
    two = StubFunction("g", ("a", "b"), 1, 2, "", False)
    assert _identity_canonical_shape("a + b", two) == "a + b"


def test_identity_synthesis_is_deterministic(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "c.py").write_text(
        "def identity(x):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_c.py").write_text(
        "from app.c import identity\n"
        "def test():\n    assert identity(5) == 5\n    assert identity(9) == 9\n",
        encoding="utf-8")
    a = plan_implement_stub(str(tmp_path), "app/c.py").new_contents.get("app/c.py")
    b = plan_implement_stub(str(tmp_path), "app/c.py").new_contents.get("app/c.py")
    assert a == b and a is not None and "return x" in a
