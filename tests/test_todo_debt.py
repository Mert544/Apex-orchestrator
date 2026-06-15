from __future__ import annotations

from app.tools.todo_debt import MARKERS, TodoDebt, analyze_todo_debt


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_detects_markers_in_comments_with_marker_and_line(tmp_path):
    _write(
        tmp_path,
        "a.py",
        "# TODO: handle empty case\n"          # line 1
        "x = 1  # FIXME race here\n"            # line 2
        "def f():\n"                            # line 3
        "    pass  # HACK works for now\n",     # line 4
    )
    debt = analyze_todo_debt(tmp_path)
    assert isinstance(debt, TodoDebt)
    assert debt.total == 3
    assert debt.by_marker["TODO"] == 1
    assert debt.by_marker["FIXME"] == 1
    assert debt.by_marker["HACK"] == 1
    by_line = {it["line"]: it for it in debt.items}
    assert by_line[1]["marker"] == "TODO"
    assert by_line[2]["marker"] == "FIXME"
    assert by_line[4]["marker"] == "HACK"
    assert by_line[1]["module"] == "a.py"
    assert "TODO" in by_line[1]["text"]


def test_marker_inside_identifier_or_word_not_matched(tmp_path):
    # TODONT is a single word: \bTODO\b must NOT fire; same for an identifier
    # use and a lowercase spelling (markers are case-sensitive).
    _write(
        tmp_path,
        "ident.py",
        "TODONT = 1  # see TODONT note\n"   # 'TODONT' contains TODO but no boundary
        "todo_list = []               \n"   # lowercase identifier, not a marker
        "todo = 'fix me'              \n",   # lowercase 'todo' string content
    )
    debt = analyze_todo_debt(tmp_path)
    assert debt.total == 0
    assert debt.items == []
    assert debt.by_marker["TODO"] == 0


def test_non_marker_comments_ignored(tmp_path):
    _write(
        tmp_path,
        "clean.py",
        "# just a normal comment\n"
        "x = 1  # nothing to see here\n"
        "def f():\n"
        "    return x  # plain note\n",
    )
    debt = analyze_todo_debt(tmp_path)
    assert debt.total == 0
    assert all(count == 0 for count in debt.by_marker.values())
    # Every known marker still has a key (zero when absent).
    assert set(debt.by_marker) == set(MARKERS)


def test_markers_in_string_literals_detected(tmp_path):
    _write(
        tmp_path,
        "s.py",
        '"""Module docstring with a XXX marker."""\n'
        "msg = 'BUG: this can fail'\n",
    )
    debt = analyze_todo_debt(tmp_path)
    assert debt.total == 2
    assert debt.by_marker["XXX"] == 1
    assert debt.by_marker["BUG"] == 1


def test_empty_project_is_safe(tmp_path):
    debt = analyze_todo_debt(tmp_path)
    assert debt.total == 0
    assert debt.items == []
    assert debt.by_marker == {m: 0 for m in MARKERS}
    assert debt.to_dict() == {
        "total": 0,
        "by_marker": {m: 0 for m in MARKERS},
        "items": [],
    }


def test_tests_and_fixtures_excluded(tmp_path):
    # The project's own debt census must skip test/fixture trees: their markers
    # are intentional and would otherwise pollute the tally.
    _write(tmp_path, "app/real.py", "# TODO: real debt\n")
    _write(tmp_path, "tests/test_thing.py", "# FIXME: in a test, excluded\n")
    _write(tmp_path, "fixtures/sample.py", "# HACK: a fixture, excluded\n")
    _write(tmp_path, "pkg/test_helper.py", "# XXX: test_ prefixed, excluded\n")
    _write(tmp_path, "conftest.py", "# BUG: conftest, excluded\n")
    debt = analyze_todo_debt(tmp_path)
    assert debt.total == 1
    assert debt.by_marker["TODO"] == 1
    assert debt.items[0]["module"] == "app/real.py"


def test_skipped_dirs_excluded(tmp_path):
    # Worktrees/caches/vendored trees never contribute to the census.
    _write(tmp_path, "keep.py", "# TODO: keep me\n")
    _write(tmp_path, ".claude/worktrees/agent/copy.py", "# TODO: worktree copy\n")
    _write(tmp_path, "node_modules/pkg/x.py", "# FIXME: vendored\n")
    debt = analyze_todo_debt(tmp_path)
    assert debt.total == 1
    assert debt.items[0]["module"] == "keep.py"


def test_deterministic_default_path(tmp_path):
    _write(tmp_path, "b.py", "# FIXME: second file marker\n")
    _write(tmp_path, "a.py", "# TODO: first file marker\nx = 1  # BUG here\n")
    first = analyze_todo_debt(tmp_path)
    second = analyze_todo_debt(tmp_path)
    assert first.to_dict() == second.to_dict()
    # Sorted by (module, line, marker): a.py before b.py.
    modules = [it["module"] for it in first.items]
    assert modules == sorted(modules)
    assert modules[0] == "a.py"


def test_items_capped_but_total_complete(tmp_path):
    # Many markers: total counts all, items head stays bounded (~20).
    body = "".join(f"x{i} = 1  # TODO: marker {i}\n" for i in range(50))
    _write(tmp_path, "many.py", body)
    debt = analyze_todo_debt(tmp_path)
    assert debt.total == 50
    assert debt.by_marker["TODO"] == 50
    assert len(debt.items) <= 20


def test_max_files_zero_yields_empty(tmp_path):
    _write(tmp_path, "a.py", "# TODO: ignored under max_files=0\n")
    debt = analyze_todo_debt(tmp_path, max_files=0)
    assert debt.total == 0
    assert debt.items == []


def test_unparseable_file_does_not_crash(tmp_path):
    # A file tokenize chokes on must not abort the whole census.
    _write(tmp_path, "broken.py", "def oops(:\n    # TODO: in broken file\n")
    _write(tmp_path, "ok.py", "# FIXME: in a good file\n")
    debt = analyze_todo_debt(tmp_path)
    # The good file is still counted regardless of the broken one.
    assert debt.by_marker["FIXME"] == 1


def test_default_path_makes_no_git_calls(tmp_path, monkeypatch):
    # with_age=False is deterministic and offline: no subprocess at all.
    import app.tools.todo_debt as mod

    def _boom(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("subprocess invoked on the default path")

    monkeypatch.setattr(mod.subprocess, "run", _boom)
    _write(tmp_path, "a.py", "# TODO: no blame should run\n")
    debt = analyze_todo_debt(tmp_path)
    assert debt.total == 1
    assert "age_days" not in debt.items[0]


def test_with_age_non_git_omits_age_and_never_crashes(tmp_path):
    # A non-git target is best-effort: age is simply absent, no exception.
    _write(tmp_path, "a.py", "# TODO: aged, but not a repo\n")
    debt = analyze_todo_debt(tmp_path, with_age=True)
    assert debt.total == 1
    assert "age_days" not in debt.items[0]
