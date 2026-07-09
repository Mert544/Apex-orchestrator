"""Apex's immune posture — ``app/reporting/immune_report`` + ``apex immune``.

Pins the fast, deterministic blind-spot ranking (many callable functions + no
linked test = highest risk) and the honest apply delegation to strengthen-tests.

SEMANTIC UPGRADE (2026-07-08): "linked test" is now decided by IMPORT
REACHABILITY — a module is linked iff at least one test file's imports would
EXECUTE it (directly, transitively through a project module, or via an
ancestor-package ``__init__``), the exact rule ``covering_test_files`` uses —
not by the old ``tests/test_<stem>*.py`` filename glob. Both honest directions
are pinned below: a same-named test that never imports the module no longer
masks a true blind spot, and a differently-named test that DOES import it no
longer cries wolf.
"""

from __future__ import annotations

from pathlib import Path

from app.reporting.immune_report import (
    _has_linked_test,
    immune_posture,
    render_immune_markdown,
)


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _project(tmp_path: Path) -> Path:
    _write(tmp_path, "app/__init__.py", "")
    # wide + untested (2 public funcs, no linked test) -> highest risk
    _write(tmp_path, "app/wide.py",
           "def a(x):\n    return x\ndef b(y):\n    return y\n")
    # has a linked test -> lower risk
    _write(tmp_path, "app/covered.py", "def c(z):\n    return z\n")
    _write(tmp_path, "tests/test_covered.py",
           "from app.covered import c\ndef test_c():\n    assert c(1) == 1\n")
    # no blindly-callable public function -> not a candidate at all
    _write(tmp_path, "app/private.py", "def _hidden(x):\n    return x\n")
    return tmp_path


def _reach_project(tmp_path: Path) -> Path:
    """A project whose only test reaches ``pkg/_impl.py`` TRANSITIVELY (the test
    imports ``pkg.api``, which imports ``pkg._impl``) under a filename that names
    neither module — plus a ghost: ``tests/test_helper.py`` exists by NAME for
    ``app/helper.py`` but never imports anything from it."""
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/_impl.py", "def f(x):\n    return x\n")
    _write(tmp_path, "pkg/api.py",
           "from pkg._impl import f\ndef g(y):\n    return f(y)\n")
    _write(tmp_path, "tests/test_endpoints.py",
           "from pkg.api import g\ndef test_g():\n    assert g(1) == 1\n")
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/helper.py", "def h(x):\n    return x\n")
    _write(tmp_path, "tests/test_helper.py",
           "def test_unrelated():\n    assert True\n")
    return tmp_path


def test_ranks_untested_wide_module_first(tmp_path):
    posture = immune_posture(_project(tmp_path))
    mods = [r["module"] for r in posture["top_risk"]]
    assert mods[0] == "app/wide.py"                  # untested + widest
    assert "app/covered.py" in mods                  # candidate but lower
    assert "app/private.py" not in mods              # no callable public fn


def test_reports_signals_per_module(tmp_path):
    posture = immune_posture(_project(tmp_path))
    by_mod = {r["module"]: r for r in posture["top_risk"]}
    assert by_mod["app/wide.py"]["callable_funcs"] == 2
    assert by_mod["app/wide.py"]["has_linked_test"] is False
    assert by_mod["app/covered.py"]["has_linked_test"] is True


# === the semantic upgrade, both honest directions ============================

def test_named_but_never_importing_test_is_not_linked(tmp_path):
    """Direction 1 (true blind spots SURFACE): ``tests/test_helper.py`` exists by
    NAME for ``app/helper.py`` but imports nothing from it, so the suite cannot
    possibly exercise the module — the old filename glob called this linked
    (fake cover); import reachability must not."""
    root = _reach_project(tmp_path)
    assert _has_linked_test(root, "app/helper.py") is False
    by_mod = {r["module"]: r for r in immune_posture(root)["top_risk"]}
    assert by_mod["app/helper.py"]["has_linked_test"] is False


def test_transitively_imported_module_is_linked_despite_test_name(tmp_path):
    """Direction 2 (false alarms DROP): ``tests/test_endpoints.py`` imports
    ``pkg.api`` which imports ``pkg._impl`` — the test EXECUTES ``_impl`` even
    though no test file is named for it. The old glob cried wolf here; import
    reachability must count it linked."""
    root = _reach_project(tmp_path)
    assert _has_linked_test(root, "pkg/_impl.py") is True
    assert _has_linked_test(root, "pkg/api.py") is True
    by_mod = {r["module"]: r for r in immune_posture(root)["top_risk"]}
    assert by_mod["pkg/_impl.py"]["has_linked_test"] is True


def test_direct_import_links_regardless_of_test_filename(tmp_path):
    """A test file whose NAME matches nothing still links every module it
    imports by dotted path — filenames carry no signal any more."""
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/foo.py", "def f(x):\n    return x\n")
    _write(tmp_path, "app/baz.py", "def z(x):\n    return x\n")
    _write(tmp_path, "tests/test_everything_else.py",
           "from app.foo import f\ndef test_f():\n    assert f(1) == 1\n")
    assert _has_linked_test(tmp_path, "app/foo.py") is True
    assert _has_linked_test(tmp_path, "app/baz.py") is False


