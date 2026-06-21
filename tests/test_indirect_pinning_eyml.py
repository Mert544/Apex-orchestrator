"""FIX 2 — indirect test-pinning no longer defeats the node-gate -> whole-file
fallback -> sibling-veto deadlock, and indirect witnesses are actually mined.

The field-test failure: when a stub is pinned INDIRECTLY — via a
``@pytest.mark.parametrize`` test, or a module-local helper that calls the
function — node-ID discovery found no node, the gate fell back to the whole FILE,
and an unsynthesizable sibling in that same file RE-VETOED the landable stub (the
exact deadlock the node-gate was meant to fix). Worse, witnesses couldn't be
mined from the indirect form, so the stub wasn't even synthesizable.

The fix scopes to the two highest-value, cleanest cases — parametrize and a
one-level module-local helper:

* NODE DISCOVERY (``_test_nodes_referencing``) additionally counts a ``test_*``
  whose body calls a module-local helper that references the symbol (the
  parametrize body already names the symbol, so it was already counted).
* WITNESS MINING (``_function_witnesses``) ALSO recovers literal witnesses from
  parametrize ROWS bound to the test's params, and from a one-level helper called
  with literals resolved through the helper's params.

HONESTY: this only ADDS the ability to find tests/witnesses that were always
there. The synthesis accept-gate is unchanged (a body must still pass all
witnesses), the ambiguity guard still applies, and only LITERAL arguments are
resolved (a non-literal indirect case is skipped — never guessed). Deterministic,
AST-based, one level of indirection only.
"""

from __future__ import annotations

from pathlib import Path


# --- fixture: parametrize + helper + an unsynthesizable sibling --------------

def _indirect_project(root: Path) -> None:
    """``scale`` pinned via ``@parametrize([(2, 6), (5, 15)])``, ``add`` pinned via
    a one-level module-local helper ``_check_add(2, 3, 5)`` / ``_check_add(10, 1,
    11)``, and an unsynthesizable ``running_total`` — ALL in the SAME shared test
    file. ``scale -> n * 3`` and ``add -> a + b`` must BOTH land (node-gate finds
    ``::test_scale_param`` / ``::test_add_indirect``, witnesses mined from the
    parametrize rows / helper literals), while ``running_total`` stays a stub."""
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    (root / "app" / "mathutils.py").write_text(
        "def scale(n):\n    raise NotImplementedError\n\n\n"
        "def add(a, b):\n    raise NotImplementedError\n\n\n"
        "def running_total(n):\n    raise NotImplementedError\n",
        encoding="utf-8")
    (root / "tests" / "test_mathutils.py").write_text(
        "import pytest\n\n"
        "from app.mathutils import scale, add, running_total\n\n\n"
        '@pytest.mark.parametrize("n,expected", [(2, 6), (5, 15)])\n'
        "def test_scale_param(n, expected):\n"
        "    assert scale(n) == expected\n\n\n"
        "def _check_add(a, b, expected):\n"
        "    assert add(a, b) == expected\n\n\n"
        "def test_add_indirect():\n"
        "    _check_add(2, 3, 5)\n    _check_add(10, 1, 11)\n\n\n"
        "def test_running_total():\n"
        # No fixed template / constant reproduces 0->2, 1->2, 2->9.
        "    assert running_total(0) == 2\n"
        "    assert running_total(1) == 2\n"
        "    assert running_total(2) == 9\n",
        encoding="utf-8")


def _node_passes(root: Path, node_id: str) -> bool:
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", node_id],
        cwd=str(root), capture_output=True, text=True)
    return proc.returncode == 0


# --- node discovery: indirect forms resolve to their OWN node IDs -------------

def test_parametrize_node_is_discovered(tmp_path: Path):
    from app.execution.stub_synthesis import pinned_test_nodes

    _indirect_project(tmp_path)
    assert pinned_test_nodes(tmp_path, "app/mathutils.py", "scale") == [
        "tests/test_mathutils.py::test_scale_param"]


def test_helper_indirect_node_is_discovered(tmp_path: Path):
    from app.execution.stub_synthesis import pinned_test_nodes

    _indirect_project(tmp_path)
    # WAS the whole file (`add` not named in `test_add_indirect`'s body) — the
    # sibling-veto deadlock. Now the one-level helper resolves the real node.
    assert pinned_test_nodes(tmp_path, "app/mathutils.py", "add") == [
        "tests/test_mathutils.py::test_add_indirect"]
    assert "::" in pinned_test_nodes(tmp_path, "app/mathutils.py", "add")[0]


# --- witness mining: indirect forms yield LITERAL witnesses ------------------

def test_parametrize_witnesses_are_literal(tmp_path: Path):
    from app.execution.stub_synthesis import _function_witnesses, find_stub_functions

    _indirect_project(tmp_path)
    src = (tmp_path / "app" / "mathutils.py").read_text(encoding="utf-8")
    scale = next(s for s in find_stub_functions(src) if s.name == "scale")
    # The parametrize rows are bound to the params and substituted into the assert.
    assert _function_witnesses(tmp_path, ["tests/test_mathutils.py"], scale) == [
        ("2", "6"), ("5", "15")]


