from pathlib import Path

from app.engine.blast_radius import (
    BlastRadius,
    blast_radius,
    changed_from_git,
    is_skipped,
    render_blast_radius_markdown,
)


def _make_chain(root: Path) -> None:
    """Plant a synthetic project: app.a -> app.b -> app.c import chain + a test.

    Also plants a .claude worktree COPY that imports app.c, to assert it is
    excluded from every result.
    """
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / ".claude" / "worktrees" / "wt" / "app").mkdir(parents=True)

    (root / "app" / "a.py").write_text("import app.b\n", encoding="utf-8")
    (root / "app" / "b.py").write_text("import app.c\n", encoding="utf-8")
    (root / "app" / "c.py").write_text("def c():\n    return 1\n", encoding="utf-8")
    (root / "tests" / "test_c.py").write_text(
        "from app.c import c\n\n\ndef test_c():\n    assert c() == 1\n",
        encoding="utf-8",
    )
    # A full-repo worktree copy: it imports app.c but must never count.
    (root / ".claude" / "worktrees" / "wt" / "app" / "copy.py").write_text(
        "import app.c\n", encoding="utf-8"
    )


def test_direct_vs_transitive_dependents_sorted(tmp_path: Path):
    _make_chain(tmp_path)
    br = blast_radius(tmp_path, ["app/c.py"])

    # b imports c directly; the covering test imports c directly.
    assert br.direct_dependents == ["app/b.py", "tests/test_c.py"]
    # a reaches c transitively (a -> b -> c); the full reachable set is a, b, test.
    assert br.transitive_dependents == ["app/a.py", "app/b.py", "tests/test_c.py"]
    # Both lists are sorted and exclude the changed module itself.
    assert "app/c.py" not in br.direct_dependents
    assert "app/c.py" not in br.transitive_dependents
    assert br.direct_dependents == sorted(br.direct_dependents)
    assert br.transitive_dependents == sorted(br.transitive_dependents)


def test_covering_tests_found(tmp_path: Path):
    _make_chain(tmp_path)
    br = blast_radius(tmp_path, ["app/c.py"])
    assert br.covering_tests == ["tests/test_c.py"]


def test_changed_test_file_is_its_own_covering_test(tmp_path: Path):
    _make_chain(tmp_path)
    br = blast_radius(tmp_path, ["tests/test_c.py"])
    # A changed test file is always part of its own covering scope.
    assert "tests/test_c.py" in br.covering_tests


def test_worktree_copy_is_ignored(tmp_path: Path):
    _make_chain(tmp_path)
    br = blast_radius(tmp_path, ["app/c.py"])
    copy = ".claude/worktrees/wt/app/copy.py"
    # The planted .claude worktree copy imports app.c but must never appear.
    assert copy not in br.direct_dependents
    assert copy not in br.transitive_dependents
    assert copy not in br.covering_tests
    assert all(not p.startswith(".claude/") for p in br.direct_dependents)
    assert all(not p.startswith(".claude/") for p in br.transitive_dependents)


def test_cohesion_tight_same_package(tmp_path: Path):
    _make_chain(tmp_path)
    br = blast_radius(tmp_path, ["app/a.py", "app/b.py"])
    assert br.cohesion is not None
    assert br.cohesion.label == "tight"
    assert br.cohesion.score == 1.0
    assert "share package 'app'" in br.cohesion.reason


def test_cohesion_tight_connected_by_imports(tmp_path: Path):
    # Two modules in DIFFERENT packages but joined by a direct import edge.
    (tmp_path / "pkg1").mkdir()
    (tmp_path / "pkg2").mkdir()
    (tmp_path / "pkg1" / "a.py").write_text("import pkg2.b\n", encoding="utf-8")
    (tmp_path / "pkg2" / "b.py").write_text("def b():\n    return 1\n", encoding="utf-8")

    br = blast_radius(tmp_path, ["pkg1/a.py", "pkg2/b.py"])
    assert br.cohesion is not None
    assert br.cohesion.label == "tight"
    assert br.cohesion.score == 1.0
    assert "connected by direct imports" in br.cohesion.reason


def test_cohesion_scattered_unrelated(tmp_path: Path):
    # Two unrelated top-level packages: no shared prefix, no import edge.
    (tmp_path / "api").mkdir()
    (tmp_path / "lib").mkdir()
    (tmp_path / "api" / "handler.py").write_text("def h():\n    return 1\n", encoding="utf-8")
    (tmp_path / "lib" / "util.py").write_text("def u():\n    return 2\n", encoding="utf-8")

    br = blast_radius(tmp_path, ["api/handler.py", "lib/util.py"])
    assert br.cohesion is not None
    assert br.cohesion.label == "scattered"
    assert br.cohesion.score == 0.0
    assert "scope creep" in br.cohesion.reason


