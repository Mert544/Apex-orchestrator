"""FIX 1 — a ``src/`` layout (and pyproject-declared source roots) no longer
silently defeats stub-synthesis AND impact-scoping.

The field-test failure: a standard ``src/``-layout project — ``pyproject.toml``
with ``[tool.pytest.ini_options] pythonpath=["src"]``, source at
``src/mylib/calc.py``, a test that does ``from mylib.calc import add`` — landed
NOTHING for implement-stub, and impact-scoping was blind::

    pinned_test_files('src/mylib/calc.py', 'add')  -> []   # should find the test
    covering_test_files('src/mylib/calc.py')        -> []   # impact scope blind

Root cause: both ``stub_synthesis.pinned_test_files`` and
``mutation_tester._module_dotted_path`` (used by ``covering_test_files``) derived
the importable dotted path by a naive path-join: ``src/mylib/calc.py`` ->
``src.mylib.calc``. But the test imports ``mylib.calc`` (pytest ``pythonpath=src``
/ an installed package strips the ``src`` root), so the import-linkage match
failed entirely. ``src/`` is one of the most common real Python layouts, so this
is a whole class of buyer projects where Apex did nothing.

The fix ALSO considers the source-root-stripped dotted path: a leading ``src/``
segment is always strippable, and pyproject roots
(``[tool.pytest.ini_options] pythonpath``, ``[tool.setuptools] package-dir`` /
``[tool.setuptools.packages.find] where``) are honored too. The raw path stays
in the candidate set, so a non-src project is byte-identical to before.
Deterministic, stdlib-only.
"""

from __future__ import annotations

from pathlib import Path


# --- fixtures ----------------------------------------------------------------

def _src_layout_project(root: Path) -> None:
    """A standard ``src/``-layout project: ``pyproject.toml`` declares
    ``pythonpath=["src"]`` (so pytest imports the package without the ``src``
    prefix), source lives at ``src/mylib/calc.py`` with one stub ``add``, and the
    test imports it as ``from mylib.calc import add``."""
    (root / "src" / "mylib").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "mylib" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'mylib'\nversion = '0'\n\n"
        "[tool.pytest.ini_options]\npythonpath = ['src']\n",
        encoding="utf-8")
    (root / "src" / "mylib" / "calc.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(
        "from mylib.calc import add\n\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n",
        encoding="utf-8")


def _custom_root_project(root: Path) -> None:
    """A pyproject-declared CUSTOM root (``lib`` rather than ``src``): the package
    lives under ``lib/`` and pytest imports it via ``pythonpath=["lib"]``."""
    (root / "lib" / "mylib").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "lib" / "mylib" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'mylib'\nversion = '0'\n\n"
        "[tool.pytest.ini_options]\npythonpath = ['lib']\n",
        encoding="utf-8")
    (root / "lib" / "mylib" / "calc.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(
        "from mylib.calc import add\n\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n",
        encoding="utf-8")


def _package_dir_project(root: Path) -> None:
    """A setuptools ``package-dir = {"" = "lib"}`` declaration — exercises the
    setuptools branch of the source-root parser at the LINKAGE level (no pytest
    pythonpath, so we only assert discovery, not a runtime landing)."""
    (root / "lib" / "mylib").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "lib" / "mylib" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'mylib'\nversion = '0'\n\n"
        '[tool.setuptools]\npackage-dir = {"" = "lib"}\n',
        encoding="utf-8")
    (root / "lib" / "mylib" / "calc.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(
        "from mylib.calc import add\n\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8")


def _non_src_project(root: Path) -> None:
    """The identical contract WITHOUT a ``src/`` root — a flat ``app/`` package.
    Linkage and landing here must be byte-identical to the pre-fix behavior."""
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'app'\nversion = '0'\n", encoding="utf-8")
    (root / "app" / "calc.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(
        "from app.calc import add\n\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n",
        encoding="utf-8")


# --- linkage primitives: src/ layout now discovered --------------------------

def test_pinned_test_files_finds_src_layout(tmp_path: Path):
    from app.execution.stub_synthesis import pinned_test_files

    _src_layout_project(tmp_path)
    # Was [] before the fix (it derived ``src.mylib.calc`` and missed the
    # ``from mylib.calc import add`` import); now finds the pinning test file.
    assert pinned_test_files(tmp_path, "src/mylib/calc.py", "add") == [
        "tests/test_calc.py"]


def test_pinned_test_nodes_finds_src_layout_node(tmp_path: Path):
    from app.execution.stub_synthesis import pinned_test_nodes

    _src_layout_project(tmp_path)
    assert pinned_test_nodes(tmp_path, "src/mylib/calc.py", "add") == [
        "tests/test_calc.py::test_add"]


def test_covering_test_files_finds_src_layout(tmp_path: Path):
    from app.engine.mutation_tester import covering_test_files

    _src_layout_project(tmp_path)
    # Impact-scoping was blind ([]); now the covering test is in scope.
    assert covering_test_files(tmp_path, "src/mylib/calc.py") == [
        "tests/test_calc.py"]


def test_root_stripped_dotted_paths_keep_raw_path_too(tmp_path: Path):
    # Both the raw path-joined dotted path AND the src-stripped one are acceptable
    # import targets, so a (rare) literal ``import src.mylib.calc`` still matches.
    from app.execution.stub_synthesis import _module_dotted_paths

    _src_layout_project(tmp_path)
    paths = _module_dotted_paths(tmp_path, "src/mylib/calc.py")
    assert "mylib.calc" in paths   # the import the test actually writes
    assert "src.mylib.calc" in paths  # the raw path-join, kept for back-compat