def test_helper_witnesses_are_literal(tmp_path: Path):
    from app.execution.stub_synthesis import _function_witnesses, find_stub_functions

    _indirect_project(tmp_path)
    src = (tmp_path / "app" / "mathutils.py").read_text(encoding="utf-8")
    add = next(s for s in find_stub_functions(src) if s.name == "add")
    # The helper's literal call args are resolved through its params.
    assert _function_witnesses(tmp_path, ["tests/test_mathutils.py"], add) == [
        ("2, 3", "5"), ("10, 1", "11")]


def test_indirect_witnesses_synthesize(tmp_path: Path):
    from app.execution.stub_synthesis import (
        find_stub_functions, synthesize_expr_from_witnesses)

    _indirect_project(tmp_path)
    src = (tmp_path / "app" / "mathutils.py").read_text(encoding="utf-8")
    stubs = {s.name: s for s in find_stub_functions(src)}
    tests = ["tests/test_mathutils.py"]
    assert synthesize_expr_from_witnesses(tmp_path, tests, stubs["scale"]) == "n * 3"
    assert synthesize_expr_from_witnesses(tmp_path, tests, stubs["add"]) == "a + b"
    # The unsynthesizable sibling stays None — never a false witness.
    assert synthesize_expr_from_witnesses(
        tmp_path, tests, stubs["running_total"]) is None


# --- the headline fix: scale AND add land, running_total stays a stub --------

