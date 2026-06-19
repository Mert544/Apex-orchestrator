"""Function-level coverage must key on a CODE reference, not a raw-text match.

A red-team moat audit found ``_names_changed_function`` used a whole-word regex
over the entire test file, so a changed function's name appearing only in a
COMMENT (or unrelated string) of an already-importing test falsely upgraded the
verification strength from ``module`` to ``function`` — overstating that the
suite actually exercises the change. (The sibling ``_references_module`` was
already AST-exact; this closes the same gap for function-level coverage.)

These tests pin: a code reference counts; a comment/string mention does not;
unparsable test text falls back to the text match. Deterministic; stdlib-only.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.verification_strength import _names_changed_function, assess_strength


def test_code_reference_counts():
    assert _names_changed_function("def t():\n    grab()\n", ["grab"]) is True
    assert _names_changed_function("x = obj.grab\n", ["grab"]) is True
    # A bare import that brings the name in but never USES it does not exercise
    # the function — honestly module-level, not function-level.
    assert _names_changed_function("from m import grab\n", ["grab"]) is False
    assert _names_changed_function("from m import grab\nx = grab\n", ["grab"]) is True


def test_comment_or_string_mention_does_not_count():
    assert _names_changed_function("# calls grab later\nx = 1\n", ["grab"]) is False
    assert _names_changed_function('s = "grab the thing"\n', ["grab"]) is False


def test_unparsable_text_falls_back_to_word_match():
    assert _names_changed_function("def t(:\n  grab()\n", ["grab"]) is True
    assert _names_changed_function("def t(:\n  # grab\n", ["grab"]) is True  # best-effort


def test_assess_strength_comment_mention_stays_module(tmp_path: Path):
    (tmp_path / "smoke.py").write_text("def grab():\n    return dict()\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    # Imports the module (module-level coverage) and names grab ONLY in a comment.
    (tests / "test_smoke.py").write_text(
        "import smoke  # exercises grab somewhere\n"
        "def test_imports():\n    assert smoke is not None\n", encoding="utf-8")
    s = assess_strength(str(tmp_path), ["smoke.py"],
                        {"smoke.py": "def grab():\n    return dict()\n"},
                        {"smoke.py": "def grab():\n    return {}\n"})
    assert s["level"] == "module"  # NOT falsely upgraded to function
    assert s["function_tests"] == []


def test_assess_strength_real_call_is_function(tmp_path: Path):
    (tmp_path / "smoke.py").write_text("def grab():\n    return dict()\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_real.py").write_text(
        "from smoke import grab\ndef test_g():\n    assert grab() == {}\n", encoding="utf-8")
    s = assess_strength(str(tmp_path), ["smoke.py"],
                        {"smoke.py": "def grab():\n    return dict()\n"},
                        {"smoke.py": "def grab():\n    return {}\n"})
    assert s["level"] == "function"
    assert s["function_tests"] == ["tests/test_real.py"]
