"""Tests for the deterministic source index (parse-once project view)."""

from __future__ import annotations

import os
from pathlib import Path

from app.engine.source_index import (
    IndexedModule,
    SourceIndex,
    _is_fixture_path,
    indexed_project,
)


def _make_project(root: Path) -> None:
    """A small synthetic project: own modules, a fixture tree, and a test file."""
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (root / "pkg" / "b.py").write_text("VALUE = 2\n", encoding="utf-8")
    # A syntactically broken own module — indexed, but tree is None.
    (root / "broken.py").write_text("def oops(:\n", encoding="utf-8")
    # Fixtures / tests that must be excluded.
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (root / "examples").mkdir()
    (root / "examples" / "demo.py").write_text("x = 1\n", encoding="utf-8")
    # A top-level module starting with test_ is also a fixture.
    (root / "test_top.py").write_text("y = 1\n", encoding="utf-8")


def test_build_indexes_own_modules_and_excludes_fixtures(tmp_path: Path) -> None:
    _make_project(tmp_path)
    index = SourceIndex.build(tmp_path)

    rels = [m.rel for m in index.modules]
    assert rels == ["broken.py", "pkg/a.py", "pkg/b.py"]  # sorted, fixtures excluded

    # Excluded paths are not present.
    assert index.get("tests/test_a.py") is None
    assert index.get("examples/demo.py") is None
    assert index.get("test_top.py") is None


def test_broken_module_is_indexed_unparsed(tmp_path: Path) -> None:
    _make_project(tmp_path)
    index = SourceIndex.build(tmp_path)

    broken = index.get("broken.py")
    assert isinstance(broken, IndexedModule)
    assert broken.tree is None
    assert broken.parsed is False
    # It still carries its source.
    assert "oops" in broken.source

    good = index.get("pkg/a.py")
    assert good is not None
    assert good.tree is not None
    assert good.parsed is True


def test_own_sources_and_parsed_modules_and_get(tmp_path: Path) -> None:
    _make_project(tmp_path)
    index = SourceIndex.build(tmp_path)

    assert index.own_sources() == [
        ("broken.py", "def oops(:\n"),
        ("pkg/a.py", "def a():\n    return 1\n"),
        ("pkg/b.py", "VALUE = 2\n"),
    ]

    parsed = [m.rel for m in index.parsed_modules()]
    assert parsed == ["pkg/a.py", "pkg/b.py"]  # broken excluded, sorted

    assert index.get("pkg/b.py").source == "VALUE = 2\n"
    assert index.get("does/not/exist.py") is None


def test_build_is_deterministic(tmp_path: Path) -> None:
    _make_project(tmp_path)
    first = SourceIndex.build(tmp_path)
    second = SourceIndex.build(tmp_path)
    assert first.own_sources() == second.own_sources()


def test_empty_project_builds_empty_index(tmp_path: Path) -> None:
    index = SourceIndex.build(tmp_path)
    assert index.modules == []
    assert index.own_sources() == []
    assert index.parsed_modules() == []
    assert index.get("anything.py") is None


def test_is_fixture_path_classification() -> None:
    assert _is_fixture_path("tests/test_a.py")
    assert _is_fixture_path("examples/demo.py")
    assert _is_fixture_path("pkg/tests/helper.py")
    assert _is_fixture_path("test_top.py")
    assert _is_fixture_path("fixtures/data.py")
    assert not _is_fixture_path("pkg/a.py")
    assert not _is_fixture_path("app/engine/source_index.py")


def test_indexed_project_caches_same_object(tmp_path: Path) -> None:
    _make_project(tmp_path)
    first = indexed_project(tmp_path)
    second = indexed_project(tmp_path)
    assert first is second  # cached: fingerprint unchanged


def test_indexed_project_fresh_rebuilds(tmp_path: Path) -> None:
    _make_project(tmp_path)
    first = indexed_project(tmp_path)
    rebuilt = indexed_project(tmp_path, fresh=True)
    assert rebuilt is not first
    # The fresh build is now the cached one.
    assert indexed_project(tmp_path) is rebuilt


def test_indexed_project_rebuilds_after_edit(tmp_path: Path) -> None:
    _make_project(tmp_path)
    first = indexed_project(tmp_path)

    # Edit a module with a bumped mtime so the fingerprint changes.
    target = tmp_path / "pkg" / "a.py"
    target.write_text("def a():\n    return 99\n", encoding="utf-8")
    st = target.stat()
    os.utime(target, (st.st_atime, st.st_mtime + 10))

    second = indexed_project(tmp_path)
    assert second is not first
    assert second.get("pkg/a.py").source == "def a():\n    return 99\n"


def test_indexed_project_rebuilds_when_file_added(tmp_path: Path) -> None:
    _make_project(tmp_path)
    first = indexed_project(tmp_path)

    (tmp_path / "pkg" / "c.py").write_text("Z = 3\n", encoding="utf-8")
    second = indexed_project(tmp_path)
    assert second is not first
    assert second.get("pkg/c.py") is not None


def test_indexed_project_keys_by_resolved_root(tmp_path: Path) -> None:
    _make_project(tmp_path)
    direct = indexed_project(tmp_path)
    # A non-normalized path to the same root resolves to the same cache entry.
    via_dot = indexed_project(tmp_path / "pkg" / "..")
    assert direct is via_dot
