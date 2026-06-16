from pathlib import Path

from app.tools.comment_quality import (
    CommentQuality,
    analyze_comment_quality,
    _is_commented_out_code,
    _analyze_source,
)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_commented_out_assignment_is_flagged(tmp_path: Path):
    _write(tmp_path, "mod.py", "x = 1\n# x = compute(y)\nx = 2\n")
    result = analyze_comment_quality(tmp_path)
    hits = result.commented_out
    assert len(hits) == 1
    assert hits[0]["module"] == "mod.py"
    assert hits[0]["line"] == 2
    assert hits[0]["text"] == "x = compute(y)"


def test_commented_out_call_and_import_flagged():
    assert _is_commented_out_code("foo(bar, baz)", first_char_after_hash="f")
    assert _is_commented_out_code("import os", first_char_after_hash="i")
    assert _is_commented_out_code("from x import y", first_char_after_hash="f")
    assert _is_commented_out_code("if cond:", first_char_after_hash="i")


def test_prose_comment_not_flagged():
    assert not _is_commented_out_code("this explains why", first_char_after_hash="t")
    assert not _is_commented_out_code(
        "we do this because the parser is eager", first_char_after_hash="w"
    )
    # Prose ending in a period, no operators -> prose.
    assert not _is_commented_out_code("explains the why.", first_char_after_hash="e")


def test_markers_and_shebang_not_flagged():
    assert not _is_commented_out_code("noqa: E501", first_char_after_hash="n")
    assert not _is_commented_out_code("type: ignore", first_char_after_hash="t")
    assert not _is_commented_out_code("TODO: x = fix(this)", first_char_after_hash="T")
    assert not _is_commented_out_code("fmt: off", first_char_after_hash="f")
    # Shebang: detected via the char right after '#'.
    assert not _is_commented_out_code("/usr/bin/env python", first_char_after_hash="!")


def test_url_and_divider_not_flagged():
    assert not _is_commented_out_code(
        "see https://example.com/a=b(c)", first_char_after_hash="s"
    )
    assert not _is_commented_out_code("--------------------", first_char_after_hash="-")
    assert not _is_commented_out_code("", first_char_after_hash="")


def test_hash_inside_string_is_not_a_comment(tmp_path: Path):
    # The '#' lives inside a string literal: tokenize must NOT see a comment, so
    # the code-shaped 'x = y(z)' text is never analyzed as a comment body.
    _write(tmp_path, "s.py", 's = "# x = y(z)"\nv = 1\n')
    result = analyze_comment_quality(tmp_path)
    assert result.commented_out == []
    # One comment-free module: zero comment lines over two code lines.
    assert result.module_ratios["s.py"] == 0.0


def test_comment_ratio_math():
    source = "a = 1\nb = 2\n# a plain note here about things\nc = 3\n"
    hits, comment_lines, code_lines = _analyze_source(source)
    assert hits == []
    assert comment_lines == 1
    assert code_lines == 3


def test_overall_ratio_across_modules(tmp_path: Path):
    _write(tmp_path, "a.py", "x = 1\n# note\n")  # 1 comment, 1 code
    _write(tmp_path, "b.py", "y = 1\ny = 2\ny = 3\n")  # 0 comment, 3 code
    result = analyze_comment_quality(tmp_path)
    assert result.module_ratios["a.py"] == 1.0
    assert result.module_ratios["b.py"] == 0.0
    # overall = (1 + 0) comments / (1 + 3) code = 0.25
    assert result.overall_ratio == 0.25
    assert result.files_scanned == 2


def test_tests_and_fixtures_excluded(tmp_path: Path):
    _write(tmp_path, "app/real.py", "# x = f(y)\nreal = 1\n")
    _write(tmp_path, "tests/test_x.py", "# y = g(z)\n")
    _write(tmp_path, "pkg/conftest.py", "# z = h(w)\n")
    _write(tmp_path, "fixtures/data.py", "# q = j(k)\n")
    result = analyze_comment_quality(tmp_path)
    assert set(result.module_ratios) == {"app/real.py"}
    assert [h["module"] for h in result.commented_out] == ["app/real.py"]


def test_empty_tree_is_safe(tmp_path: Path):
    result = analyze_comment_quality(tmp_path)
    assert isinstance(result, CommentQuality)
    assert result.commented_out == []
    assert result.module_ratios == {}
    assert result.overall_ratio == 0.0
    assert result.files_scanned == 0


def test_missing_root_is_safe(tmp_path: Path):
    result = analyze_comment_quality(tmp_path / "does-not-exist")
    assert result.files_scanned == 0
    assert result.commented_out == []


def test_determinism(tmp_path: Path):
    _write(tmp_path, "z.py", "# z = a(b)\nz = 1\n")
    _write(tmp_path, "a.py", "# a = c(d)\na = 1\n")
    first = analyze_comment_quality(tmp_path)
    second = analyze_comment_quality(tmp_path)
    assert first == second
    # Sorted by (module, line): 'a.py' before 'z.py'.
    assert [h["module"] for h in first.commented_out] == ["a.py", "z.py"]


def test_commented_out_cap(tmp_path: Path):
    lines = [f"# v{i} = f{i}(x)" for i in range(40)]
    _write(tmp_path, "many.py", "\n".join(lines) + "\nreal = 1\n")
    result = analyze_comment_quality(tmp_path)
    assert len(result.commented_out) == 20
    # First 20 by line number.
    assert result.commented_out[0]["line"] == 1
    assert result.commented_out[-1]["line"] == 20


def test_trailing_comment_counts_both_lines(tmp_path: Path):
    _write(tmp_path, "t.py", "x = 1  # x = compute(y)\n")
    result = analyze_comment_quality(tmp_path)
    # The trailing comment IS code-shaped and parses -> flagged.
    assert len(result.commented_out) == 1
    # One row, counted as both a comment line and a code line -> ratio 1.0.
    assert result.module_ratios["t.py"] == 1.0
