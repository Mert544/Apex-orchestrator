"""Residual branch/defensive coverage for the dependency audit.

Complements ``test_dependency_audit.py`` and ``test_dependency_audit_more_edges.py``
by reaching the last few uncovered lines/branches:

  * a ``requirements*.txt`` file that raises on read is skipped (per-file
    defensiveness), the other file still parsed;
  * ``_local_top_packages`` returns empty when ``iterdir`` raises ``OSError``;
  * a hidden / skipped top-level directory is ignored by local-package detection;
  * ``from __future__`` (module present, level 0) and a bare/empty-module import
    node exercise the ``ImportFrom`` branch arms without adding third-party deps.

Deterministic, stdlib-only, LLM-free — every project lives in the tmp tree; the
one read-failure is injected via monkeypatch on ``Path.read_text``, not the OS.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.dependency_audit import (
    _collect_third_party_imports,
    _local_top_packages,
    _parse_requirements,
    _top_level_imports,
    audit_dependencies,
)


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------- #
# _parse_requirements: per-file read failure is swallowed (lines 159-160)
# --------------------------------------------------------------------------- #

def test_requirements_unreadable_file_is_skipped(tmp_path, monkeypatch):
    _write(tmp_path, "requirements.txt", "requests>=2\n")
    _write(tmp_path, "requirements-dev.txt", "rich>=13\n")

    real_read_text = Path.read_text

    def boom(self, *args, **kwargs):
        if self.name == "requirements.txt":
            raise OSError("simulated unreadable file")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", boom)

    out = _parse_requirements(tmp_path)
    names = [name for name, _ in out if name]
    # requirements.txt failed to read -> only requirements-dev.txt contributes.
    assert "rich" in names
    assert "requests" not in names


# --------------------------------------------------------------------------- #
# _local_top_packages: iterdir OSError -> empty (lines 174-175)
# --------------------------------------------------------------------------- #

def test_local_top_packages_iterdir_oserror_returns_empty(tmp_path, monkeypatch):
    def boom(self):
        raise OSError("simulated iterdir failure")

    monkeypatch.setattr(Path, "iterdir", boom)
    assert _local_top_packages(tmp_path) == set()


# --------------------------------------------------------------------------- #
# hidden / skipped top-level dir is ignored (line 179)
# --------------------------------------------------------------------------- #

def test_hidden_top_level_dir_is_not_local(tmp_path):
    # A dotted dir holding an __init__.py would normally register as local, but
    # the leading "." makes it skipped before that check.
    _write(tmp_path, ".hidden_pkg/__init__.py", "")
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/core.py", "x = 1\n")

    local = _local_top_packages(tmp_path)
    assert ".hidden_pkg" not in local
    assert "hidden_pkg" not in local
    assert "app" in local


def test_skipped_dir_name_is_ignored(tmp_path):
    # A conventionally-skipped dir name (e.g. __pycache__) is dropped even though
    # it might contain .py files.
    _write(tmp_path, "__pycache__/stale.py", "y = 1\n")
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/core.py", "x = 1\n")

    local = _local_top_packages(tmp_path)
    assert "__pycache__" not in local


# --------------------------------------------------------------------------- #
# _top_level_imports: ImportFrom branch arms (206->204, 211->202, 213->202)
# --------------------------------------------------------------------------- #

def test_import_from_future_module_present_level_zero():
    # `from __future__ import annotations` -> module present, level 0 -> recorded.
    tree = ast.parse("from __future__ import annotations\n")
    names = _top_level_imports(tree)
    assert "__future__" in names


def test_import_from_with_no_module_is_skipped():
    # `from . import x` has node.module == None and level > 0 -> skipped entirely.
    tree = ast.parse("from . import sibling\n")
    names = _top_level_imports(tree)
    assert names == set()


def test_import_from_level_zero_no_module_records_nothing():
    # Construct a level-0 ImportFrom with module=None directly (rare; e.g. a
    # synthesized node). The `if node.module` guard (213->202) drops it.
    node = ast.ImportFrom(module=None, names=[ast.alias(name="x", asname=None)], level=0)
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    names = _top_level_imports(module)
    assert names == set()


def test_plain_import_records_top_level():
    tree = ast.parse("import os.path\nimport requests\n")
    names = _top_level_imports(tree)
    assert "os" in names
    assert "requests" in names


def test_import_alias_with_empty_top_is_dropped():
    # A synthesized `import .x`-style alias whose name splits to an empty top
    # (alias.name == ".") exercises the `if top:` guard's false arm (206->204).
    node = ast.Import(names=[ast.alias(name=".", asname=None)])
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    assert _top_level_imports(module) == set()


def test_import_from_empty_module_top_is_dropped():
    # A level-0 ImportFrom whose module splits to an empty top (module == ".")
    # exercises the inner `if top:` false arm (213->202).
    node = ast.ImportFrom(
        module=".", names=[ast.alias(name="x", asname=None)], level=0
    )
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    assert _top_level_imports(module) == set()


# --------------------------------------------------------------------------- #
# integration: third-party collection excludes __future__ and stdlib
# --------------------------------------------------------------------------- #

def test_collect_excludes_future_and_stdlib(tmp_path):
    _write(tmp_path, "app/__init__.py", "")
    _write(
        tmp_path, "app/core.py",
        "from __future__ import annotations\n"
        "import os\nimport sys\nimport requests\n",
    )
    third = _collect_third_party_imports(tmp_path)
    assert third == {"requests"}


def test_audit_with_future_import_only_is_clean(tmp_path):
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/core.py", "from __future__ import annotations\nx = 1\n")
    f = audit_dependencies(str(tmp_path))
    assert f.imported_third_party == []
    assert f.undeclared == []
