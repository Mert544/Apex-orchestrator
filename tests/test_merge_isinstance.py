"""Tests for the merge-isinstance develop transform."""

from __future__ import annotations

import ast

from app.execution.merge_isinstance import plan_merge_isinstance


def _write(tmp_path, source: str, rel: str = "mod.py") -> str:
    (tmp_path / rel).write_text(source, encoding="utf-8")
    return rel


def _result(tmp_path, source: str):
    rel = _write(tmp_path, source)
    return rel, plan_merge_isinstance(tmp_path, rel)


def test_two_type_or_to_tuple(tmp_path):
    rel, plan = _result(tmp_path, "y = isinstance(x, A) or isinstance(x, B)\n")
    assert plan.new_contents[rel] == "y = isinstance(x, (A, B))\n"
    assert plan.edits_by_file[rel] == 1
    assert not plan.blockers


def test_three_type_or_to_3_tuple(tmp_path):
    rel, plan = _result(
        tmp_path,
        "y = isinstance(x, A) or isinstance(x, B) or isinstance(x, C)\n",
    )
    assert plan.new_contents[rel] == "y = isinstance(x, (A, B, C))\n"
    assert plan.edits_by_file[rel] == 1


def test_flatten_when_one_arg_already_tuple(tmp_path):
    rel, plan = _result(
        tmp_path, "y = isinstance(x, (A, B)) or isinstance(x, C)\n")
    assert plan.new_contents[rel] == "y = isinstance(x, (A, B, C))\n"


def test_flatten_both_tuples(tmp_path):
    rel, plan = _result(
        tmp_path, "y = isinstance(x, (A, B)) or isinstance(x, (C, D))\n")
    assert plan.new_contents[rel] == "y = isinstance(x, (A, B, C, D))\n"


def test_different_targets_untouched(tmp_path):
    src = "y = isinstance(x, A) or isinstance(z, B)\n"
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


def test_single_isinstance_untouched(tmp_path):
    rel, plan = _result(tmp_path, "y = isinstance(x, A)\n")
    assert not plan.new_contents


def test_mixed_with_non_isinstance_untouched(tmp_path):
    src = "y = isinstance(x, A) or foo()\n"
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents


def test_mixed_with_nested_boolop_untouched(tmp_path):
    # A value that is itself a BoolOp must skip the whole outer BoolOp.
    src = "y = isinstance(x, A) or (isinstance(x, B) and g())\n"
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents


def test_keyword_isinstance_untouched(tmp_path):
    # isinstance called with a keyword arg isn't the bare two-positional shape.
    src = "y = isinstance(x, A) or isinstance(x, class_or_tuple=B)\n"
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents


def test_three_arg_call_untouched(tmp_path):
    src = "y = isinstance(x, A) or isinstance(x, B, C)\n"
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents


def test_starred_arg_untouched(tmp_path):
    src = "y = isinstance(x, A) or isinstance(*pair)\n"
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents


def test_multiline_boolop_untouched(tmp_path):
    src = "y = (\n    isinstance(x, A)\n    or isinstance(x, B)\n)\n"
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents


def test_duplicate_types_deduped(tmp_path):
    rel, plan = _result(
        tmp_path,
        "y = isinstance(x, A) or isinstance(x, B) or isinstance(x, A)\n",
    )
    assert plan.new_contents[rel] == "y = isinstance(x, (A, B))\n"


def test_duplicate_across_tuple_deduped(tmp_path):
    rel, plan = _result(
        tmp_path, "y = isinstance(x, (A, B)) or isinstance(x, A)\n")
    assert plan.new_contents[rel] == "y = isinstance(x, (A, B))\n"


def test_attribute_type_preserved(tmp_path):
    rel, plan = _result(
        tmp_path,
        "y = isinstance(x, mod.A) or isinstance(x, pkg.mod.B)\n",
    )
    assert plan.new_contents[rel] == "y = isinstance(x, (mod.A, pkg.mod.B))\n"


def test_attribute_target_preserved(tmp_path):
    rel, plan = _result(
        tmp_path,
        "y = isinstance(self.x, A) or isinstance(self.x, B)\n",
    )
    assert plan.new_contents[rel] == "y = isinstance(self.x, (A, B))\n"


def test_multiple_occurrences_all_merged(tmp_path):
    src = (
        "a = isinstance(x, A) or isinstance(x, B)\n"
        "b = 1\n"
        "c = isinstance(y, C) or isinstance(y, D) or isinstance(y, E)\n"
    )
    rel, plan = _result(tmp_path, src)
    assert plan.edits_by_file[rel] == 2
    assert plan.new_contents[rel] == (
        "a = isinstance(x, (A, B))\n"
        "b = 1\n"
        "c = isinstance(y, (C, D, E))\n"
    )


def test_two_occurrences_on_one_line(tmp_path):
    # Right-to-left application keeps offsets valid for same-line rewrites.
    src = ("r = (isinstance(x, A) or isinstance(x, B), "
           "isinstance(y, C) or isinstance(y, D))\n")
    rel, plan = _result(tmp_path, src)
    assert plan.new_contents[rel] == (
        "r = (isinstance(x, (A, B)), isinstance(y, (C, D)))\n")


def test_unparseable_module_blocks(tmp_path):
    rel, plan = _result(tmp_path, "def broken(:\n")
    assert plan.blockers
    assert not plan.new_contents
    assert not plan.ok


def test_noop_returns_empty_plan(tmp_path):
    rel, plan = _result(tmp_path, "y = 1 + 2\n")
    assert not plan.new_contents
    assert not plan.blockers
    assert not plan.ok


def test_fixture_path_excluded(tmp_path):
    src = "y = isinstance(x, A) or isinstance(x, B)\n"
    rel = "tests/test_thing.py"
    (tmp_path / "tests").mkdir()
    (tmp_path / rel).write_text(src, encoding="utf-8")
    plan = plan_merge_isinstance(tmp_path, rel)
    assert not plan.new_contents
    assert not plan.blockers


def test_missing_file_blocks(tmp_path):
    plan = plan_merge_isinstance(tmp_path, "nope.py")
    assert plan.blockers
    assert not plan.ok


def test_semantically_equivalent(tmp_path):
    # The rewritten expression yields the same truth value across inputs.
    before = "result = isinstance(x, int) or isinstance(x, (float, str))\n"
    rel, plan = _result(tmp_path, before)
    after = plan.new_contents[rel]
    # Sanity: the merged form is a single tuple-form isinstance.
    assert after == "result = isinstance(x, (int, float, str))\n"

    for x in (1, 1.0, "s", b"bytes", [1], None, True, (1,)):
        before_ns: dict = {"x": x}
        after_ns: dict = {"x": x}
        exec(compile(before, "<before>", "exec"), before_ns)
        exec(compile(after, "<after>", "exec"), after_ns)
        assert before_ns["result"] == after_ns["result"], x


def test_semantically_equivalent_three_targets(tmp_path):
    before = ("ok = isinstance(v, int) or isinstance(v, float) "
              "or isinstance(v, complex)\n")
    rel, plan = _result(tmp_path, before)
    after = plan.new_contents[rel]
    assert ast.parse(after)  # re-parses
    for v in (1, 2.0, 3j, "x", None, True):
        b_ns: dict = {"v": v}
        a_ns: dict = {"v": v}
        exec(compile(before, "<b>", "exec"), b_ns)
        exec(compile(after, "<a>", "exec"), a_ns)
        assert b_ns["ok"] == a_ns["ok"], v
