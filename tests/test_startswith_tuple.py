"""Tests for the collapse-startswith develop transform."""

from __future__ import annotations

import ast

from app.execution.startswith_tuple import plan_collapse_startswith


def _write(tmp_path, rel: str, src: str) -> str:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    return rel


def _plan(tmp_path, src: str, rel: str = "pkg/mod.py"):
    _write(tmp_path, rel, src)
    return plan_collapse_startswith(str(tmp_path), rel), rel


def test_two_arg_startswith_or(tmp_path):
    src = "def f(x):\n    return x.startswith('a') or x.startswith('b')\n"
    plan, rel = _plan(tmp_path, src)
    assert plan.new_contents[rel] == (
        "def f(x):\n    return x.startswith(('a', 'b'))\n")
    assert plan.edits_by_file[rel] == 1
    assert not plan.blockers


def test_endswith_or(tmp_path):
    src = "def f(x):\n    return x.endswith('.py') or x.endswith('.pyi')\n"
    plan, rel = _plan(tmp_path, src)
    assert plan.new_contents[rel] == (
        "def f(x):\n    return x.endswith(('.py', '.pyi'))\n")


def test_three_args(tmp_path):
    src = ("def f(x):\n    return x.startswith('a') or x.startswith('b') "
           "or x.startswith('c')\n")
    plan, rel = _plan(tmp_path, src)
    assert "x.startswith(('a', 'b', 'c'))" in plan.new_contents[rel]
    assert plan.edits_by_file[rel] == 1


def test_flatten_existing_tuple(tmp_path):
    src = ("def f(x):\n    return x.startswith(('a', 'b')) "
           "or x.startswith('c')\n")
    plan, rel = _plan(tmp_path, src)
    assert "x.startswith(('a', 'b', 'c'))" in plan.new_contents[rel]


def test_different_receivers_untouched(tmp_path):
    src = "def f(x, y):\n    return x.startswith('a') or y.startswith('b')\n"
    plan, rel = _plan(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


def test_startswith_endswith_mix_untouched(tmp_path):
    src = "def f(x):\n    return x.startswith('a') or x.endswith('b')\n"
    plan, rel = _plan(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


def test_single_call_untouched(tmp_path):
    src = "def f(x):\n    return x.startswith('a')\n"
    plan, rel = _plan(tmp_path, src)
    assert not plan.new_contents


def test_or_with_non_call_untouched(tmp_path):
    src = "def f(x):\n    return x.startswith('a') or foo()\n"
    plan, rel = _plan(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


def test_keyword_arg_untouched(tmp_path):
    # startswith's 2nd/3rd args (start/end) make this NOT a tuple-collapsible form.
    src = "def f(x):\n    return x.startswith('a', 0) or x.startswith('b', 0)\n"
    plan, rel = _plan(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


def test_multiline_boolop_untouched(tmp_path):
    src = ("def f(x):\n    return (x.startswith('a')\n"
           "            or x.startswith('b'))\n")
    plan, rel = _plan(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


def test_attribute_receiver_handled(tmp_path):
    src = ("def f(path):\n    return path.name.startswith('a') "
           "or path.name.startswith('b')\n")
    plan, rel = _plan(tmp_path, src)
    assert "path.name.startswith(('a', 'b'))" in plan.new_contents[rel]


def test_duplicate_args_deduped(tmp_path):
    src = ("def f(x):\n    return x.startswith('a') or x.startswith('a') "
           "or x.startswith('b')\n")
    plan, rel = _plan(tmp_path, src)
    assert "x.startswith(('a', 'b'))" in plan.new_contents[rel]


def test_multiple_occurrences_merged(tmp_path):
    src = ("def f(x, y):\n"
           "    a = x.startswith('a') or x.startswith('b')\n"
           "    b = y.endswith('c') or y.endswith('d')\n"
           "    return a, b\n")
    plan, rel = _plan(tmp_path, src)
    assert "x.startswith(('a', 'b'))" in plan.new_contents[rel]
    assert "y.endswith(('c', 'd'))" in plan.new_contents[rel]
    assert plan.edits_by_file[rel] == 2


def test_result_reparses_and_equivalent(tmp_path):
    src = (
        "def f(x):\n"
        "    return x.startswith('a') or x.startswith('bb') or x.endswith('z')\n"
        "def g(x):\n"
        "    return x.startswith('a') or x.startswith('bb')\n"
    )
    plan, rel = _plan(tmp_path, src)
    new_src = plan.new_contents[rel]
    ast.parse(new_src)  # must re-parse

    ns_old: dict = {}
    ns_new: dict = {}
    exec(src, ns_old)
    exec(new_src, ns_new)
    for s in ("a", "aXY", "bb", "bbZ", "qz", "z", "nope", ""):
        assert ns_old["f"](s) == ns_new["f"](s)
        assert ns_old["g"](s) == ns_new["g"](s)


def test_unparseable_module_blocks(tmp_path):
    src = "def f(:\n    pass\n"
    plan, rel = _plan(tmp_path, src)
    assert plan.blockers
    assert not plan.new_contents


def test_noop_returns_empty_plan(tmp_path):
    src = "def f(x):\n    return x + 1\n"
    plan, rel = _plan(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers
    assert not plan.ok


def test_fixture_path_skipped(tmp_path):
    src = "def f(x):\n    return x.startswith('a') or x.startswith('b')\n"
    rel = _write(tmp_path, "tests/test_thing.py", src)
    plan = plan_collapse_startswith(str(tmp_path), rel)
    assert not plan.new_contents
    assert not plan.blockers


def test_receiver_parenthesised_when_low_precedence(tmp_path):
    # `(a or b).startswith(...)` receiver stays wrapped: `a or b.startswith(...)`
    # would be `a or (b.startswith(...))`.  [H6]
    from app.execution.startswith_tuple import plan_collapse_startswith
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "m.py").write_text(
        'def f(a, b):\n    return (a or b).startswith("x") or (a or b).startswith("y")\n',
        encoding="utf-8")
    new = plan_collapse_startswith(str(tmp_path), "app/m.py").new_contents["app/m.py"]
    assert '(a or b).startswith(("x", "y"))' in new
    ns: dict = {}
    exec(compile(new, "<m>", "exec"), ns)  # noqa: S102
    assert ns["f"]("zzz", "abc") is False
    assert ns["f"]("", "xyz") is True
