"""Tests for the simplify-dict-get develop transform."""

from __future__ import annotations

import ast

from app.execution.dict_get import plan_simplify_dict_get


def _write(tmp_path, source: str, rel: str = "mod.py") -> str:
    (tmp_path / rel).write_text(source, encoding="utf-8")
    return rel


def _result(tmp_path, source: str):
    rel = _write(tmp_path, source)
    return rel, plan_simplify_dict_get(tmp_path, rel)


def test_basic_name_key(tmp_path):
    rel, plan = _result(tmp_path, "y = d[k] if k in d else 0\n")
    assert plan.new_contents[rel] == "y = d.get(k, 0)\n"
    assert plan.edits_by_file[rel] == 1
    assert not plan.blockers


def test_attribute_container(tmp_path):
    src = "y = self.cache[k] if k in self.cache else None\n"
    rel, plan = _result(tmp_path, src)
    assert plan.new_contents[rel] == "y = self.cache.get(k, None)\n"
    assert plan.edits_by_file[rel] == 1


def test_constant_key(tmp_path):
    rel, plan = _result(tmp_path, "y = d['x'] if 'x' in d else 1\n")
    assert plan.new_contents[rel] == "y = d.get('x', 1)\n"


def test_mismatched_container_untouched(tmp_path):
    rel, plan = _result(tmp_path, "y = a[k] if k in b else 0\n")
    assert not plan.new_contents
    assert not plan.blockers


def test_mismatched_key_untouched(tmp_path):
    rel, plan = _result(tmp_path, "y = d[k1] if k2 in d else 0\n")
    assert not plan.new_contents
    assert not plan.blockers


def test_call_container_untouched(tmp_path):
    # f() has potential side effects and is evaluated twice in the original —
    # the guard skips it to stay always-correct.
    rel, plan = _result(tmp_path, "y = f()[k] if k in f() else 0\n")
    assert not plan.new_contents
    assert not plan.blockers


def test_call_key_untouched(tmp_path):
    rel, plan = _result(tmp_path, "y = d[g()] if g() in d else 0\n")
    assert not plan.new_contents
    assert not plan.blockers


def test_subscript_key_untouched(tmp_path):
    # A subscript key could itself have side effects via a custom __getitem__.
    rel, plan = _result(tmp_path, "y = d[ks[0]] if ks[0] in d else 0\n")
    assert not plan.new_contents
    assert not plan.blockers


def test_multiline_ternary_untouched(tmp_path):
    src = "y = (\n    d[k]\n    if k in d\n    else 0\n)\n"
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


def test_multiple_occurrences_all_rewritten(tmp_path):
    src = (
        "a = d[k] if k in d else 0\n"
        "b = 1\n"
        "c = m[j] if j in m else None\n"
    )
    rel, plan = _result(tmp_path, src)
    assert plan.edits_by_file[rel] == 2
    assert plan.new_contents[rel] == (
        "a = d.get(k, 0)\n"
        "b = 1\n"
        "c = m.get(j, None)\n"
    )


def test_two_occurrences_on_one_line(tmp_path):
    # Right-to-left application keeps offsets valid for same-line rewrites.
    src = "r = (d[k] if k in d else 0, m[j] if j in m else 1)\n"
    rel, plan = _result(tmp_path, src)
    assert plan.new_contents[rel] == "r = (d.get(k, 0), m.get(j, 1))\n"
    assert plan.edits_by_file[rel] == 2


def test_attribute_key_rewritten(tmp_path):
    src = "y = d[self.k] if self.k in d else 0\n"
    rel, plan = _result(tmp_path, src)
    assert plan.new_contents[rel] == "y = d.get(self.k, 0)\n"


def test_reparses(tmp_path):
    rel, plan = _result(tmp_path, "y = d[k] if k in d else 0\n")
    assert ast.parse(plan.new_contents[rel])


def test_semantically_equivalent(tmp_path):
    before = "result = d[k] if k in d else 99\n"
    rel, plan = _result(tmp_path, before)
    after = plan.new_contents[rel]
    assert after == "result = d.get(k, 99)\n"

    for d, k in (
        ({"a": 1}, "a"),       # present key
        ({"a": 1}, "b"),       # absent key -> default
        ({}, "x"),             # empty dict
        ({"a": None}, "a"),    # present, value is None
    ):
        b_ns: dict = {"d": d, "k": k}
        a_ns: dict = {"d": d, "k": k}
        exec(compile(before, "<b>", "exec"), b_ns)
        exec(compile(after, "<a>", "exec"), a_ns)
        assert b_ns["result"] == a_ns["result"], (d, k)


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
    src = "y = d[k] if k in d else 0\n"
    rel = "tests/test_thing.py"
    (tmp_path / "tests").mkdir()
    (tmp_path / rel).write_text(src, encoding="utf-8")
    plan = plan_simplify_dict_get(tmp_path, rel)
    assert not plan.new_contents
    assert not plan.blockers


def test_missing_file_blocks(tmp_path):
    plan = plan_simplify_dict_get(tmp_path, "nope.py")
    assert plan.blockers
    assert not plan.ok


def test_self_registration():
    from app.engine.objective_compiler import available_objectives

    assert "simplify-dict-get" in available_objectives()
