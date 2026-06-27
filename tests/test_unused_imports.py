"""Tests for the remove-unused-imports transform."""

from __future__ import annotations

import ast

from app.execution.cross_file_rename import _py_files
from app.execution.unused_imports import (
    _is_fixture_path,
    _is_package_init,
    plan_remove_unused_imports,
)


def _write(tmp_path, rel, source):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


# ── plainly-unused import removed ───────────────────────────────────────────

def test_unused_import_removed(tmp_path):
    src = (
        "import os\n"
        "\n"
        "x = 1\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "import os" not in new
    assert "x = 1" in new
    assert plan.edits_by_file["m.py"] == 1
    ast.parse(new)


# ── used import kept ────────────────────────────────────────────────────────

def test_used_import_kept(tmp_path):
    src = (
        "import os\n"
        "\n"
        "print(os.getcwd())\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert not plan.ok
    assert not plan.new_contents
    assert not plan.blockers  # no-op, not a failure


def test_used_via_attribute_chain_kept(tmp_path):
    src = (
        "import a.b.c\n"
        "\n"
        "a.b.c.run()\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert not plan.new_contents


def test_asname_binding_used(tmp_path):
    src = (
        "import a.b as c\n"
        "\n"
        "c.run()\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert not plan.new_contents


def test_asname_binding_unused_removed(tmp_path):
    src = (
        "import a.b as c\n"
        "\n"
        "x = 1\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "import a.b as c" not in new
    ast.parse(new)


# ── partial from-import: drop only the unused name ──────────────────────────

def test_partial_from_import(tmp_path):
    src = (
        "from x import a, b\n"
        "\n"
        "print(a)\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "from x import a\n" in new
    assert "b" not in new.split("\n")[0]
    ast.parse(new)


def test_partial_from_import_preserves_order(tmp_path):
    src = (
        "from x import a, b, c\n"
        "\n"
        "print(a, c)\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "from x import a, c\n" in new  # original order, b dropped
    ast.parse(new)


# ── all-unused from-import: whole statement removed ─────────────────────────

def test_all_unused_from_import_removed(tmp_path):
    src = (
        "from x import a, b\n"
        "\n"
        "y = 2\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "from x import" not in new
    assert "y = 2" in new
    ast.parse(new)


# ── __future__ never touched ────────────────────────────────────────────────

def test_future_import_never_touched(tmp_path):
    src = (
        "from __future__ import annotations\n"
        "\n"
        "x = 1\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert not plan.new_contents
    assert not plan.blockers


# ── star import: whole module is a no-op ────────────────────────────────────

def test_star_import_module_noop(tmp_path):
    src = (
        "from x import *\n"
        "import os\n"
        "\n"
        "y = 1\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert not plan.new_contents  # os not removed despite looking unused
    assert not plan.blockers


# ── name kept because it's in __all__ ───────────────────────────────────────

def test_name_kept_via_all(tmp_path):
    src = (
        "from x import helper\n"
        "\n"
        "__all__ = ['helper']\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert not plan.new_contents


def test_partial_kept_via_all(tmp_path):
    src = (
        "from x import a, b\n"
        "\n"
        "__all__ = ['a']\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "from x import a\n" in new  # a exported, b pruned
    ast.parse(new)


# ── multi-line parenthesized from-import ─────────────────────────────────────

def test_multiline_parenthesized_from_import(tmp_path):
    src = (
        "from x import (\n"
        "    a,\n"
        "    b,\n"
        ")\n"
        "\n"
        "print(a)\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "from x import a\n" in new
    assert "print(a)" in new
    ast.parse(new)


def test_multiline_all_unused_removed(tmp_path):
    src = (
        "from x import (\n"
        "    a,\n"
        "    b,\n"
        ")\n"
        "\n"
        "z = 3\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "from x import" not in new
    assert "z = 3" in new
    ast.parse(new)


# ── noqa: left as written ────────────────────────────────────────────────────

def test_noqa_left_alone(tmp_path):
    src = (
        "import os  # noqa\n"
        "\n"
        "x = 1\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert not plan.new_contents


# ── imports inside non-module-body scopes ignored ───────────────────────────

def test_import_inside_function_ignored(tmp_path):
    src = (
        "def f():\n"
        "    import os\n"
        "    return 1\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert not plan.new_contents


def test_import_inside_try_ignored(tmp_path):
    src = (
        "try:\n"
        "    import fast as mod\n"
        "except ImportError:\n"
        "    import slow as mod\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert not plan.new_contents


# ── multiple removals, bottom-up line preservation ──────────────────────────

def test_multiple_removals(tmp_path):
    src = (
        "import os\n"
        "import sys\n"
        "from x import a, b\n"
        "\n"
        "print(sys.argv, a)\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "import os" not in new
    assert "import sys" in new
    assert "from x import a\n" in new
    assert plan.edits_by_file["m.py"] == 2
    ast.parse(new)


# ── clean module: empty plan ─────────────────────────────────────────────────

def test_clean_module_empty_plan(tmp_path):
    src = (
        "import os\n"
        "\n"
        "print(os.getcwd())\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert not plan.ok
    assert not plan.new_contents
    assert not plan.blockers
    assert not plan.edits_by_file


# ── unreadable / unparseable module ─────────────────────────────────────────

def test_missing_module_blocks(tmp_path):
    plan = plan_remove_unused_imports(tmp_path, "nope.py")
    assert not plan.ok
    assert plan.blockers


def test_syntax_error_blocks(tmp_path):
    _write(tmp_path, "bad.py", "import (:\n")
    plan = plan_remove_unused_imports(tmp_path, "bad.py")
    assert not plan.ok
    assert any("doesn't parse" in b for b in plan.blockers)


# ── result always re-parses ─────────────────────────────────────────────────

def test_result_reparses(tmp_path):
    src = (
        "import os\n"
        "import sys\n"
        "from x import a, b, c\n"
        "\n"
        "print(a, c)\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert plan.ok
    ast.parse(plan.new_contents["m.py"])  # never produces broken source


# ── discovery via _py_files in a tmp_path project ───────────────────────────

def test_via_py_files_discovery(tmp_path):
    _write(
        tmp_path, "pkg/mod.py",
        "import os\n"
        "\n"
        "value = 42\n",
    )
    _write(tmp_path, "pkg/__init__.py", "")
    discovered = dict(_py_files(tmp_path))
    assert "pkg/mod.py" in discovered

    plan = plan_remove_unused_imports(tmp_path, "pkg/mod.py")
    assert plan.ok
    new = plan.new_contents["pkg/mod.py"]
    assert "import os" not in new
    ast.parse(new)


# ── local _is_fixture_path mirrors dedup's ──────────────────────────────────

def test_is_fixture_path():
    assert _is_fixture_path("tests/test_x.py")
    assert _is_fixture_path("examples/demo.py")
    assert _is_fixture_path("pkg/test_helper.py")
    assert _is_fixture_path("a/fixtures/b.py")
    assert not _is_fixture_path("app/execution/unused_imports.py")


# ── package __init__.py: re-exports are NEVER pruned ────────────────────────
#
# The buyer-facing trap: a package ``__init__.py`` whose public API is a re-export
# (``from .a import foo``) carrying NO module-level ``__all__``. The name is
# imported but never USED locally, so a path-blind pruner reads it as dead and
# drops the package's public export. A top-level import in ``__init__.py`` is a
# presumptive re-export, so remove-unused-imports must REFUSE the whole file.

def test_init_reexport_without_all_is_refused(tmp_path):
    # from .a import foo, no __all__: foo is the package's public surface. Without
    # the guard this import reads as "unused" and is pruned (the bug); with it the
    # whole __init__.py is refused and the re-export survives.
    _write(tmp_path, "pkg/__init__.py", "from .a import foo\n")
    plan = plan_remove_unused_imports(tmp_path, "pkg/__init__.py")
    assert not plan.ok          # honest no-op, not a failure
    assert not plan.new_contents  # the re-export line is kept verbatim
    assert not plan.blockers
    assert not plan.edits_by_file


def test_init_reexport_with_multiple_names_is_refused(tmp_path):
    # A multi-name re-export with one locally-used and one purely-exported name is
    # STILL refused wholesale — __init__.py is off-limits, never partially pruned.
    _write(
        tmp_path, "pkg/__init__.py",
        "from .a import foo, bar\n"
        "\n"
        "value = foo()\n",  # foo used locally, bar only re-exported
    )
    plan = plan_remove_unused_imports(tmp_path, "pkg/__init__.py")
    assert not plan.new_contents  # bar (the re-export) is not stripped


def test_non_init_module_unused_import_still_pruned(tmp_path):
    # Regression guard: a NON-__init__ module's genuinely-unused ``import os`` is
    # STILL pruned — the guard must not over-refuse ordinary modules.
    _write(
        tmp_path, "pkg/feature.py",
        "import os\n"
        "\n"
        "x = 1\n",
    )
    plan = plan_remove_unused_imports(tmp_path, "pkg/feature.py")
    assert plan.ok
    new = plan.new_contents["pkg/feature.py"]
    assert "import os" not in new
    assert "x = 1" in new
    ast.parse(new)


def test_init_with_explicit_all_still_works(tmp_path):
    # Regression guard: an __init__.py WITH an explicit __all__ was already
    # protected (the exported name is in the keep-set). The new path guard refuses
    # the file outright before that even matters — either way the re-export
    # survives and nothing is pruned. (A truly-dead import alongside it is the rare
    # accepted false-negative — soundness over recall.)
    _write(
        tmp_path, "pkg/__init__.py",
        "from .a import foo\n"
        "import os\n"           # genuinely unused, but __init__ is off-limits
        "\n"
        "__all__ = ['foo']\n",
    )
    plan = plan_remove_unused_imports(tmp_path, "pkg/__init__.py")
    assert not plan.new_contents  # exported foo kept; os left alone (init refused)
    assert not plan.blockers


def test_dunder_init_in_subpackage_is_refused(tmp_path):
    # The guard keys on the basename, so a nested package __init__ is refused too.
    _write(tmp_path, "pkg/sub/__init__.py", "from .impl import api\n")
    plan = plan_remove_unused_imports(tmp_path, "pkg/sub/__init__.py")
    assert not plan.new_contents


def test_is_package_init():
    assert _is_package_init("pkg/__init__.py")
    assert _is_package_init("a/b/c/__init__.py")
    assert _is_package_init("__init__.py")
    assert _is_package_init("pkg\\__init__.py")  # windows separator normalized
    assert not _is_package_init("pkg/module.py")
    assert not _is_package_init("pkg/__main__.py")
    assert not _is_package_init("not_init.py")