def test_private_module_is_linked_by_import_not_filename(tmp_path):
    """SEMANTIC UPGRADE of the old underscore-strip filename case: a private
    module (``_apply_verify.py``) tested under ANY filename counts as linked
    because the test IMPORTS it — imports don't care about leading underscores
    or naming conventions. A genuinely-unimported private module stays blind
    even though its stripped stem happens to prefix-match the test's name."""
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/execution/__init__.py", "")
    _write(tmp_path, "app/execution/_apply_verify.py",
           "def v(x):\n    return x\n")
    _write(tmp_path, "app/execution/_never_tested.py",
           "def n(x):\n    return x\n")
    _write(tmp_path, "tests/test_apply_verify_shared.py",
           "from app.execution._apply_verify import v\n"
           "def test_v():\n    assert v(1) == 1\n")
    assert _has_linked_test(tmp_path, "app/execution/_apply_verify.py") is True
    assert _has_linked_test(tmp_path, "app/execution/_never_tested.py") is False


def test_import_under_package_prefix_links_the_package_init(tmp_path):
    """Importing ANYTHING under a package executes the package ``__init__`` on
    the way — even a name the graph cannot see (e.g. a compiled extension), so
    the prefix rule links the ``__init__`` exactly as covering-scope does."""
    _write(tmp_path, "pkg2/__init__.py", "def top(x):\n    return x\n")
    _write(tmp_path, "tests/test_native.py",
           "import pkg2.native_ext  # noqa: F401  (not a parseable .py module)\n")
    assert _has_linked_test(tmp_path, "pkg2/__init__.py") is True


def test_linkage_agrees_with_covering_test_files(tmp_path):
    """ONE SOURCE OF TRUTH: for every module, the posture's linked/unlinked call
    must equal ``bool(covering_test_files(...))`` — the established covering
    matcher the strengthen-tests engine scopes its mutant runs with. The immune
    index is a hoisted-out-of-the-loop implementation of the SAME rule, so any
    divergence is a bug."""
    from app.engine.mutation_tester import covering_test_files

    root = _reach_project(tmp_path)
    _write(root, "pkg2/__init__.py", "def top(x):\n    return x\n")
    _write(root, "tests/test_native.py", "import pkg2.native_ext  # noqa: F401\n")
    for rel in ("pkg/_impl.py", "pkg/api.py", "pkg/__init__.py",
                "app/helper.py", "pkg2/__init__.py"):
        assert _has_linked_test(root, rel) == bool(
            covering_test_files(root, rel)), rel


# === edge / empty paths ======================================================

def test_no_tests_at_all_means_nothing_is_linked(tmp_path):
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/solo.py", "def f(x):\n    return x\n")
    assert _has_linked_test(tmp_path, "app/solo.py") is False
    rows = immune_posture(tmp_path)["top_risk"]
    assert [r["module"] for r in rows] == ["app/solo.py"]
    assert rows[0]["has_linked_test"] is False


def test_unparseable_test_file_cannot_prove_linkage(tmp_path):
    """A test file that fails to parse contributes no imports (honest degrade,
    no crash) — a same-named but broken test cannot vouch for the module."""
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/solo.py", "def f(x):\n    return x\n")
    _write(tmp_path, "tests/test_solo.py", "def broken(:\n")
    assert _has_linked_test(tmp_path, "app/solo.py") is False


def test_is_deterministic(tmp_path):
    root = _project(tmp_path)
    assert immune_posture(root) == immune_posture(root)


def test_is_deterministic_across_reach_paths(tmp_path):
    # Two sweeps over a project that exercises BOTH the direct-name path and the
    # transitive import-reach path must be identical (no clock/random anywhere).
    root = _reach_project(tmp_path)
    assert immune_posture(root) == immune_posture(root)


def test_top_bounds_the_list(tmp_path):
    assert len(immune_posture(_project(tmp_path), top=1)["top_risk"]) == 1
    assert immune_posture(_project(tmp_path), top=0)["top_risk"] == []


def test_empty_project_is_honest(tmp_path):
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/only_private.py", "def _p(x):\n    return x\n")
    posture = immune_posture(tmp_path)
    assert posture["top_risk"] == []
    assert "nothing to immunise" in render_immune_markdown(posture)


def test_markdown_flags_untested_modules(tmp_path):
    md = render_immune_markdown(immune_posture(_project(tmp_path)))
    assert "Immune posture" in md
    assert "app/wide.py" in md
    assert "no linked test" in md


def test_cli_immune_report_json_and_text(tmp_path, capsys):
    import argparse

    from app.cli_insight import cmd_immune
    root = _project(tmp_path)
    rc = cmd_immune(argparse.Namespace(
        target=str(root), top=20, apply=False, json=True))
    assert rc == 0
    assert '"module": "app/wide.py"' in capsys.readouterr().out

    rc = cmd_immune(argparse.Namespace(
        target=str(root), top=20, apply=False, json=False))
    assert rc == 0
    assert "blindest" in capsys.readouterr().out


def test_cli_immune_apply_is_honest_when_nothing_lands(tmp_path, capsys):
    import argparse

    from app.cli_insight import cmd_immune
    # a project whose only public fn is already covered -> no killable survivor
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/pass_through.py", "def echo(x):\n    return x\n")
    _write(tmp_path, "tests/test_pass_through.py",
           "from app.pass_through import echo\ndef test_echo():\n    assert echo(7) == 7\n")
    _write(tmp_path, "pyproject.toml", "[project]\nname='d'\nversion='0'\n")
    rc = cmd_immune(argparse.Namespace(
        target=str(tmp_path), top=20, apply=True, max_modules=1, json=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert '"count": 0' in out
