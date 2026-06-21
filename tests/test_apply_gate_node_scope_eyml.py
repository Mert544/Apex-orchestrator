"""Apply-gate NODE-ID scoping — the OUTER gate honours the planner's per-symbol
node IDs, so a same-file unsynthesizable sibling no longer rolls a landable fill
back END-TO-END.

The remaining gap after the planner-level node-ID fix (commit 64623885): the
PLANNER stopped letting one unsynthesizable sibling veto its synthesizable
siblings, but the OUTER apply gate still scoped by whole test FILE. When
``compile_objective`` applied a ``plan_implement_stub`` plan via
``apply_rename(..., impact_scope=True)``, ``_verify_scoped`` ran the whole
impacted test FILE (``tests/test_mathutils.py``) — which still contains
``test_running_total`` (the unsynthesizable sibling, red) — so the scoped run
FAILED and the correct ``add``/``scale`` fill was ROLLED BACK.

The fix: the plan carries the pre-existing-red sibling nodes
(``scoped_excluded_nodes``) and the apply gate DESELECTS exactly those from the
whole impacted files. ``add``/``scale``'s real nodes still run and pass;
``::test_running_total`` (red before, not worsened by the fill) is deselected and
no longer vetoes. A test that the change would REGRESS from green still runs
(it's not deselected), so never-fake-green holds. The full suite stays the
commit-time backstop.

These tests prove the gate mechanics directly:
  - ``RenamePlan`` carries the new fields (default empty → behavior unchanged);
  - the implement-stub plan populates the LANDED nodes and DESELECTS the
    unsynthesizable sibling's node — never a landed stub's node;
  - the scoped command (``--deselect file::test_running_total``) is exactly what
    ``_verify_scoped`` runs, and an empty-exclusion plan's command is
    byte-identical to the established whole-file shape (no regression for any
    other objective);
  - determinism: same fixture → identical scoped_test_nodes and excluded nodes.
"""

from __future__ import annotations

from pathlib import Path


# --- fixture: three siblings in one shared test file -------------------------

def _mathutils_project(root: Path) -> None:
    """``app/mathutils.py`` with ``add`` (-> ``a + b``), ``scale``
    (-> ``value * factor``) — both synthesizable — and ``running_total``
    (genuinely unsynthesizable), all pinned in ONE ``tests/test_mathutils.py``."""
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
        "    assert running_total(0) == 2\n"
        "    assert running_total(1) == 2\n"
        "    assert running_total(2) == 9\n",
        encoding="utf-8")


# --- the RenamePlan carries the new fields (default empty) -------------------

def test_renameplan_scope_fields_default_empty():
    from app.execution.cross_file_rename import RenamePlan

    plan = RenamePlan(old="x", new="y")
    assert plan.scoped_test_nodes == []
    assert plan.scoped_excluded_nodes == []


# --- the implement-stub plan populates the gate scope ------------------------

def test_plan_populates_landed_nodes_and_excludes_sibling(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _mathutils_project(tmp_path)
    plan = plan_implement_stub(str(tmp_path), "app/mathutils.py")
    assert plan.new_contents  # add/scale land

    # The LANDED stubs' OWN nodes are named (transparency + honesty).
    assert plan.scoped_test_nodes == [
        "tests/test_mathutils.py::test_add",
        "tests/test_mathutils.py::test_scale",
    ]
    # The unsynthesizable sibling's node is DESELECTED — and never a landed node.
    assert plan.scoped_excluded_nodes == [
        "tests/test_mathutils.py::test_running_total",
    ]
    assert not (set(plan.scoped_test_nodes) & set(plan.scoped_excluded_nodes))


# --- the scoped command deselects exactly the sibling node -------------------

def test_verify_scoped_deselects_sibling_node(tmp_path: Path, monkeypatch):
    import app.execution.cross_file_rename as cfr
    from app.execution.objectives.implement_stub import plan_implement_stub

    _mathutils_project(tmp_path)
    plan = plan_implement_stub(str(tmp_path), "app/mathutils.py")
    # Apply the fill so the impacted file is the one we expect to gate.
    (tmp_path / "app" / "mathutils.py").write_text(
        plan.new_contents["app/mathutils.py"], encoding="utf-8")

    seen: list[list[str]] = []

    import subprocess as _sp
    real_run = _sp.run

    def _spy(cmd, **kw):
        seen.append(list(cmd))
        return real_run(cmd, **kw)

    monkeypatch.setattr("subprocess.run", _spy)
    out = cfr._verify_scoped(tmp_path, plan)
    assert out is not None
    ok, evidence = out
    assert ok is True  # add/scale pass once the red sibling is deselected

    cmd = seen[0]
    # The whole impacted FILE still runs (so a green->red regression is caught)...
    assert "tests/test_mathutils.py" in cmd
    # ...but the pre-existing-red sibling node is deselected, never a landed node.
    di = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--deselect"]
    assert di == ["tests/test_mathutils.py::test_running_total"]
    assert "tests/test_mathutils.py::test_add" not in di
    assert evidence["deselected"] == [
        "tests/test_mathutils.py::test_running_total"]


# --- empty exclusion -> byte-identical whole-file command (no regression) ----

def test_empty_exclusion_command_is_byte_identical_to_whole_file(
        tmp_path: Path, monkeypatch):
    # A plan with NO excluded nodes (every other objective, and the no-sibling
    # case) must produce EXACTLY the established whole-file scoped command — no
    # `--deselect` token at all — so nothing that used to land stops landing.
    import sys

    import app.execution.cross_file_rename as cfr
    from app.execution.cross_file_rename import RenamePlan

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "mod.py").write_text(
        "def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_mod.py").write_text(
        "from app.mod import f\ndef test_f():\n    assert f() == 1\n",
        encoding="utf-8")

    plan = RenamePlan(old="app/mod.py", new="x")
    plan.originals["app/mod.py"] = "def f():\n    return 1\n"
    plan.new_contents["app/mod.py"] = "def f():\n    return 1  # tidy\n"
    assert plan.scoped_test_nodes == [] and plan.scoped_excluded_nodes == []

    seen: list[list[str]] = []
    import subprocess as _sp
    real_run = _sp.run

    def _spy(cmd, **kw):
        seen.append(list(cmd))
        return real_run(cmd, **kw)

    monkeypatch.setattr("subprocess.run", _spy)
    cfr._verify_scoped(tmp_path, plan)

    cmd = seen[0]
    assert "--deselect" not in cmd  # no deselection when nothing is excluded
    # The exact established shape: pytest -q -x -p no:cacheprovider <impacted file>.
    assert cmd == [
        sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
        "tests/test_mod.py"]


# --- determinism -------------------------------------------------------------

def test_scope_fields_are_deterministic(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _mathutils_project(tmp_path)
    first = plan_implement_stub(str(tmp_path), "app/mathutils.py")

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root2 = Path(d)
        _mathutils_project(root2)
        second = plan_implement_stub(str(root2), "app/mathutils.py")

    assert first.scoped_test_nodes == second.scoped_test_nodes
    assert first.scoped_excluded_nodes == second.scoped_excluded_nodes
