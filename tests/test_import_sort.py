"""Tests for the import-sort transform."""

from __future__ import annotations

import ast

from app.execution.cross_file_rename import _py_files
from app.execution.import_sort import (
    _is_fixture_path,
    plan_sort_imports,
)


def _write(tmp_path, rel, source):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _imported_names(source):
    """The SET of (module, name)-ish tokens imported by ``source`` — order
    independent, so a reorder that preserves meaning compares equal."""
    names: set[tuple] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(("import", alias.name, alias.asname))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(("from", node.level, node.module, alias.name,
                           alias.asname))
    return names


# ── out-of-order stdlib block gets alphabetized ─────────────────────────────

def test_stdlib_block_alphabetized(tmp_path):
    src = (
        "import sys\n"
        "import os\n"
        "import json\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_sort_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert new == "import json\nimport os\nimport sys\n"
    ast.parse(new)
    assert _imported_names(src) == _imported_names(new)


# ── three groups: stdlib / third-party / first-party, blank line between ────

def test_three_groups_split(tmp_path):
    src = (
        "import requests\n"
        "import os\n"
        "from app.engine import core\n"
        "import sys\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_sort_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert new == (
        "import os\n"
        "import sys\n"
        "\n"
        "import requests\n"
        "\n"
        "from app.engine import core\n"
    )
    # Exactly two blank lines (one between each adjacent non-empty group).
    assert new.count("\n\n") == 2
    ast.parse(new)


# ── __future__ left untouched at top and NOT grouped ────────────────────────

def test_future_left_untouched(tmp_path):
    src = (
        "from __future__ import annotations\n"
        "import sys\n"
        "import os\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_sort_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    # __future__ stays first; only the run below it is sorted.
    assert new == (
        "from __future__ import annotations\n"
        "import os\n"
        "import sys\n"
    )
    assert plan.edits_by_file["m.py"] == 2  # only the two sorted imports
    ast.parse(new)


def test_future_with_docstring(tmp_path):
    src = (
        '"""Module."""\n'
        "from __future__ import annotations\n"
        "import sys\n"
        "import os\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_sort_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert new == (
        '"""Module."""\n'
        "from __future__ import annotations\n"
        "import os\n"
        "import sys\n"
    )
    ast.parse(new)


# ── already sorted → no-op ──────────────────────────────────────────────────

def test_already_sorted_noop(tmp_path):
    src = (
        "import json\n"
        "import os\n"
        "import sys\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_sort_imports(tmp_path, "m.py")
    assert not plan.ok
    assert not plan.new_contents
    assert not plan.blockers  # a no-op, not a failure


# ── interleaved comment → aborted no-op ─────────────────────────────────────

def test_interleaved_comment_aborts(tmp_path):
    src = (
        "import sys\n"
        "# a comment between imports\n"
        "import os\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_sort_imports(tmp_path, "m.py")
    assert not plan.ok
    assert not plan.new_contents
    assert not plan.blockers


def test_interleaved_blank_line_aborts(tmp_path):
    src = (
        "import sys\n"
        "\n"
        "import os\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_sort_imports(tmp_path, "m.py")
    assert not plan.new_contents
    assert not plan.blockers


# ── relative import classed first-party ─────────────────────────────────────

def test_relative_import_first_party(tmp_path):
    src = (
        "import os\n"
        "from . import helpers\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_sort_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    # stdlib first, then the relative (first-party) import after a blank line.
    assert new == (
        "import os\n"
        "\n"
        "from . import helpers\n"
    )
    ast.parse(new)


# ── multi-line parenthesized import preserved verbatim ──────────────────────

def test_multiline_parenthesized_preserved(tmp_path):
    src = (
        "import sys\n"
        "from os.path import (\n"
        "    join,\n"
        "    dirname,\n"
        ")\n"
        "import os\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_sort_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    # All stdlib. `import os` and `from os.path import ...` share root key "os",
    # so the original-text tiebreaker orders "from ..." before "import ..."
    # ('f' < 'i'); then "import os" < "import sys". The parenthesized body is
    # reproduced verbatim.
    assert new == (
        "from os.path import (\n"
        "    join,\n"
        "    dirname,\n"
        ")\n"
        "import os\n"
        "import sys\n"
    )
    ast.parse(new)
    assert _imported_names(src) == _imported_names(new)


# ── fewer than 2 imports → no-op ────────────────────────────────────────────

def test_single_import_noop(tmp_path):
    src = "import os\n"
    _write(tmp_path, "m.py", src)
    plan = plan_sort_imports(tmp_path, "m.py")
    assert not plan.ok
    assert not plan.new_contents
    assert not plan.blockers


def test_no_imports_noop(tmp_path):
    src = "x = 1\n"
    _write(tmp_path, "m.py", src)
    plan = plan_sort_imports(tmp_path, "m.py")
    assert not plan.new_contents
    assert not plan.blockers


# ── imported-name set unchanged across the reorder ──────────────────────────

def test_import_set_preserved(tmp_path):
    src = (
        "import requests\n"
        "from app.engine import core, helpers\n"
        "import os\n"
        "from collections import OrderedDict\n"
        "import sys\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_sort_imports(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    ast.parse(new)
    assert _imported_names(src) == _imported_names(new)


# ── unparseable / missing module → blocker ──────────────────────────────────

def test_syntax_error_blocks(tmp_path):
    _write(tmp_path, "bad.py", "import os\nimport (\n")
    plan = plan_sort_imports(tmp_path, "bad.py")
    assert not plan.ok
    assert any("doesn't parse" in b for b in plan.blockers)


def test_missing_module_blocks(tmp_path):
    plan = plan_sort_imports(tmp_path, "nope.py")
    assert not plan.ok
    assert plan.blockers


# ── discovery via _py_files in a tmp_path project ───────────────────────────

def test_via_py_files_discovery(tmp_path):
    _write(
        tmp_path, "pkg/mod.py",
        "import sys\n"
        "import os\n",
    )
    _write(tmp_path, "pkg/__init__.py", "")
    discovered = dict(_py_files(tmp_path))
    assert "pkg/mod.py" in discovered

    plan = plan_sort_imports(tmp_path, "pkg/mod.py")
    assert plan.ok
    new = plan.new_contents["pkg/mod.py"]
    assert new == "import os\nimport sys\n"
    ast.parse(new)


# ── local _is_fixture_path mirrors dedup's ──────────────────────────────────

def test_is_fixture_path():
    assert _is_fixture_path("tests/test_x.py")
    assert _is_fixture_path("examples/demo.py")
    assert _is_fixture_path("pkg/test_helper.py")
    assert _is_fixture_path("a/fixtures/b.py")
    assert not _is_fixture_path("app/execution/import_sort.py")
