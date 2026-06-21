"""Blocker 2 — per-symbol NODE-ID gating so one unsynthesizable sibling stub no
longer vetoes its landable siblings.

The field-test failure: a module ``mathutils.py`` with ``add`` (-> ``a + b``),
``scale`` (-> ``value * factor``), and ``running_total`` (genuinely
unsynthesizable) — ALL pinned in ONE shared test file ``tests/test_mathutils.py``
— landed NOTHING. ``add``/``scale`` are trivially synthesizable but were refused
together: the gate ran ``pytest -q tests/test_mathutils.py`` (the whole FILE),
which also re-runs ``test_running_total`` for the unsynthesizable stub, so the
union run stayed RED and the landable siblings were rolled back.

The fix gates each stub against the specific pinned-test NODE IDs that name it
(``tests/test_mathutils.py::test_add``, ``::test_scale``) rather than the whole
file. A stub whose own node IDs pass lands even if a sibling's node IDs (for the
unsynthesizable stub) stay red — the unsynthesizable sibling's tests are simply
not in the landed stubs' gate (they were never going to pass; pre-existing, not
caused by the fill). Each landed stub is still gated against its OWN real tests,
so never-fake-green holds. Node-ID discovery is deterministic (AST-based,
stdlib-only, sorted).
"""

from __future__ import annotations

from pathlib import Path


# --- fixture: three siblings in one shared test file -------------------------

