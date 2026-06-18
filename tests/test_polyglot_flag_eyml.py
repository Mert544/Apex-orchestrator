"""Tests for the polyglot safe flag-action (``app/execution/polyglot_flag.py``).

Covers each comment syntax (JS slash, YAML/shell hash, HTML block), indentation
preservation, idempotence, decline paths (out-of-range line, unsupported
extension), byte-identical preservation of the flagged line, and determinism.
"""

from __future__ import annotations

import pytest

from app.execution.polyglot_flag import flag_line, is_flagged


# --- JS/TS family: ``// Apex: ...`` ---------------------------------------

def test_js_inserts_slash_comment_above_line():
    src = "const a = 1;\nconst b = 2;\nconst c = 3;\n"
    out = flag_line("x.js", src, 2, "review b")
    assert out == "const a = 1;\n// Apex: review b\nconst b = 2;\nconst c = 3;\n"


@pytest.mark.parametrize("ext", ["ts", "tsx", "js", "jsx"])
def test_all_js_family_extensions_use_slash(ext):
    out = flag_line(f"f.{ext}", "let x = 0;\n", 1, "m")
    assert out == "// Apex: m\nlet x = 0;\n"


def test_js_preserves_indentation():
    src = "function f() {\n    return secret();\n}\n"
    out = flag_line("a.ts", src, 2, "no secret")
    assert out == "function f() {\n    // Apex: no secret\n    return secret();\n}\n"


# --- YAML / shell: ``# Apex: ...`` ----------------------------------------

@pytest.mark.parametrize("ext", ["yaml", "yml", "sh"])
def test_yaml_and_shell_use_hash(ext):
    out = flag_line(f"c.{ext}", "key: value\n", 1, "check")
    assert out == "# Apex: check\nkey: value\n"


def test_yaml_preserves_indentation():
    src = "root:\n  child: 1\n"
    out = flag_line("c.yaml", src, 2, "nested")
    assert out == "root:\n  # Apex: nested\n  child: 1\n"


# --- HTML: ``<!-- Apex: ... -->`` -----------------------------------------

def test_html_uses_block_comment():
    src = "<div>\n  <span>hi</span>\n</div>\n"
    out = flag_line("p.html", src, 2, "audit span")
    assert out == "<div>\n  <!-- Apex: audit span -->\n  <span>hi</span>\n</div>\n"


# --- Idempotence -----------------------------------------------------------

def test_idempotent_second_flag_declines():
    src = "const a = 1;\nconst b = 2;\n"
    once = flag_line("x.js", src, 2, "same")
    assert once is not None
    # Re-flagging the now-shifted target line (the original line 2 is now line 3)
    twice = flag_line("x.js", once, 3, "same")
    assert twice is None


def test_idempotent_flagging_once_equals_twice_idempotent_helper():
    src = "a: 1\nb: 2\n"
    once = flag_line("c.yml", src, 2, "dup")
    assert once is not None
    assert is_flagged(once, 3, "dup")
    # Flagging the same logical line again is declined.
    assert flag_line("c.yml", once, 3, "dup") is None


def test_is_flagged_true_after_flag_and_false_before():
    src = "<ul>\n<li>x</li>\n</ul>\n"
    assert is_flagged(src, 2, "li check") is False
    out = flag_line("z.html", src, 2, "li check")
    assert is_flagged(out, 3, "li check") is True


def test_is_flagged_false_for_different_message():
    src = "x = 1\n// Apex: one\nx = 2\n"
    assert is_flagged(src, 3, "one") is True
    assert is_flagged(src, 3, "two") is False


# --- Decline paths ---------------------------------------------------------

def test_out_of_range_line_returns_none():
    src = "a = 1\nb = 2\n"
    assert flag_line("f.js", src, 0, "m") is None
    assert flag_line("f.js", src, 3, "m") is None
    assert flag_line("f.js", src, 99, "m") is None


def test_unsupported_extension_returns_none():
    src = "print(1)\n"
    assert flag_line("f.py", src, 1, "m") is None
    assert flag_line("f.rb", src, 1, "m") is None
    assert flag_line("noext", src, 1, "m") is None


def test_is_flagged_out_of_range_is_false_not_raising():
    assert is_flagged("a\n", 0, "m") is False
    assert is_flagged("a\n", 1, "m") is False  # nothing above line 1
    assert is_flagged("a\n", 50, "m") is False


def test_empty_source_declines():
    assert flag_line("f.js", "", 1, "m") is None


# --- Preservation + token equivalence -------------------------------------

def test_original_line_byte_identical_and_one_line_added():
    src = "const a = 1;\n    const secret = key;\nconst c = 3;\n"
    out = flag_line("app.ts", src, 2, "rotate key")
    assert out is not None
    src_lines = src.splitlines(keepends=True)
    out_lines = out.splitlines(keepends=True)
    # Exactly one line added.
    assert len(out_lines) == len(src_lines) + 1
    # The flagged source line is preserved byte-for-byte, shifted down by one.
    assert out_lines[2] == src_lines[1]
    # The single inserted line is the comment, at the expected position.
    inserted = [ln for ln in out_lines if ln not in src_lines or out_lines.count(ln) > src_lines.count(ln)]
    assert "    // Apex: rotate key\n" in out_lines
    assert out_lines[1] == "    // Apex: rotate key\n"
    assert inserted == ["    // Apex: rotate key\n"]


def test_js_tokens_equal_original_minus_comment():
    # The flagged file, with its single ``// Apex:`` line stripped, is
    # byte-identical to the original — i.e. only a comment was added.
    src = "let total = price * qty;\nrenderTotal(total);\n"
    out = flag_line("cart.jsx", src, 2, "validate qty")
    assert out is not None
    kept = [ln for ln in out.splitlines(keepends=True)
            if "// Apex: validate qty" not in ln]
    assert "".join(kept) == src


def test_no_trailing_newline_target_still_flags():
    src = "a = 1\nb = 2"  # last line has no newline
    out = flag_line("c.sh", src, 2, "tail")
    assert out == "a = 1\n# Apex: tail\nb = 2"
    # Original last line preserved exactly (still no newline).
    assert out.endswith("b = 2")


# --- Determinism -----------------------------------------------------------

def test_deterministic_repeated_calls_identical():
    src = "root:\n  a: 1\n  b: 2\n"
    results = {flag_line("d.yaml", src, 3, "stable") for _ in range(20)}
    assert len(results) == 1
    assert next(iter(results)) == "root:\n  a: 1\n  # Apex: stable\n  b: 2\n"