def test_cohesion_partial_prefix_score(tmp_path: Path):
    # 3 modules, 2 under app/api and 1 under app/db: shared prefix is "app",
    # all 3 are under it -> score 1.0 (tight) by the common-prefix fraction rule.
    (tmp_path / "app" / "api").mkdir(parents=True)
    (tmp_path / "app" / "db").mkdir(parents=True)
    (tmp_path / "app" / "api" / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (tmp_path / "app" / "api" / "b.py").write_text("def b():\n    return 2\n", encoding="utf-8")
    (tmp_path / "app" / "db" / "c.py").write_text("def c():\n    return 3\n", encoding="utf-8")

    br = blast_radius(tmp_path, ["app/api/a.py", "app/api/b.py", "app/db/c.py"])
    assert br.cohesion is not None
    # Different packages, no import edges -> falls through to the common-prefix
    # rule; all 3 share prefix "app", so the fraction is 3/3 = 1.0 -> tight.
    assert br.cohesion.label == "tight"
    assert br.cohesion.score == 1.0
    assert "common prefix 'app'" in br.cohesion.reason


def test_empty_change(tmp_path: Path):
    _make_chain(tmp_path)
    br = blast_radius(tmp_path, [])
    assert br.changed == []
    assert br.direct_dependents == []
    assert br.transitive_dependents == []
    assert br.covering_tests == []
    # An empty change is cohesive by definition (the <=1 module rule).
    assert br.cohesion is not None
    assert br.cohesion.label == "tight"


def test_unresolvable_changed_path_is_skipped_not_guessed(tmp_path: Path):
    _make_chain(tmp_path)
    # A path that isn't a graph node contributes no dependents.
    br = blast_radius(tmp_path, ["app/does_not_exist.py"])
    assert br.changed == ["app/does_not_exist.py"]
    assert br.direct_dependents == []
    assert br.transitive_dependents == []


def test_skipped_changed_path_dropped(tmp_path: Path):
    _make_chain(tmp_path)
    # A changed path inside a skipped dir is dropped from the changed set itself.
    br = blast_radius(tmp_path, [".claude/worktrees/wt/app/copy.py", "app/c.py"])
    assert br.changed == ["app/c.py"]


def test_determinism_same_input_same_output(tmp_path: Path):
    _make_chain(tmp_path)
    first = blast_radius(tmp_path, ["app/c.py"]).to_dict()
    second = blast_radius(tmp_path, ["app/c.py"]).to_dict()
    assert first == second


def test_to_dict_shape(tmp_path: Path):
    _make_chain(tmp_path)
    d = blast_radius(tmp_path, ["app/c.py"]).to_dict()
    assert set(d) == {
        "changed",
        "direct_dependents",
        "transitive_dependents",
        "covering_tests",
        "cohesion",
    }
    assert set(d["cohesion"]) == {"score", "label", "reason"}


def test_render_markdown_contains_sections_and_verdict(tmp_path: Path):
    _make_chain(tmp_path)
    md = render_blast_radius_markdown(blast_radius(tmp_path, ["app/c.py"]))
    assert "# Change Blast Radius" in md
    assert "| Dimension | Count |" in md
    assert "## Direct dependents" in md
    assert "## Covering tests" in md
    assert "## Scope cohesion" in md
    assert "`app/b.py`" in md
    assert "tight" in md


def test_render_markdown_empty(tmp_path: Path):
    md = render_blast_radius_markdown(BlastRadius())
    assert "_No changed modules._" in md


def test_is_skipped():
    assert is_skipped(".claude/worktrees/wt/app/copy.py")
    assert is_skipped("app/__pycache__/x.py")
    assert not is_skipped("app/engine/blast_radius.py")
    assert not is_skipped(Path("tests/test_c.py"))


def test_changed_from_git_non_repo_returns_empty(tmp_path: Path):
    # Not a git repo -> conservative empty, never raises.
    assert changed_from_git(tmp_path) == []


def test_changed_from_git_filters_to_unskipped_py(tmp_path: Path, monkeypatch):
    import subprocess as _sp

    class _Proc:
        returncode = 0
        stdout = (
            "app/c.py\n"
            "README.md\n"
            ".claude/worktrees/wt/app/copy.py\n"
            "app/__pycache__/c.cpython.pyc\n"
            "app/b.py\n"
        )

    def _fake_run(*args, **kwargs):
        return _Proc()

    monkeypatch.setattr(_sp, "run", _fake_run)
    out = changed_from_git(tmp_path)
    # Only project .py files that survive is_skipped, sorted, de-duplicated.
    assert out == ["app/b.py", "app/c.py"]


def test_changed_from_git_failure_returns_empty(tmp_path: Path, monkeypatch):
    import subprocess as _sp

    class _Proc:
        returncode = 128
        stdout = "app/c.py\n"

    monkeypatch.setattr(_sp, "run", lambda *a, **k: _Proc())
    assert changed_from_git(tmp_path) == []