def _mathutils_project(root: Path) -> None:
    """A package with THREE stubs in ONE module, all pinned by ONE shared test
    file. ``add`` (-> ``a + b``) and ``scale`` (-> ``value * factor``) are
    trivially synthesizable; ``running_total`` is genuinely unsynthesizable (its
    witnesses fit no fixed template / constant), so its test stays RED."""
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    (root / "app" / "mathutils.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n\n\n"
        "def scale(value, factor):\n    raise NotImplementedError\n\n\n"
        "def running_total(n):\n    raise NotImplementedError\n",
        encoding="utf-8")
    (root / "tests" / "test_mathutils.py").write_text(
        "from app.mathutils import add, scale, running_total\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n\n"
        "def test_scale():\n"
        "    assert scale(2, 3) == 6\n    assert scale(4, 5) == 20\n\n"
        "def test_running_total():\n"
        # No fixed template reproduces these: 0->2, 1->2, 2->9 fit no n OP k shape,
        # no constant (they disagree), no parity/comparison/recursion.
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


# --- node-ID discovery: deterministic, AST-based, per symbol -----------------

def test_pinned_test_nodes_discovers_per_symbol_node_ids(tmp_path: Path):
    from app.execution.stub_synthesis import pinned_test_nodes

    _mathutils_project(tmp_path)
    add_nodes = pinned_test_nodes(tmp_path, "app/mathutils.py", "add")
    scale_nodes = pinned_test_nodes(tmp_path, "app/mathutils.py", "scale")
    rt_nodes = pinned_test_nodes(tmp_path, "app/mathutils.py", "running_total")

    # Each symbol resolves to its OWN test function's node ID — NOT the whole file.
    assert add_nodes == ["tests/test_mathutils.py::test_add"]
    assert scale_nodes == ["tests/test_mathutils.py::test_scale"]
    assert rt_nodes == ["tests/test_mathutils.py::test_running_total"]
    # The gate is at NODE granularity (file::test), not a bare file path.
    assert all("::" in n for n in add_nodes + scale_nodes + rt_nodes)


def test_node_discovery_is_deterministic(tmp_path: Path):
    from app.execution.stub_synthesis import pinned_test_nodes

    _mathutils_project(tmp_path)
    first = pinned_test_nodes(tmp_path, "app/mathutils.py", "add")
    second = pinned_test_nodes(tmp_path, "app/mathutils.py", "add")
    assert first == second  # AST-based, sorted — same fixture, same result


# --- the headline fix: add AND scale land, running_total stays a stub --------

def test_add_and_scale_both_land_despite_unsynthesizable_sibling(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _mathutils_project(tmp_path)
    plan = plan_implement_stub(str(tmp_path), "app/mathutils.py")
    filled = plan.new_contents.get("app/mathutils.py")
    assert filled is not None  # something lands — the sibling no longer vetoes all

    # add and scale END with their REAL bodies; running_total stays a stub.
    assert "return a + b" in filled
    assert "return value * factor" in filled
    # running_total's stub is untouched (its own node is not in the landed gate).
    assert filled.count("raise NotImplementedError") == 1
    rt_def = filled.split("def running_total(n):", 1)[1]
    assert "raise NotImplementedError" in rt_def


def test_landed_stubs_pass_their_own_real_tests_red_sibling_stays_red(tmp_path: Path):
    # Honesty: the node-gated PLAN fills add/scale with bodies whose OWN real
    # pinned tests genuinely pass on disk, while the unsynthesizable sibling's
    # test stays RED (never faked green). We write the planned content and check
    # each node directly — proving the gate is grounded in real, passing tests.
    from app.execution.objectives.implement_stub import plan_implement_stub

    _mathutils_project(tmp_path)
    filled = plan_implement_stub(str(tmp_path), "app/mathutils.py").new_contents.get(
        "app/mathutils.py")
    assert filled is not None
    (tmp_path / "app" / "mathutils.py").write_text(filled, encoding="utf-8")

    assert "return a + b" in filled and "return value * factor" in filled
    assert "raise NotImplementedError" in filled  # running_total still a stub

    # add/scale's OWN nodes pass; running_total's node stays red (never faked).
    assert _node_passes(tmp_path, "tests/test_mathutils.py::test_add")
    assert _node_passes(tmp_path, "tests/test_mathutils.py::test_scale")
    assert not _node_passes(tmp_path, "tests/test_mathutils.py::test_running_total")


# --- the gate actually uses node IDs, not the whole file ---------------------

def test_union_gate_runs_node_ids_not_whole_file(tmp_path: Path, monkeypatch):
    # Assert directly that the union gate is invoked with file::test node IDs for
    # the landed stubs only — NOT the bare shared file path (which would re-run
    # the unsynthesizable sibling's red node and roll everything back).
    import app.execution.objectives.implement_stub as mod

    _mathutils_project(tmp_path)
    seen: list[list[str]] = []
    real = mod._union_passes

    def _spy(root, module_rel, candidate, test_files, runner):
        seen.append(list(test_files))
        return real(root, module_rel, candidate, test_files, runner)

    monkeypatch.setattr(mod, "_union_passes", _spy)
    mod.plan_implement_stub(str(tmp_path), "app/mathutils.py")

    assert seen, "the union gate was exercised"
    union = seen[0]
    # Node IDs for the LANDED stubs, never the bare file path.
    assert "tests/test_mathutils.py::test_add" in union
    assert "tests/test_mathutils.py::test_scale" in union
    assert "tests/test_mathutils.py" not in union  # not the whole file
    # The unsynthesizable sibling's red node is NOT in the gate.
    assert "tests/test_mathutils.py::test_running_total" not in union


# --- determinism: same fixture -> same landed result twice -------------------

def test_landing_is_deterministic(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _mathutils_project(tmp_path)
    first = plan_implement_stub(str(tmp_path), "app/mathutils.py").new_contents.get(
        "app/mathutils.py")

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root2 = Path(d)
        _mathutils_project(root2)
        second = plan_implement_stub(str(root2), "app/mathutils.py").new_contents.get(
            "app/mathutils.py")

    assert first == second and first is not None  # byte-identical, no clock/random


# --- fallback: a symbol whose test doesn't name it discoverably --------------

def _indirect_project(root: Path) -> None:
    """A stub whose pinned test references the symbol only via a module-qualified
    call (``m.twice(...)``), so the bare-name AST reference still finds it, but we
    also include a test whose function name does not start with ``test`` to prove
    the fallback path (no discoverable node -> whole-file gate) still lands it."""
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='i'\nversion='0'\n", encoding="utf-8")
    (root / "app" / "ind.py").write_text(
        "def twice(n):\n    raise NotImplementedError\n", encoding="utf-8")
    # The assertions live in a helper that does NOT start with `test`, invoked by a
    # parametrized-style runner — the symbol name appears only inside the helper,
    # so no `def test_*` references it directly. Node discovery finds nothing for
    # `twice` and falls back to whole-file gating, which still lands it.
    (root / "tests" / "test_ind.py").write_text(
        "from app.ind import twice\n\n"
        "def check_twice(x, y):\n    assert twice(x) == y\n\n"
        "def test_run():\n    check_twice(3, 6)\n    check_twice(5, 10)\n",
        encoding="utf-8")


def test_fallback_to_whole_file_when_no_node_names_symbol(tmp_path: Path):
    from app.execution.stub_synthesis import pinned_test_nodes

    _indirect_project(tmp_path)
    nodes = pinned_test_nodes(tmp_path, "app/ind.py", "twice")
    # No `def test_*` references `twice` directly (it's named only in `check_twice`
    # and via the import line), so discovery falls back to the whole file path.
    assert nodes == ["tests/test_ind.py"]


def test_fallback_case_still_lands(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _indirect_project(tmp_path)
    filled = plan_implement_stub(str(tmp_path), "app/ind.py").new_contents.get(
        "app/ind.py")
    # Whole-file fallback still gates and lands the genuine body.
    assert filled is not None and "return n * 2" in filled
