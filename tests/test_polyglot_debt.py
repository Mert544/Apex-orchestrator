"""Tests for the language-agnostic DEBT-MARKER count that sharpens Apex's
polyglot facts: ``TODO``/``FIXME``/``HACK``/``XXX`` are a real, comment-syntax-
independent debt signal on ANY text file, so ``FileFact.debt_markers`` counts
them and ``render_polyglot_attention`` flags a file with "N TODO/FIXME".

The annotation is additive and gated exactly like ``has_test``'s "(no test
found)": a no-debt set renders byte-identically to the pre-debt output.
"""

from pathlib import Path

from app.tools.polyglot_facts import (
    FileFact,
    render_polyglot_attention,
    scan_polyglot_facts,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_counts_todo_and_fixme_markers(tmp_path: Path):
    _write(
        tmp_path / "web" / "app.js",
        "// TODO: refactor\n"
        "const a = 1; // TODO inline\n"
        "function f() {} // TODO again\n"
        "/* FIXME: broken */\n"
        "const b = 2;\n",
    )
    by_path = {f.path: f for f in scan_polyglot_facts(str(tmp_path))}
    assert by_path["web/app.js"].debt_markers == 4


def test_no_markers_yields_zero_and_unchanged_clause(tmp_path: Path):
    _write(tmp_path / "web" / "clean.js", "const a = 1;\nconst b = 2;\n")
    facts = scan_polyglot_facts(str(tmp_path))
    by_path = {f.path: f for f in facts}
    assert by_path["web/clean.js"].debt_markers == 0
    clause = render_polyglot_attention(facts)
    assert "TODO/FIXME" not in clause


def test_case_insensitive_and_word_boundary(tmp_path: Path):
    # todo/Fixme/hAcK/xxx match case-insensitively; TODOLIST and FIXMEISH do NOT
    # (word boundary), nor does a substring like "axxxb".
    _write(
        tmp_path / "lib" / "parser.go",
        "// todo lower\n"
        "// Fixme mixed\n"
        "// hAcK weird\n"
        "// xxx marker\n"
        "var TODOLIST = 1\n"
        "var FIXMEISH = 2\n"
        "var axxxb = 3\n",
    )
    by_path = {f.path: f for f in scan_polyglot_facts(str(tmp_path))}
    assert by_path["lib/parser.go"].debt_markers == 4


def test_render_flags_debt_when_set_has_markers(tmp_path: Path):
    facts = [
        FileFact(path="src/app.js", language="JavaScript", loc=412, churn=8,
                 debt_markers=12),
        FileFact(path="web/index.html", language="HTML", loc=240, churn=1),
    ]
    clause = render_polyglot_attention(facts)
    assert "`src/app.js` (412 LOC, 8 commits) (12 TODO/FIXME)" in clause
    # The marker-free file is NOT annotated.
    assert "`web/index.html` (240 LOC, 1 commit)" in clause
    assert "`web/index.html` (240 LOC, 1 commit) (" not in clause


def test_render_no_debt_stays_byte_identical(tmp_path: Path):
    # No file carries debt, so no annotation is added and the clause matches the
    # pre-debt output exactly (same fixture as the pinned render tests).
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
    assert "TODO/FIXME" not in clause


def test_debt_does_not_affect_ranking(tmp_path: Path):
    # Two files, equal churn (0); ordering stays (-loc, path) regardless of debt.
    # The high-LOC file with NO debt still sorts before the low-LOC heavy-debt one.
    _write(tmp_path / "big.js", "a = 1;\nb = 2;\nc = 3;\nd = 4;\n")
    _write(tmp_path / "small.js", "// TODO\n// FIXME\n// HACK\n")
    facts = scan_polyglot_facts(str(tmp_path))
    order = [f.path for f in facts if f.path in {"big.js", "small.js"}]
    assert order == ["big.js", "small.js"]


def test_debt_and_test_annotations_coexist(tmp_path: Path):
    # When a set carries BOTH a test signal and a debt signal, an untested file
    # with debt shows "(no test found) (N TODO/FIXME)".
    _write(tmp_path / "src" / "app.js", "x = 1;\n")
    _write(tmp_path / "src" / "app.test.js", "x = 1;\n")
    _write(tmp_path / "web" / "util.js", "// TODO\n// FIXME\nx = 1;\n")
    facts = scan_polyglot_facts(str(tmp_path))
    clause = render_polyglot_attention(facts)
    assert "`web/util.js` (3 LOC, 0 commits) (no test found) (2 TODO/FIXME)" in clause


def test_determinism_debt(tmp_path: Path):
    _write(tmp_path / "web" / "app.js", "// TODO\n// FIXME\n// XXX\nx = 1;\n")
    first = scan_polyglot_facts(str(tmp_path))
    second = scan_polyglot_facts(str(tmp_path))
    assert first == second
    assert [(f.path, f.debt_markers) for f in first] == [
        (f.path, f.debt_markers) for f in second
    ]


def test_empty_repo_renders_nothing(tmp_path: Path):
    assert scan_polyglot_facts(str(tmp_path)) == []
    assert render_polyglot_attention([]) == ""
