"""Edge / error-path tests for the comment-quality analyzer.

Covers the prose gates (sentence-ending punctuation and long word runs), the
parser-failure path, the tokenizer-error partial-result path, the ``max_files``
cap, and the unreadable-file skip. Deterministic and hermetic.
"""

from __future__ import annotations

from pathlib import Path

from app.tools.comment_quality import (
    analyze_comment_quality,
    _analyze_source,
    _is_commented_out_code,
    _looks_like_prose,
    _parses_as_code,
)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_prose_sentence_ending_with_operator_still_code():
    # Ends with '.', but has '(' -> NOT prose by the sentence-end rule. The dotted
    # call parses as one statement -> code-shaped and flagged.
    assert _looks_like_prose("call(x).") is False
    assert _is_commented_out_code("call(x)", first_char_after_hash="c")


def test_sentence_ending_without_operator_is_prose():
    # Ends with sentence punctuation AND has no '='/'(' operator -> prose (the
    # first prose gate's True branch).
    assert _looks_like_prose("explains the why.") is True
    assert _looks_like_prose("really?") is True


def test_long_word_run_is_prose():
    # >= 6 alphabetic words, no operator/bracket -> prose, even with a colon shape.
    body = "this is a fairly long natural english sentence here"
    assert _looks_like_prose(body) is True


def test_long_word_run_with_colon_shape_not_flagged():
    # Has a code shape (trailing colon) but is a long prose run -> rejected at the
    # prose gate before the parser is consulted.
    body = "remember to update the docs whenever the schema changes here:"
    assert not _is_commented_out_code(body, first_char_after_hash="r")


def test_short_phrase_with_shape_but_unparseable_rejected():
    # Has a code shape ('=') but does not parse cleanly -> parser is the final no.
    assert _parses_as_code("x = = y") is False
    assert not _is_commented_out_code("x = = y", first_char_after_hash="x")


def test_parses_as_code_rejects_multi_statement():
    # Two statements -> not a single disabled line.
    assert _parses_as_code("a = 1; b = 2") is False


def test_colon_header_gets_pass_body_to_parse():
    # A commented-out 'for' header ends with ':' -> ' pass' is appended to parse.
    assert _parses_as_code("for i in range(3):") is True


def test_tokenizer_error_yields_partial_results(tmp_path: Path):
    # An unclosed bracket raises tokenize.TokenError mid-stream; the analyzer must
    # keep whatever rows it already saw and not crash (the except/pass path).
    source = "x = 1\n# y = f(z)\n(\n"
    hits, comment_lines, code_lines = _analyze_source(source)
    # The comment on line 2 was seen before the broken line 3.
    assert (2, "y = f(z)") in hits
    assert comment_lines >= 1
    assert code_lines >= 1


def test_max_files_cap(tmp_path: Path):
    _write(tmp_path, "a.py", "# a = f(b)\na = 1\n")
    _write(tmp_path, "b.py", "# c = g(d)\nb = 1\n")
    result = analyze_comment_quality(tmp_path, max_files=1)
    assert result.files_scanned == 1
    # Only the first sorted module is recorded.
    assert set(result.module_ratios) == {"a.py"}


def test_unreadable_file_is_skipped(tmp_path: Path, monkeypatch):
    import app.tools.comment_quality as mod

    _write(tmp_path, "good.py", "# x = f(y)\nx = 1\n")
    _write(tmp_path, "bad.py", "# z = h(w)\nz = 1\n")

    real_read = mod.Path.read_text

    def fake_read(self, *args, **kwargs):
        if self.name == "bad.py":
            raise OSError("nope")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(mod.Path, "read_text", fake_read)
    result = analyze_comment_quality(tmp_path)
    assert set(result.module_ratios) == {"good.py"}
    assert result.files_scanned == 1
