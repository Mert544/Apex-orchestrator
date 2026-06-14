from __future__ import annotations

import ast

import pytest

from app.execution.remove_redundant_fstring import (
    plan_remove_redundant_fstring,
)


def _write(tmp_path, body: str, rel: str = "app/m.py") -> str:
    """Write a module under ``tmp_path`` and return its project-relative path."""
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return rel


def _plan(tmp_path, body: str, rel: str = "app/m.py"):
    _write(tmp_path, body, rel)
    return plan_remove_redundant_fstring(str(tmp_path), rel)


def _rewrite(tmp_path, body: str, rel: str = "app/m.py") -> str:
    """Run the plan over ``body`` and return the rewritten source (asserts it
    actually changed and re-parses)."""
    plan = _plan(tmp_path, body, rel)
    assert not plan.blockers, plan.blockers
    assert plan.new_contents, "expected a rewrite"
    new = plan.new_contents[rel]
    ast.parse(new)  # must re-parse
    return new


def _noop(tmp_path, body: str, rel: str = "app/m.py") -> None:
    """Assert the plan leaves ``body`` untouched (no rewrite, no blockers)."""
    plan = _plan(tmp_path, body, rel)
    assert not plan.blockers, plan.blockers
    assert not plan.new_contents, "expected no rewrite"


# --- positives: a placeholder-free f-string loses only its `f` prefix ----------

def test_plain_double_quote(tmp_path):
    assert _rewrite(tmp_path, 'x = f"hello world"\n') == 'x = "hello world"\n'


def test_plain_single_quote(tmp_path):
    assert _rewrite(tmp_path, "x = f'single'\n") == "x = 'single'\n"


def test_capital_f(tmp_path):
    assert _rewrite(tmp_path, 'x = F"up"\n') == 'x = "up"\n'


def test_raw_rf_keeps_r(tmp_path):
    assert _rewrite(tmp_path, 'x = rf"raw"\n') == 'x = r"raw"\n'


def test_raw_fr_keeps_r(tmp_path):
    assert _rewrite(tmp_path, 'x = fr"raw"\n') == 'x = r"raw"\n'


def test_raw_capital_keeps_case(tmp_path):
    assert _rewrite(tmp_path, 'x = Rf"raw"\n') == 'x = R"raw"\n'
    assert _rewrite(tmp_path, 'x = FR"raw"\n') == 'x = R"raw"\n'


def test_call_argument(tmp_path):
    assert _rewrite(tmp_path, 'log(f"done")\n') == 'log("done")\n'


def test_return_value(tmp_path):
    src = "def g():\n    return f'ok'\n"
    assert _rewrite(tmp_path, src) == "def g():\n    return 'ok'\n"


def test_empty_fstring(tmp_path):
    assert _rewrite(tmp_path, 'x = f""\n') == 'x = ""\n'


def test_triple_quoted_multiline(tmp_path):
    src = 'x = f"""\nline one\nline two\n"""\n'
    assert _rewrite(tmp_path, src) == 'x = """\nline one\nline two\n"""\n'


def test_two_on_one_line(tmp_path):
    # right-to-left application keeps both column spans valid.
    assert _rewrite(tmp_path, 'x = f"a" + f"b"\n') == 'x = "a" + "b"\n'


def test_only_targeted_fstring_changes(tmp_path):
    src = 'a = f"keep me"\nb = "already plain"\nc = f"{a}"\n'
    out = _rewrite(tmp_path, src)
    assert out == 'a = "keep me"\nb = "already plain"\nc = f"{a}"\n'


def test_indented_and_comment_preserved(tmp_path):
    src = "def g():\n    y = f'v'  # note\n    return y\n"
    out = _rewrite(tmp_path, src)
    assert out == "def g():\n    y = 'v'  # note\n    return y\n"


# --- negatives: anything not provably safe is left untouched -------------------

def test_placeholder_blocks(tmp_path):
    _noop(tmp_path, 'x = f"{y}"\n')


def test_placeholder_with_text_blocks(tmp_path):
    _noop(tmp_path, 'x = f"{y}text"\n')


def test_text_then_placeholder_blocks(tmp_path):
    _noop(tmp_path, 'x = f"text{y}"\n')


def test_plain_string_untouched(tmp_path):
    _noop(tmp_path, 'x = "already plain"\n')


def test_raw_plain_string_untouched(tmp_path):
    _noop(tmp_path, 'x = r"raw plain"\n')


def test_bytes_literal_untouched(tmp_path):
    _noop(tmp_path, 'x = b"bytes"\n')


def test_escaped_braces_blocked(tmp_path):
    # f"{{x}}" renders {x}; plain "{{x}}" renders {{x}} — NOT value-preserving.
    _noop(tmp_path, 'x = f"{{x}}"\n')


def test_implicit_concat_both_fstrings_blocked(tmp_path):
    # single JoinedStr node spanning both literals — half-rewrite avoided.
    _noop(tmp_path, 'x = f"a" f"b"\n')


def test_implicit_concat_mixed_blocked(tmp_path):
    _noop(tmp_path, 'x = f"a" "b"\n')


def test_implicit_concat_with_placeholder_blocked(tmp_path):
    _noop(tmp_path, 'x = f"a" f"{y}"\n')


# --- empty / edge paths --------------------------------------------------------

def test_no_strings_noop(tmp_path):
    _noop(tmp_path, "x = 1 + 2\n")


def test_fixture_path_excluded(tmp_path):
    # a test_/fixtures path is never a subject, even with a redundant f-string.
    _noop(tmp_path, 'x = f"plain"\n', rel="tests/test_thing.py")


def test_unreadable_module_blocks(tmp_path):
    plan = plan_remove_redundant_fstring(str(tmp_path), "app/missing.py")
    assert plan.blockers
    assert not plan.new_contents


def test_syntax_error_blocks(tmp_path):
    plan = _plan(tmp_path, "def (:\n")
    assert plan.blockers
    assert not plan.new_contents


# --- determinism + exec-equivalence -------------------------------------------

def test_deterministic_repeated_runs(tmp_path):
    src = 'a = f"x"\nb = rf"y"\nlog(f"z")\n'
    first = _rewrite(tmp_path, src)
    for _ in range(3):
        assert _rewrite(tmp_path, src) == first


@pytest.mark.parametrize(
    "literal",
    ['f"hello"', "f'single'", 'rf"raw\\d+"', 'fr"\\n"', 'F"caps"', 'f""'],
)
def test_value_identical_after_strip(tmp_path, literal):
    src = f"x = {literal}\n"
    out = _rewrite(tmp_path, src)
    # the rewritten literal is the same string value, sans the f prefix.
    ns_before: dict = {}
    ns_after: dict = {}
    exec(compile(src, "<before>", "exec"), ns_before)
    exec(compile(out, "<after>", "exec"), ns_after)
    assert ns_before["x"] == ns_after["x"]
    # and the f prefix is genuinely gone.
    assert "f" not in out.split("=", 1)[1].lstrip()[:2].lower().rstrip("'\"")


def test_value_identical_for_escaped_braces_when_skipped(tmp_path):
    # the blocker exists precisely so this value is preserved (no rewrite).
    src = 'x = f"{{lit}}"\n'
    _noop(tmp_path, src)
    ns: dict = {}
    exec(compile(src, "<m>", "exec"), ns)
    assert ns["x"] == "{lit}"
