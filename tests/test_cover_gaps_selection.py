"""Tests for cover-gaps' lean untested-module selection (the perf fix) and its
PUBLIC-LIBRARY-MODULE target gate (the targeting fix).

The selection in app/execution/objectives/cover_gaps.py replaced a ~200s
ProjectProfiler.profile() call with an index-based, test-source-linkage scan.
These lock the linkage logic: a module a real test imports is covered (both the
`import a.b.c` and `from a.b import c` forms), everything else is a gap, and
package markers are never proposed.

The targeting fix (DELIVERABLE B.1) adds an eligibility gate in the SELECTOR
``_untested_own_modules`` (reusing wire-module-exports' ``_is_library_module`` +
``_SCRIPT_DENYLIST``, PLUS a private-module ``_``-stem skip), so cover-gaps stops
manufacturing near-zero-value smoke tests on config / generated / private trivia
(the pilot found ``docs.conf``, ``funcy._inspect``, ``humanize._version``) while
STILL selecting a real public library module that genuinely lacks a test.
"""

from __future__ import annotations

import textwrap

from app.execution.objectives.cover_gaps import (
    _is_coverable_target,
    _untested_own_modules,
)


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
    # Still holds — now via the `_`-stem rule in _is_coverable_target, which
    # subsumes the old explicit __init__.py skip (a package marker is low value).
    _project(tmp_path)
    _write(tmp_path, "app/sub/__init__.py")
    untested = _untested_own_modules(tmp_path)
    assert not any(m.endswith("__init__.py") for m in untested)


# --- the PUBLIC-LIBRARY-MODULE target gate (DELIVERABLE B.1) -----------------

def test_skips_docs_conf_no_package_marker(tmp_path):
    # docs/conf.py: a Sphinx config whose dir has no __init__.py AND a denylisted
    # basename -> not a candidate (the inflection pilot's `tests/test_conf.py`).
    _project(tmp_path)
    _write(tmp_path, "docs/conf.py", "project = 'demo'\n")
    untested = _untested_own_modules(tmp_path)
    assert "docs/conf.py" not in untested
    assert _is_coverable_target(tmp_path, "docs/conf.py") is False


def test_skips_setup_py(tmp_path):
    # setup.py: denylisted packaging script with no package __init__ beside it.
    _project(tmp_path)
    _write(tmp_path, "setup.py", "from setuptools import setup\nsetup()\n")
    untested = _untested_own_modules(tmp_path)
    assert "setup.py" not in untested
    assert _is_coverable_target(tmp_path, "setup.py") is False


def test_skips_private_module_in_a_package(tmp_path):
    # pkg/_inspect.py: an importable library module (dir HAS __init__.py) but
    # PRIVATE (leading `_`) -> skipped (the funcy pilot's `funcy._inspect`).
    _project(tmp_path)
    _write(tmp_path, "app/_inspect.py", "def helper():\n    return 1\n")
    untested = _untested_own_modules(tmp_path)
    assert "app/_inspect.py" not in untested
    assert _is_coverable_target(tmp_path, "app/_inspect.py") is False


def test_skips_version_module_denylist(tmp_path):
    # pkg/_version.py: caught by BOTH the denylist and the `_`-stem rule (the
    # humanize pilot's `humanize._version`).
    _project(tmp_path)
    _write(tmp_path, "app/_version.py", "__version__ = '1.0'\n")
    untested = _untested_own_modules(tmp_path)
    assert "app/_version.py" not in untested
    assert _is_coverable_target(tmp_path, "app/_version.py") is False


def test_still_selects_a_real_public_library_module(tmp_path):
    # REGRESSION: the gate must NOT over-skip. A genuine public library module
    # with a safely-callable public function is STILL a candidate.
    _project(tmp_path)
    _write(tmp_path, "app/widget.py", "def area(w, h):\n    return w * h\n")
    untested = _untested_own_modules(tmp_path)
    assert "app/widget.py" in untested
    assert _is_coverable_target(tmp_path, "app/widget.py") is True


def test_init_marker_skipped_via_stem_rule(tmp_path):
    # The `_`-stem rule (not a separate __init__ branch) drops package markers.
    _project(tmp_path)
    _write(tmp_path, "app/sub/__init__.py")
    assert _is_coverable_target(tmp_path, "app/sub/__init__.py") is False


def test_gate_drops_noise_but_keeps_the_real_target_together(tmp_path):
    # The whole point: in one project, the noise targets are dropped and the one
    # real public module survives — exactly the pilot's intended outcome.
    _project(tmp_path)
    _write(tmp_path, "app/widget.py", "def area(w, h):\n    return w * h\n")
    _write(tmp_path, "app/_inspect.py", "def helper():\n    return 1\n")
    _write(tmp_path, "app/_version.py", "__version__ = '1.0'\n")
    _write(tmp_path, "docs/conf.py", "project = 'demo'\n")
    _write(tmp_path, "setup.py", "from setuptools import setup\nsetup()\n")
    untested = _untested_own_modules(tmp_path)
    assert untested == ["app/widget.py"]


def test_selection_is_deterministic_across_two_calls(tmp_path):
    _project(tmp_path)
    _write(tmp_path, "app/widget.py", "def area(w, h):\n    return w * h\n")
    _write(tmp_path, "app/gadget.py", "def vol(x):\n    return x ** 3\n")
    _write(tmp_path, "app/_inspect.py", "def helper():\n    return 1\n")
    assert _untested_own_modules(tmp_path) == _untested_own_modules(tmp_path)