def test_scale_and_add_both_land_despite_unsynthesizable_sibling(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _indirect_project(tmp_path)
    plan = plan_implement_stub(str(tmp_path), "app/mathutils.py")
    filled = plan.new_contents.get("app/mathutils.py")
    assert filled is not None
    assert "return n * 3" in filled   # parametrize-pinned stub lands
    assert "return a + b" in filled   # helper-pinned stub lands
    # running_total's stub is untouched (its red node is not in the landed gate).
    assert filled.count("raise NotImplementedError") == 1
    rt_def = filled.split("def running_total(n):", 1)[1]
    assert "raise NotImplementedError" in rt_def


def test_landed_indirect_stubs_pass_their_own_real_tests(tmp_path: Path):
    # Honesty: the node-gated plan fills scale/add with bodies whose OWN real
    # pinned (indirect) tests genuinely pass on disk, while the unsynthesizable
    # sibling's test stays RED (never faked green).
    from app.execution.objectives.implement_stub import plan_implement_stub

    _indirect_project(tmp_path)
    filled = plan_implement_stub(str(tmp_path), "app/mathutils.py").new_contents.get(
        "app/mathutils.py")
    assert filled is not None
    (tmp_path / "app" / "mathutils.py").write_text(filled, encoding="utf-8")

    assert _node_passes(tmp_path, "tests/test_mathutils.py::test_scale_param")
    assert _node_passes(tmp_path, "tests/test_mathutils.py::test_add_indirect")
    assert not _node_passes(tmp_path, "tests/test_mathutils.py::test_running_total")


# --- a non-literal indirect case is SKIPPED (no false witness) ---------------

def _non_literal_indirect_project(root: Path) -> None:
    """An indirect contract whose call arguments are NOT literals — a parametrize
    row and a helper call both built from a module-level name (``BASE``). Neither
    can be resolved to a literal witness, so the witness miner must skip them (no
    guess).

    ``scale``'s real intent (``scale(2) == 6`` -> ``n * 3``) can ONLY be reached
    from a WITNESS-DERIVED constant; with no literal witness, no ``k = 3`` is
    proposed and ``scale`` lands NOTHING — proving the no-false-witness invariant
    actually withholds a body, not just a witness. (``add``'s ``a + b`` is a
    value-FREE template that the runtime pytest gate can still land legitimately,
    so it is not asserted here — never-fake-green governs that path.)"""
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='n'\nversion='0'\n", encoding="utf-8")
    (root / "app" / "ndl.py").write_text(
        "def scale(n):\n    raise NotImplementedError\n\n\n"
        "def add(a, b):\n    raise NotImplementedError\n",
        encoding="utf-8")
    (root / "tests" / "test_ndl.py").write_text(
        "import pytest\n\n"
        "from app.ndl import scale, add\n\n\n"
        "BASE = 2\n\n\n"
        # parametrize row argument is a non-literal NAME (BASE) — unresolvable.
        '@pytest.mark.parametrize("n,expected", [(BASE, 6)])\n'
        "def test_scale_param(n, expected):\n"
        "    assert scale(n) == expected\n\n\n"
        "def _check_add(a, b, expected):\n"
        "    assert add(a, b) == expected\n\n\n"
        "def test_add_indirect():\n"
        # helper called with a non-literal first argument — unresolvable.
        "    _check_add(BASE, 3, 5)\n",
        encoding="utf-8")


def test_non_literal_indirect_yields_no_witness(tmp_path: Path):
    from app.execution.stub_synthesis import (
        _function_witnesses, find_stub_functions, synthesize_expr_from_witnesses)

    _non_literal_indirect_project(tmp_path)
    src = (tmp_path / "app" / "ndl.py").read_text(encoding="utf-8")
    stubs = {s.name: s for s in find_stub_functions(src)}
    tests = ["tests/test_ndl.py"]
    for name in ("scale", "add"):
        # No LITERAL witness is recovered from a non-literal row / helper call, so
        # in-process synthesis refuses (never a false witness — never-fake-green).
        assert not _has_literal_witness(_function_witnesses(tmp_path, tests, stubs[name]))
        assert synthesize_expr_from_witnesses(tmp_path, tests, stubs[name]) is None


def test_non_literal_indirect_withholds_witness_derived_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _non_literal_indirect_project(tmp_path)
    filled = plan_implement_stub(str(tmp_path), "app/ndl.py").new_contents.get(
        "app/ndl.py")
    # `scale`'s n*3 needs a witness-derived constant; with no literal witness it is
    # never proposed, so `scale` stays a stub — the no-false-witness invariant
    # withholds a real body, not merely a witness.
    scale_def = (filled or
                 (tmp_path / "app" / "ndl.py").read_text(encoding="utf-8")
                 ).split("def scale(n):", 1)[1].split("def add", 1)[0]
    assert "raise NotImplementedError" in scale_def
    assert "n * 3" not in (filled or "")


def _has_literal_witness(witnesses) -> bool:
    """True when any ``(args, expected)`` pair is fully literal (both sides parse
    via ``ast.literal_eval``)."""
    import ast
    for args, expected in witnesses:
        try:
            ast.literal_eval(f"({args},)")
            ast.literal_eval(expected)
            return True
        except (ValueError, SyntaxError, TypeError):
            continue
    return False


# --- determinism -------------------------------------------------------------

def test_indirect_landing_is_deterministic(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub
    import tempfile

    _indirect_project(tmp_path)
    first = plan_implement_stub(str(tmp_path), "app/mathutils.py").new_contents.get(
        "app/mathutils.py")
    with tempfile.TemporaryDirectory() as d:
        root2 = Path(d)
        _indirect_project(root2)
        second = plan_implement_stub(str(root2), "app/mathutils.py").new_contents.get(
            "app/mathutils.py")
    assert first == second and first is not None


def test_indirect_witness_mining_is_deterministic(tmp_path: Path):
    from app.execution.stub_synthesis import _function_witnesses, find_stub_functions

    _indirect_project(tmp_path)
    src = (tmp_path / "app" / "mathutils.py").read_text(encoding="utf-8")
    add = next(s for s in find_stub_functions(src) if s.name == "add")
    tests = ["tests/test_mathutils.py"]
    assert _function_witnesses(tmp_path, tests, add) == \
        _function_witnesses(tmp_path, tests, add)


# --- direct pinning stays byte-identical (no regression) ---------------------

def _direct_project(root: Path) -> None:
    """The same ``scale``/``add`` contract pinned DIRECTLY (no parametrize, no
    helper) — its witnesses and node IDs must be byte-identical to the pre-fix
    behavior."""
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    (root / "app" / "mathutils.py").write_text(
        "def scale(n):\n    raise NotImplementedError\n\n\n"
        "def add(a, b):\n    raise NotImplementedError\n",
        encoding="utf-8")
    (root / "tests" / "test_mathutils.py").write_text(
        "from app.mathutils import scale, add\n\n\n"
        "def test_scale():\n    assert scale(2) == 6\n    assert scale(5) == 15\n\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n",
        encoding="utf-8")


def test_direct_pinning_witnesses_unchanged(tmp_path: Path):
    from app.execution.stub_synthesis import _function_witnesses, find_stub_functions

    _direct_project(tmp_path)
    src = (tmp_path / "app" / "mathutils.py").read_text(encoding="utf-8")
    stubs = {s.name: s for s in find_stub_functions(src)}
    tests = ["tests/test_mathutils.py"]
    # Exactly the direct regex output — no indirect miner fires here.
    assert _function_witnesses(tmp_path, tests, stubs["scale"]) == [("2", "6"), ("5", "15")]
    assert _function_witnesses(tmp_path, tests, stubs["add"]) == [("2, 3", "5"), ("10, 1", "11")]


def test_direct_pinning_nodes_unchanged(tmp_path: Path):
    from app.execution.stub_synthesis import pinned_test_nodes

    _direct_project(tmp_path)
    assert pinned_test_nodes(tmp_path, "app/mathutils.py", "scale") == [
        "tests/test_mathutils.py::test_scale"]
    assert pinned_test_nodes(tmp_path, "app/mathutils.py", "add") == [
        "tests/test_mathutils.py::test_add"]
