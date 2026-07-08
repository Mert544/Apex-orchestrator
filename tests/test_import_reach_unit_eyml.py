"""Unit tests for :mod:`app.engine.import_reach` — the project import graph
behind covering-scope reachability. The behavioral (end-to-end) contract lives
in ``test_covering_scope_reachability_eyml.py``; these pin the graph edges and
the honest-degrade paths directly.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.import_reach import (
    _absolute_imports,
    _from_target,
    reaching_import_names,
)


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- reaching_import_names -----------------------------------------------------

def test_exact_names_include_transitive_importer(tmp_path):
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/_impl.py", "X = 1\n")
    _write(tmp_path, "pkg/api.py", "from pkg._impl import X\n")
    exact, prefixes = reaching_import_names(tmp_path, "pkg/_impl.py")
    assert "pkg.api" in exact and "pkg._impl" in exact


def test_package_prefixes_cover_unparseable_descendants(tmp_path):
    # A package __init__ is executed by importing ANY name under the package —
    # even one the graph cannot index (a compiled extension, a typo). The
    # prefix rule is the belt to the graph's suspenders.
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/mod.py", "Y = 2\n")
    exact, prefixes = reaching_import_names(tmp_path, "pkg/__init__.py")
    assert "pkg." in prefixes


def test_star_import_resolves_to_the_package(tmp_path):
    # ``from pkg.sub import *`` executes pkg/sub/__init__.py; the ``*`` member
    # must not break resolution of the package edge.
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/sub/__init__.py", "Z = 3\n")
    _write(tmp_path, "pkg/consumer.py", "from pkg.sub import *  # noqa: F403\n")
    exact, _ = reaching_import_names(tmp_path, "pkg/sub/__init__.py")
    assert "pkg.consumer" in exact


def test_repo_root_init_never_crashes_the_graph(tmp_path):
    # A repo-root ``__init__.py`` has an EMPTY dotted path (no import name at
    # all). The graph build walks every project file, so it must skip such a
    # file instead of crashing on its empty name list — found live: the
    # verify-budget fixtures carry exactly this shape and the first graph
    # build raised IndexError on them.
    _write(tmp_path, "__init__.py", "")
    _write(tmp_path, "alpha.py", "A = 1\n")
    _write(tmp_path, "bravo.py", "import alpha\n")
    exact, prefixes = reaching_import_names(tmp_path, "alpha.py")
    assert "bravo" in exact  # the real edges still resolve


def test_unparseable_importer_degrades_to_ancestor_edges_only(tmp_path):
    # A module that fails to parse contributes no import edges (its imports are
    # invisible), but its POSITION still counts: importing it executes its
    # ancestor __init__, so it must appear in the ancestor's reach set.
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/broken.py", "def broken(:\n")
    _write(tmp_path, "pkg/target.py", "T = 4\n")
    exact_init, _ = reaching_import_names(tmp_path, "pkg/__init__.py")
    assert "pkg.broken" in exact_init  # position edge survives the parse error
    exact_target, _ = reaching_import_names(tmp_path, "pkg/target.py")
    assert "pkg.broken" not in exact_target  # no invented import edge


# --- _from_target: relative-import resolution -----------------------------------

def test_from_target_resolves_single_dot():
    node = ast.parse("from . import x").body[0]
    assert _from_target(node, ["pkg", "sub"]) == "pkg.sub"


def test_from_target_resolves_dotted_module():
    node = ast.parse("from .mod2 import z").body[0]
    assert _from_target(node, ["pkg", "sub"]) == "pkg.sub.mod2"


def test_from_target_resolves_double_dot():
    node = ast.parse("from ..other import y").body[0]
    assert _from_target(node, ["pkg", "sub"]) == "pkg.other"


def test_from_target_refuses_escape_past_top():
    # ``from ... import y`` inside a two-deep package escapes the project top:
    # a broken import at runtime, so the honest degrade is NO edge, not a guess.
    node = ast.parse("from ...nowhere import y").body[0]
    assert _from_target(node, ["pkg"]) is None


def test_absolute_imports_records_source_and_member():
    tree = ast.parse("from a.b import c\nimport d.e\n")
    names = _absolute_imports(tree, "pkg.mod", is_pkg=False)
    assert {"a.b", "a.b.c", "d.e"} <= names
