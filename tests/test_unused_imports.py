"""Tests for the remove-unused-imports transform."""

from __future__ import annotations

import ast

from app.execution.cross_file_rename import _py_files
from app.execution.unused_imports import (
    _is_fixture_path,
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