# --- the headline fix: a src/ project now LANDS real code --------------------

def test_src_layout_lands_via_plan(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _src_layout_project(tmp_path)
    plan = plan_implement_stub(str(tmp_path), "src/mylib/calc.py")
    filled = plan.new_contents.get("src/mylib/calc.py")
    # Was nothing (empty plan) before the fix; now the real body lands.
    assert filled is not None
    assert "return a + b" in filled
    assert "raise NotImplementedError" not in filled
    assert plan.scoped_test_nodes == ["tests/test_calc.py::test_add"]


def test_src_layout_lands_via_compile_objective(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _src_layout_project(tmp_path)
    result = compile_objective(
        str(tmp_path), objective="implement-stub",
        scope_module="src/mylib/calc.py", scope_verify=True)
    landed = (tmp_path / "src" / "mylib" / "calc.py").read_text(encoding="utf-8")
    # The objective applied the fill on disk through the verified-apply engine —
    # was nothing before the fix (the campaign found no move on a src/ layout).
    assert "return a + b" in landed
    assert result.applied and result.steps  # a real move was composed + written


# --- pyproject-declared custom roots -----------------------------------------

def test_custom_pythonpath_root_links_and_lands(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub
    from app.execution.stub_synthesis import pinned_test_files
    from app.engine.mutation_tester import covering_test_files

    _custom_root_project(tmp_path)
    assert pinned_test_files(tmp_path, "lib/mylib/calc.py", "add") == [
        "tests/test_calc.py"]
    assert covering_test_files(tmp_path, "lib/mylib/calc.py") == [
        "tests/test_calc.py"]
    filled = plan_implement_stub(str(tmp_path), "lib/mylib/calc.py").new_contents.get(
        "lib/mylib/calc.py")
    assert filled is not None and "return a + b" in filled


def test_setuptools_package_dir_root_links(tmp_path: Path):
    from app.execution.stub_synthesis import pinned_test_files
    from app.engine.mutation_tester import covering_test_files, _source_roots

    _package_dir_project(tmp_path)
    # The setuptools ``package-dir`` branch contributes ``lib`` as a source root.
    assert "lib" in _source_roots(tmp_path)
    assert pinned_test_files(tmp_path, "lib/mylib/calc.py", "add") == [
        "tests/test_calc.py"]
    assert covering_test_files(tmp_path, "lib/mylib/calc.py") == [
        "tests/test_calc.py"]


# --- NON-src project: byte-identical, no regression --------------------------

def test_non_src_linkage_unchanged(tmp_path: Path):
    from app.execution.stub_synthesis import pinned_test_files, _module_dotted_paths
    from app.engine.mutation_tester import covering_test_files

    _non_src_project(tmp_path)
    # No ``src/``/declared root applies, so ONLY the raw dotted path is a target —
    # exactly the pre-fix candidate set.
    assert _module_dotted_paths(tmp_path, "app/calc.py") == ["app.calc"]
    assert pinned_test_files(tmp_path, "app/calc.py", "add") == ["tests/test_calc.py"]
    assert covering_test_files(tmp_path, "app/calc.py") == ["tests/test_calc.py"]


def test_non_src_landing_unchanged(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _non_src_project(tmp_path)
    filled = plan_implement_stub(str(tmp_path), "app/calc.py").new_contents.get(
        "app/calc.py")
    assert filled == "def add(a, b):\n    return a + b\n"


# --- determinism -------------------------------------------------------------

def test_src_layout_linkage_is_deterministic(tmp_path: Path):
    from app.execution.stub_synthesis import pinned_test_files, _module_dotted_paths
    from app.engine.mutation_tester import covering_test_files

    _src_layout_project(tmp_path)
    assert _module_dotted_paths(tmp_path, "src/mylib/calc.py") == \
        _module_dotted_paths(tmp_path, "src/mylib/calc.py")
    assert pinned_test_files(tmp_path, "src/mylib/calc.py", "add") == \
        pinned_test_files(tmp_path, "src/mylib/calc.py", "add")
    assert covering_test_files(tmp_path, "src/mylib/calc.py") == \
        covering_test_files(tmp_path, "src/mylib/calc.py")


def test_src_layout_landing_is_deterministic(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub
    import tempfile

    _src_layout_project(tmp_path)
    first = plan_implement_stub(str(tmp_path), "src/mylib/calc.py").new_contents.get(
        "src/mylib/calc.py")
    with tempfile.TemporaryDirectory() as d:
        root2 = Path(d)
        _src_layout_project(root2)
        second = plan_implement_stub(str(root2), "src/mylib/calc.py").new_contents.get(
            "src/mylib/calc.py")
    assert first == second and first is not None


def test_no_pyproject_degrades_to_src_convention(tmp_path: Path):
    # Best-effort: with NO pyproject at all, the ``src/`` convention still applies
    # (the de-facto root), so a src-layout project without config still links.
    from app.execution.stub_synthesis import pinned_test_files
    from app.engine.mutation_tester import covering_test_files, _source_roots

    (tmp_path / "src" / "mylib").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "mylib" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "mylib" / "calc.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from mylib.calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8")
    assert _source_roots(tmp_path) == ["src"]
    assert pinned_test_files(tmp_path, "src/mylib/calc.py", "add") == [
        "tests/test_calc.py"]
    assert covering_test_files(tmp_path, "src/mylib/calc.py") == [
        "tests/test_calc.py"]
