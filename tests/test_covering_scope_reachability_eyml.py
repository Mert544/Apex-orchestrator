"""Falsifiable tests for import-reachability covering scope — the fix for the
one hole that let a broken change be stamped "verified" on a real external
project (`packaging`, 2026-07): impact scoping matched a test to a changed
module only by the module's own dotted path and its parent packages, so it
missed two real import shapes:

* **child import** — ``tests/test_licenses.py`` imports
  ``packaging.licenses._spdx``; importing that submodule EXECUTES
  ``packaging/licenses/__init__.py``, yet a change to that ``__init__`` found
  no covering test and the move sailed through "verified";
* **transitive import** — a test imports ``pkg.api`` and ``api`` itself
  imports ``pkg._impl``; a change to ``_impl`` is exercised by the test, but
  no import statement in the test names ``_impl``.

Every test here encodes the honest semantics ("which tests would really
execute this module?"), not the implementation — each failed on the
pre-fix code (verified red-first), so a regression cannot pass silently.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.mutation_tester import covering_test_files
from app.engine.test_impact import impacted_test_files


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _flat_project(tmp_path: Path) -> Path:
    """pkg/ with an __init__ that re-exports, a private impl, an api module
    importing the impl absolutely, a relative-import twin, and a loner."""
    _write(tmp_path, "pkg/__init__.py", "from pkg._impl import f\n")
    _write(tmp_path, "pkg/_impl.py", "def f():\n    return 1\n")
    _write(tmp_path, "pkg/api.py",
           "from pkg._impl import f\n\n\ndef api():\n    return f()\n")
    _write(tmp_path, "pkg/rel_api.py",
           "from ._impl import f\n\n\ndef rel_api():\n    return f()\n")
    _write(tmp_path, "pkg/loner.py", "def alone():\n    return 9\n")
    _write(tmp_path, "tests/test_impl.py",
           "from pkg._impl import f\n\n\ndef test_f():\n    assert f() == 1\n")
    _write(tmp_path, "tests/test_api.py",
           "from pkg.api import api\n\n\ndef test_api():\n    assert api() == 1\n")
    _write(tmp_path, "tests/test_rel_api.py",
           "from pkg.rel_api import rel_api\n\n\n"
           "def test_rel():\n    assert rel_api() == 1\n")
    return tmp_path


# --- (A) child import executes the changed package __init__ -------------------

def test_child_import_covers_changed_package_init(tmp_path):
    # The literal packaging fake-green: the only test imports pkg._impl, the
    # changed file is pkg/__init__.py. Importing pkg._impl EXECUTES
    # pkg/__init__.py, so that test must be in scope.
    _flat_project(tmp_path)
    covering = covering_test_files(tmp_path, "pkg/__init__.py")
    assert "tests/test_impl.py" in covering


# --- (B) transitive imports reach the changed module ---------------------------

def test_transitive_import_covers_changed_module(tmp_path):
    # test_api imports pkg.api; pkg/api.py imports pkg._impl; a change to
    # pkg/_impl.py is executed by test_api and must be in its covering scope.
    _flat_project(tmp_path)
    covering = covering_test_files(tmp_path, "pkg/_impl.py")
    assert "tests/test_api.py" in covering


def test_relative_transitive_import_is_resolved(tmp_path):
    # Same shape but the intermediate hop is a RELATIVE import
    # (``from ._impl import f``) — the dominant style inside real packages.
    _flat_project(tmp_path)
    covering = covering_test_files(tmp_path, "pkg/_impl.py")
    assert "tests/test_rel_api.py" in covering


def test_src_layout_transitive_import_is_resolved(tmp_path):
    # src/ layout: the test imports mylib.api (root-stripped name); api imports
    # mylib._impl; the changed file is src/mylib/_impl.py.
    _write(tmp_path, "src/mylib/__init__.py", "")
    _write(tmp_path, "src/mylib/_impl.py", "def f():\n    return 2\n")
    _write(tmp_path, "src/mylib/api.py",
           "from mylib._impl import f\n\n\ndef api():\n    return f()\n")
    _write(tmp_path, "tests/test_api.py",
           "from mylib.api import api\n\n\ndef test_api():\n    assert api() == 2\n")
    covering = covering_test_files(tmp_path, "src/mylib/_impl.py")
    assert "tests/test_api.py" in covering


def test_import_cycle_terminates_and_covers(tmp_path):
    # a <-> b cycle must not hang the reachability walk, and a test importing
    # either side of the cycle covers a change to the other.
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/a.py", "import pkg.b\n\n\ndef fa():\n    return 1\n")
    _write(tmp_path, "pkg/b.py", "import pkg.a\n\n\ndef fb():\n    return 2\n")
    _write(tmp_path, "tests/test_b.py",
           "import pkg.b\n\n\ndef test_b():\n    assert pkg.b.fb() == 2\n")
    covering = covering_test_files(tmp_path, "pkg/a.py")
    assert "tests/test_b.py" in covering


# --- soundness: reachability must not degrade into match-everything -----------

def test_unrelated_module_is_not_swept_in(tmp_path):
    # loner.py has no importers; a test that only imports pkg.api must NOT be
    # charged to it. Guards against the fix ballooning every scope.
    _flat_project(tmp_path)
    covering = covering_test_files(tmp_path, "pkg/loner.py")
    assert "tests/test_api.py" not in covering
    assert "tests/test_rel_api.py" not in covering


def test_direct_import_still_covered(tmp_path):
    # Regression: the original exact-path matching must keep working.
    _flat_project(tmp_path)
    assert "tests/test_impl.py" in covering_test_files(tmp_path, "pkg/_impl.py")


def test_result_is_deterministic_across_calls(tmp_path):
    # Two calls on the same tree (second may hit the graph cache) must agree.
    _flat_project(tmp_path)
    first = covering_test_files(tmp_path, "pkg/_impl.py")
    second = covering_test_files(tmp_path, "pkg/_impl.py")
    assert first == second


def test_edit_between_calls_invalidates_the_cache(tmp_path):
    # The graph cache is keyed on file stats: rewiring an importer between two
    # calls must change the answer, never serve the stale scope.
    _flat_project(tmp_path)
    before = covering_test_files(tmp_path, "pkg/loner.py")
    assert "tests/test_api.py" not in before
    api = tmp_path / "pkg" / "api.py"
    api.write_text("from pkg.loner import alone\n\n\ndef api():\n"
                   "    return alone()\n", encoding="utf-8")
    later = api.stat().st_mtime_ns + 1_000_000
    import os
    os.utime(api, ns=(later, later))
    after = covering_test_files(tmp_path, "pkg/loner.py")
    assert "tests/test_api.py" in after


# --- the develop-loop integration point ----------------------------------------

def test_impacted_tests_include_transitive_scope(tmp_path):
    # impacted_test_files is what the per-move verify gate consumes: the
    # transitive scope must flow through it, or moves stay "no-suite".
    _flat_project(tmp_path)
    impacted = impacted_test_files(tmp_path, ["pkg/_impl.py"])
    assert "tests/test_api.py" in impacted
    assert "tests/test_impl.py" in impacted
