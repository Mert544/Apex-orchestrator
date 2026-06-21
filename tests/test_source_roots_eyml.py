"""Unit tests for the extracted shared source-root utility,
:func:`app.engine.source_roots.source_roots`.

The detection used to live in ``mutation_tester._source_roots`` and was byte-copied
into ``export_wiring`` ("to stay decoupled"), which the duplication detector flagged
(12 clone blocks, dropping the self-grade A+99 -> A-90). The fix extracts ONE shared
module; these tests pin its behaviour and prove the extraction is byte-identical to
the original:

* the de-facto ``src/`` convention is ALWAYS a root (no config needed);
* pyproject roots are honored — ``[tool.pytest.ini_options] pythonpath``,
  ``[tool.setuptools] package-dir`` values, ``[tool.setuptools.packages.find]
  where``;
* each declared root contributes only its FIRST path segment (``./src`` -> ``src``);
* a missing / empty / unparseable pyproject (or no ``tomllib``) degrades to ``src/``
  alone — never raises;
* output is sorted and deterministic;
* the historical private alias ``mutation_tester._source_roots`` still resolves to
  the shared function, AND ``export_wiring`` imports the same object — so existing
  callers (e.g. ``stub_synthesis``) keep working without edits.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.source_roots import source_roots


# --- fixtures ----------------------------------------------------------------

def _write_pyproject(root: Path, body: str) -> None:
    """Write ``pyproject.toml`` with ``body`` under ``root``."""
    (root / "pyproject.toml").write_text(body, encoding="utf-8")


# --- the de-facto src convention ---------------------------------------------

def test_src_convention_always_present_without_any_config(tmp_path: Path) -> None:
    """No pyproject at all: the ``src/`` convention is the sole root."""
    assert source_roots(tmp_path) == ["src"]


def test_src_present_even_when_pyproject_declares_only_others(tmp_path: Path) -> None:
    """``src`` is unconditional — a declared ``lib`` is ADDED to it, not a
    replacement."""
    _write_pyproject(
        tmp_path,
        "[tool.pytest.ini_options]\npythonpath = ['lib']\n",
    )
    assert source_roots(tmp_path) == ["lib", "src"]


# --- pytest pythonpath -------------------------------------------------------

def test_pytest_pythonpath_list(tmp_path: Path) -> None:
    """A list ``pythonpath`` contributes each entry (deduped against ``src``)."""
    _write_pyproject(
        tmp_path,
        "[tool.pytest.ini_options]\npythonpath = ['src', 'lib']\n",
    )
    assert source_roots(tmp_path) == ["lib", "src"]


def test_pytest_pythonpath_scalar_string(tmp_path: Path) -> None:
    """A bare-string ``pythonpath`` is normalized to a one-element list."""
    _write_pyproject(
        tmp_path,
        "[tool.pytest.ini_options]\npythonpath = 'lib'\n",
    )
    assert source_roots(tmp_path) == ["lib", "src"]


# --- setuptools package-dir / packages.find where ----------------------------

def test_setuptools_package_dir_values(tmp_path: Path) -> None:
    """``[tool.setuptools] package-dir`` VALUES are roots (the keys are ignored)."""
    _write_pyproject(
        tmp_path,
        '[tool.setuptools]\npackage-dir = {"" = "app"}\n',
    )
    assert source_roots(tmp_path) == ["app", "src"]


def test_setuptools_packages_find_where(tmp_path: Path) -> None:
    """``[tool.setuptools.packages.find] where`` entries are roots."""
    _write_pyproject(
        tmp_path,
        "[tool.setuptools.packages.find]\nwhere = ['pkgs']\n",
    )
    assert source_roots(tmp_path) == ["pkgs", "src"]


def test_all_pyproject_sources_combined(tmp_path: Path) -> None:
    """pytest pythonpath + setuptools package-dir + packages.find where all fold
    into one sorted, deduped set alongside ``src``."""
    _write_pyproject(
        tmp_path,
        "[tool.pytest.ini_options]\npythonpath = ['lib']\n"
        '[tool.setuptools]\npackage-dir = {"" = "app"}\n'
        "[tool.setuptools.packages.find]\nwhere = ['pkgs', 'src']\n",
    )
    assert source_roots(tmp_path) == ["app", "lib", "pkgs", "src"]


# --- first-path-segment normalization ----------------------------------------

def test_only_first_path_segment_is_used(tmp_path: Path) -> None:
    """A declared root like ``./src`` or ``lib/pkg`` contributes only its leading
    component (``src`` / ``lib``); a bare ``.`` contributes nothing."""
    _write_pyproject(
        tmp_path,
        "[tool.pytest.ini_options]\npythonpath = ['./lib', 'pkgs/inner', '.']\n",
    )
    assert source_roots(tmp_path) == ["lib", "pkgs", "src"]


# --- graceful degradation ----------------------------------------------------

def test_missing_pyproject_degrades_to_src(tmp_path: Path) -> None:
    """No pyproject file -> ``['src']`` (best-effort, never raises)."""
    assert not (tmp_path / "pyproject.toml").exists()
    assert source_roots(tmp_path) == ["src"]


def test_empty_pyproject_degrades_to_src(tmp_path: Path) -> None:
    """An empty pyproject (no ``[tool]`` table) -> ``['src']``."""
    _write_pyproject(tmp_path, "")
    assert source_roots(tmp_path) == ["src"]


def test_unparseable_pyproject_degrades_to_src(tmp_path: Path) -> None:
    """Malformed TOML is swallowed -> ``['src']`` (best-effort)."""
    _write_pyproject(tmp_path, "this is not = valid toml [[[\n")
    assert source_roots(tmp_path) == ["src"]


def test_tool_not_a_table_degrades_to_src(tmp_path: Path) -> None:
    """A ``tool`` key that is not a table is ignored -> ``['src']``."""
    _write_pyproject(tmp_path, "tool = 'oops'\n")
    assert source_roots(tmp_path) == ["src"]


def test_non_string_pythonpath_entries_ignored(tmp_path: Path) -> None:
    """Non-string entries in a ``pythonpath`` list are dropped, not coerced."""
    _write_pyproject(
        tmp_path,
        "[tool.pytest.ini_options]\npythonpath = ['lib', 3, true]\n",
    )
    assert source_roots(tmp_path) == ["lib", "src"]


# --- determinism -------------------------------------------------------------

def test_deterministic_and_sorted(tmp_path: Path) -> None:
    """Same input -> same sorted output on repeated calls (no clock/random)."""
    _write_pyproject(
        tmp_path,
        "[tool.pytest.ini_options]\npythonpath = ['zeta', 'alpha', 'lib']\n",
    )
    first = source_roots(tmp_path)
    assert first == sorted(first)
    assert first == source_roots(tmp_path)
    assert first == ["alpha", "lib", "src", "zeta"]


# --- behaviour-preserving extraction: the re-export identity -----------------

def test_mutation_tester_reexports_the_shared_function() -> None:
    """``mutation_tester._source_roots`` IS the shared ``source_roots`` — the
    historical private name (imported by ``stub_synthesis``) keeps working without
    editing that module."""
    from app.engine.mutation_tester import _source_roots as mt_source_roots

    assert mt_source_roots is source_roots


def test_export_wiring_imports_the_shared_function() -> None:
    """``export_wiring`` uses the same shared object — the 12 duplicated helper
    blocks are gone, replaced by one import."""
    from app.execution import export_wiring

    assert export_wiring.source_roots is source_roots
