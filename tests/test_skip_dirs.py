"""Tests for the canonical tree-walk exclusion set."""

from __future__ import annotations

from pathlib import Path

from app.engine.skip_dirs import (
    SKIPPED_DIRS,
    is_skipped,
    is_test_or_fixture_name,
    is_test_or_fixture_path,
    iter_source_files,
    module_dotted_name,
)


def test_claude_worktrees_are_skipped():
    # The omission that bit Apex three times: agent worktrees under .claude/.
    assert ".claude" in SKIPPED_DIRS
    assert is_skipped(".claude/worktrees/agent-1/app/engine/foo.py")
    assert is_skipped(Path("x/.claude/y/test_foo.py"))


def test_real_source_is_kept():
    assert not is_skipped("app/engine/foo.py")
    assert not is_skipped("tests/test_foo.py")
    assert not is_skipped(Path("scripts/verify.py"))


def test_caches_venvs_and_build_output_skipped():
    for d in (".git", "__pycache__", ".apex", ".epistemic",
              ".venv", "venv", "node_modules", "dist", "build"):
        assert is_skipped(f"{d}/x.py"), d
        assert d in SKIPPED_DIRS


def test_skip_is_a_whole_component_match_not_substring():
    # A file whose NAME merely contains a skipped token is not a directory match.
    assert not is_skipped("app/buildings.py")    # 'build' is a substring, not a part
    assert not is_skipped("app/distance.py")     # 'dist' is a substring, not a part
    assert not is_skipped("app/venv_helper.py")  # 'venv' is a substring, not a part


def test_iter_source_files_excludes_worktrees(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "real.py").write_text("x = 1\n", encoding="utf-8")
    wt = tmp_path / ".claude" / "worktrees" / "agent-1" / "app"
    wt.mkdir(parents=True)
    (wt / "copy.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "c.py").write_text("x = 1\n", encoding="utf-8")

    found = [p.relative_to(tmp_path).as_posix() for p in iter_source_files(tmp_path)]
    assert found == ["app/real.py"]  # sorted, worktree + cache excluded


def test_iter_source_files_is_sorted_and_deterministic(tmp_path):
    (tmp_path / "app").mkdir()
    for name in ("c.py", "a.py", "b.py"):
        (tmp_path / "app" / name).write_text("x = 1\n", encoding="utf-8")
    a = [p.name for p in iter_source_files(tmp_path)]
    b = [p.name for p in iter_source_files(tmp_path)]
    assert a == b == ["a.py", "b.py", "c.py"]


# --- shared path-classification helpers (consolidated from app/tools/*) --------


def test_is_test_or_fixture_path_markers_and_skipset():
    # Honours the canonical skip-set in addition to test/fixture conventions.
    assert is_test_or_fixture_path(Path("tests/test_a.py"))
    assert is_test_or_fixture_path(Path("a/fixtures/b.py"))
    assert is_test_or_fixture_path(Path("a/fixture/b.py"))
    assert is_test_or_fixture_path(Path("testdata/x.py"))
    assert is_test_or_fixture_path(Path("foo/conftest.py"))
    assert is_test_or_fixture_path(Path("bar_test.py"))
    assert is_test_or_fixture_path(Path("pkg/baz_test.py"))
    assert is_test_or_fixture_path(Path(".claude/wt/app/x.py"))  # via is_skipped
    assert is_test_or_fixture_path(Path("app/test_thing.py"))
    # Case-sensitive on directory markers; plain modules are not test code.
    assert not is_test_or_fixture_path(Path("app/x.py"))
    assert not is_test_or_fixture_path(Path("TESTS/Foo.py"))
    assert not is_test_or_fixture_path(Path("Test_X.py"))
    assert not is_test_or_fixture_path(Path("plain.py"))


def test_is_test_or_fixture_name_is_case_insensitive_and_ignores_skipset():
    # Lowercases directory markers and the stem/name; does NOT consult is_skipped.
    assert is_test_or_fixture_name(Path("tests/test_a.py"))
    assert is_test_or_fixture_name(Path("TESTS/Foo.py"))          # case-insensitive
    assert is_test_or_fixture_name(Path("b/Fixtures/c.py"))
    assert is_test_or_fixture_name(Path("Test_X.py"))             # lowered stem
    assert is_test_or_fixture_name(Path("pkg/baz_test.py"))
    assert is_test_or_fixture_name(Path("foo/conftest.py"))
    # No skip-set consultation: a .claude worktree copy is NOT flagged by name.
    assert not is_test_or_fixture_name(Path(".claude/wt/app/x.py"))
    assert not is_test_or_fixture_name(Path("testdata/x.py"))     # not a marker dir
    assert not is_test_or_fixture_name(Path("app/x.py"))
    assert not is_test_or_fixture_name(Path("plain.py"))


def test_module_dotted_name_relative_fallback_and_extension():
    assert module_dotted_name(Path("app/x.py"), Path(".")) == "app.x"
    assert module_dotted_name(Path("app/sub/mod.py"), Path(".")) == "app.sub.mod"
    assert module_dotted_name(Path("/r/app/x.py"), Path("/r")) == "app.x"
    # No .py suffix: extension stripping is a no-op.
    assert module_dotted_name(Path("app/x.txt"), Path(".")) == "app.x.txt"
    # Outside root: falls back to the bare path.
    assert module_dotted_name(Path("outside/y.py"), Path("/r")) == "outside.y"
