"""Tests for cover-gaps' lean untested-module selection (the perf fix).

The selection in app/execution/objectives/cover_gaps.py replaced a ~200s
ProjectProfiler.profile() call with an index-based, test-source-linkage scan.
These lock the linkage logic: a module a real test imports is covered (both the
`import a.b.c` and `from a.b import c` forms), everything else is a gap, and
package markers are never proposed.
"""

from __future__ import annotations

import textwrap

from app.execution.objectives.cover_gaps import _untested_own_modules


def _write(root, rel, body=""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def _project(root):
    _write(root, "pyproject.toml", "[project]\nname='demo'\nversion='0'\n")
    _write(root, "app/__init__.py")
    return root


def test_untested_module_is_a_gap(tmp_path):
    _project(tmp_path)
    _write(tmp_path, "app/lonely.py", "def f():\n    return 1\n")
    assert "app/lonely.py" in _untested_own_modules(tmp_path)


def test_dotted_import_marks_covered(tmp_path):
    # Form A: `from app.covered import ...` — the dotted path appears verbatim.
    _project(tmp_path)
    _write(tmp_path, "app/covered.py", "def g():\n    return 2\n")
    _write(tmp_path, "tests/test_covered.py",
           "from app.covered import g\ndef test_g():\n    assert g() == 2\n")
    assert "app/covered.py" not in _untested_own_modules(tmp_path)


def test_from_package_import_marks_covered(tmp_path):
    # Form B: `from app import mod` — parent imported-from, bare stem in the list.
    _project(tmp_path)
    _write(tmp_path, "app/mod.py", "VALUE = 3\n")
    _write(tmp_path, "tests/test_mod.py",
           "from app import mod\ndef test_v():\n    assert mod.VALUE == 3\n")
    assert "app/mod.py" not in _untested_own_modules(tmp_path)


def test_prefix_is_not_a_false_match(tmp_path):
    # `foobar` must not be marked covered by a test that only imports `foo`.
    _project(tmp_path)
    _write(tmp_path, "app/foo.py", "x = 1\n")
    _write(tmp_path, "app/foobar.py", "y = 2\n")
    _write(tmp_path, "tests/test_foo.py", "from app.foo import x\n")
    untested = _untested_own_modules(tmp_path)
    assert "app/foobar.py" in untested  # not covered by the foo import
    assert "app/foo.py" not in untested


def test_package_markers_are_never_proposed(tmp_path):
    _project(tmp_path)
    _write(tmp_path, "app/sub/__init__.py")
    untested = _untested_own_modules(tmp_path)
    assert not any(m.endswith("__init__.py") for m in untested)
