"""Tests for the convention-based, NO-execution TEST-PRESENCE heuristic that
sharpens Apex's polyglot facts: a big, active, NON-Python file with no test is
the highest-leverage out-of-scope risk, so ``FileFact.has_test`` makes it
visible and ``render_polyglot_attention`` flags it with "(no test found)".
"""

from pathlib import Path

from app.tools.polyglot_facts import (
    FileFact,
    render_polyglot_attention,
    scan_polyglot_facts,
)


def _write(path: Path, text: str = "x = 1;\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_sibling_dot_test_convention_marks_has_test(tmp_path: Path):
    _write(tmp_path / "src" / "app.js")
    _write(tmp_path / "src" / "app.test.js")
    by_path = {f.path: f for f in scan_polyglot_facts(str(tmp_path))}
    assert by_path["src/app.js"].has_test is True


def test_untested_file_has_test_false(tmp_path: Path):
    _write(tmp_path / "web" / "util.js")
    by_path = {f.path: f for f in scan_polyglot_facts(str(tmp_path))}
    assert by_path["web/util.js"].has_test is False


def test_underscore_test_and_test_prefix_conventions(tmp_path: Path):
    _write(tmp_path / "lib" / "parser.go")
    _write(tmp_path / "lib" / "parser_test.go")
    _write(tmp_path / "pkg" / "client.py")  # python ignored, just here as noise
    _write(tmp_path / "ui" / "widget.ts")
    _write(tmp_path / "ui" / "test_widget.ts")
    by_path = {f.path: f for f in scan_polyglot_facts(str(tmp_path))}
    assert by_path["lib/parser.go"].has_test is True
    assert by_path["ui/widget.ts"].has_test is True


def test_dot_spec_and_underscore_spec_conventions(tmp_path: Path):
    _write(tmp_path / "a" / "form.jsx")
    _write(tmp_path / "a" / "form.spec.jsx")
    _write(tmp_path / "b" / "store.rb")
    _write(tmp_path / "b" / "store_spec.rb")
    by_path = {f.path: f for f in scan_polyglot_facts(str(tmp_path))}
    assert by_path["a/form.jsx"].has_test is True
    assert by_path["b/store.rb"].has_test is True


def test_tests_directory_convention(tmp_path: Path):
    # foo.ext has a sibling __tests__/ dir containing a file referencing foo.
    _write(tmp_path / "src" / "calc.js")
    _write(tmp_path / "src" / "__tests__" / "calc.js")
    by_path = {f.path: f for f in scan_polyglot_facts(str(tmp_path))}
    assert by_path["src/calc.js"].has_test is True


def test_tests_directory_with_test_suffixed_name(tmp_path: Path):
    _write(tmp_path / "core" / "engine.ts")
    _write(tmp_path / "tests" / "engine.test.ts")
    by_path = {f.path: f for f in scan_polyglot_facts(str(tmp_path))}
    assert by_path["core/engine.ts"].has_test is True


def test_unrelated_test_file_does_not_mark_source(tmp_path: Path):
    # A test exists, but for a DIFFERENT stem — util.js stays untested.
    _write(tmp_path / "web" / "util.js")
    _write(tmp_path / "web" / "other.test.js")
    by_path = {f.path: f for f in scan_polyglot_facts(str(tmp_path))}
    assert by_path["web/util.js"].has_test is False


def test_render_flags_untested_when_set_is_mixed(tmp_path: Path):
    # src/app.js is tested; web/util.js is not. The rendered clause flags only
    # the untested one with "(no test found)".
    _write(tmp_path / "src" / "app.js")
    _write(tmp_path / "src" / "app.test.js")
    _write(tmp_path / "web" / "util.js")
    facts = scan_polyglot_facts(str(tmp_path))
    by_path = {f.path: f for f in facts}
    assert by_path["src/app.js"].has_test is True
    assert by_path["web/util.js"].has_test is False
    clause = render_polyglot_attention(facts)
    assert "`web/util.js`" in clause
    assert "`web/util.js` (1 LOC, 0 commits) (no test found)" in clause
    # The tested file is NOT flagged.
    assert "`src/app.js` (1 LOC, 0 commits)" in clause
    assert "`src/app.js` (1 LOC, 0 commits) (no test found)" not in clause


def test_render_all_untested_stays_byte_identical(tmp_path: Path):
    # When nothing has a test, there is no contrast signal, so no annotation is
    # added and the clause matches the pre-test-presence output exactly.
    facts = [
        FileFact(path="src/app.js", language="JavaScript", loc=412, churn=8),
        FileFact(path="web/index.html", language="HTML", loc=240, churn=1),
    ]
    clause = render_polyglot_attention(facts)
    assert clause == (
        "Largest / most-active files outside analysis scope: "
        "`src/app.js` (412 LOC, 8 commits), `web/index.html` (240 LOC, 1 commit)"
        " — Apex can't deep-analyse these yet, but they're where the "
        "non-Python risk concentrates."
    )
    assert "no test found" not in clause


def test_has_test_is_a_later_tiebreaker_only(tmp_path: Path):
    # Two files, equal churn (0) and equal LOC: untested sorts before tested.
    _write(tmp_path / "z_tested.js", "a = 1;\n")
    _write(tmp_path / "z_tested.test.js")
    _write(tmp_path / "z_untest.js", "a = 1;\n")
    facts = scan_polyglot_facts(str(tmp_path))
    order = [f.path for f in facts if f.path in {"z_tested.js", "z_untest.js"}]
    assert order == ["z_untest.js", "z_tested.js"]


def test_determinism_test_presence(tmp_path: Path):
    _write(tmp_path / "src" / "app.js")
    _write(tmp_path / "src" / "app.test.js")
    _write(tmp_path / "web" / "util.js")
    first = scan_polyglot_facts(str(tmp_path))
    second = scan_polyglot_facts(str(tmp_path))
    assert first == second
    assert [(f.path, f.has_test) for f in first] == [
        (f.path, f.has_test) for f in second
    ]


def test_empty_repo_still_renders_nothing(tmp_path: Path):
    assert scan_polyglot_facts(str(tmp_path)) == []
    assert render_polyglot_attention([]) == ""
