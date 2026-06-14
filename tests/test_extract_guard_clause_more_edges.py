from __future__ import annotations

import ast

from app.execution.extract_guard_clause import plan_extract_guard_clause


def _write(tmp_path, source: str, rel: str = "app/m.py") -> str:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / rel).write_text(source, encoding="utf-8")
    return rel


def _run_func(source: str, name: str, *args):
    ns: dict = {}
    exec(compile(source, "<rewritten>", "exec"), ns)  # noqa: S102
    return ns[name](*args)


# --- ambiguous-dedent skip (one-line ``if x: return x``) ---------------------

def test_inline_if_body_is_skipped(tmp_path):
    # The if header and body share one physical line, so the if-body line does
    # not carry the expected leading indent — the dedent is ambiguous and the
    # occurrence is skipped (no rewrite, no blocker).
    rel = _write(tmp_path, "def f(x):\n    if x: return x\n")
    plan = plan_extract_guard_clause(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


# --- bodies that are a single real-but-trivial statement still qualify --------

def test_pass_body_qualifies(tmp_path):
    rel = _write(tmp_path, "def f(x):\n    if x:\n        pass\n")
    new = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert new == ("def f(x):\n    if not (x):\n        return\n    pass\n")
    ast.parse(new)
    assert _run_func(new, "f", 0) is None


def test_ellipsis_body_qualifies(tmp_path):
    rel = _write(tmp_path, "def f(x):\n    if x:\n        ...\n")
    new = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert new == ("def f(x):\n    if not (x):\n        return\n    ...\n")
    ast.parse(new)


# --- docstring handling shapes ------------------------------------------------

def test_docstring_followed_by_two_statements_not_matched(tmp_path):
    # After stripping the docstring the remaining body is len 2, not a sole if.
    rel = _write(
        tmp_path,
        'def f(x):\n'
        '    """doc"""\n'
        '    y = 1\n'
        '    if x:\n'
        '        return y\n',
    )
    plan = plan_extract_guard_clause(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_function_body_without_if_is_noop(tmp_path):
    rel = _write(tmp_path, "def f():\n    pass\n")
    plan = plan_extract_guard_clause(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_docstring_only_if_body_with_multiline_statements(tmp_path):
    # Docstring left untouched; the multi-statement if-body all dedents together.
    rel = _write(
        tmp_path,
        'def f(x):\n'
        '    """Header."""\n'
        '    if x > 0:\n'
        '        a = x + 1\n'
        '        b = a * 2\n'
        '        return b\n',
    )
    new = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert new == (
        'def f(x):\n'
        '    """Header."""\n'
        '    if not (x > 0):\n'
        '        return\n'
        '    a = x + 1\n'
        '    b = a * 2\n'
        '    return b\n'
    )
    assert _run_func(new, "f", 3) == 8
    assert _run_func(new, "f", 0) is None


# --- is-not / is identity inversions both directions -------------------------

def test_is_not_inverts_to_is(tmp_path):
    rel = _write(tmp_path, "def f(x):\n    if x is not None:\n        return x\n")
    new = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert "    if x is None:\n" in new
    assert "not (" not in new
    assert _run_func(new, "f", 5) == 5
    assert _run_func(new, "f", None) is None


# --- multiple functions: only the matching ones rewrite ----------------------

def test_mixed_module_only_matching_function_rewritten(tmp_path):
    rel = _write(
        tmp_path,
        "def good(x):\n"
        "    if x:\n"
        "        return x\n"
        "\n"
        "def bad(x):\n"
        "    if x:\n"
        "        return x\n"
        "    return 0\n",
    )
    plan = plan_extract_guard_clause(str(tmp_path), rel)
    assert plan.edits_by_file[rel] == 1  # only good() matched
    new = plan.new_contents[rel]
    assert new.count("if not (") == 1
    assert "    return 0\n" in new  # bad() left intact
    ast.parse(new)


# --- non-existent module + unparseable both reported -------------------------

def test_missing_module_reports_cannot_read(tmp_path):
    (tmp_path / "app").mkdir()
    plan = plan_extract_guard_clause(str(tmp_path), "app/gone.py")
    assert any("cannot read" in b for b in plan.blockers)
    assert not plan.new_contents


def test_unparseable_module_reports_parse_error(tmp_path):
    rel = _write(tmp_path, "def f(:\n    pass\n")
    plan = plan_extract_guard_clause(str(tmp_path), rel)
    assert any("doesn't parse" in b for b in plan.blockers)


# --- determinism across repeated builds on a multi-function module -----------

def test_determinism_multi_function(tmp_path):
    rel = _write(
        tmp_path,
        "def a(x):\n    if x:\n        return x\n\n"
        "def b(y):\n    if y > 0:\n        return y\n",
    )
    first = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    second = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert first == second
