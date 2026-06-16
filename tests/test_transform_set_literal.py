from __future__ import annotations

import ast

from app.execution.semantic.transforms.set_literal import apply


def _new(result) -> str:
    assert result is not None
    return result.patch_requests[0]["new_content"]


class TestSetLiteralRewrite:
    def test_list_arg_rewritten(self):
        result = apply("m.py", "x = set([1, 2, 3])\n", "title")
        assert _new(result) == "x = {1, 2, 3}\n"
        assert result.transform_type == "set_literal"

    def test_tuple_arg_rewritten(self):
        result = apply("m.py", "x = set((a, b))\n", "title")
        assert _new(result) == "x = {a, b}\n"

    def test_preserves_element_text_exactly(self):
        src = "x = set([foo.bar, baz(1, 2), 'q']) \n"
        out = _new(apply("m.py", src, "t"))
        assert out == "x = {foo.bar, baz(1, 2), 'q'} \n"

    def test_single_element_list(self):
        assert _new(apply("m.py", "x = set([1])\n", "t")) == "x = {1}\n"


class TestRefusals:
    def test_empty_call_refused(self):
        # set() is the empty set; {} is a dict, so it MUST stay set().
        assert apply("m.py", "x = set()\n", "t") is None

    def test_empty_list_refused(self):
        # set([]) -> {} would be a dict, not an empty set. Refuse.
        assert apply("m.py", "x = set([])\n", "t") is None

    def test_empty_tuple_refused(self):
        assert apply("m.py", "x = set(())\n", "t") is None

    def test_name_arg_refused(self):
        # set(x) where x is a name, not a literal display.
        assert apply("m.py", "x = set(x)\n", "t") is None

    def test_starred_refused(self):
        assert apply("m.py", "x = set([*a])\n", "t") is None
        assert apply("m.py", "x = set([*a, b])\n", "t") is None

    def test_generator_refused(self):
        assert apply("m.py", "x = set(x for x in y)\n", "t") is None

    def test_comprehension_refused(self):
        # A set comprehension is already a literal; nothing to rewrite.
        assert apply("m.py", "x = set([i for i in y])\n", "t") is None

    def test_attribute_set_refused(self):
        # foo.set([...]) is not the builtin.
        assert apply("m.py", "x = foo.set([1, 2])\n", "t") is None

    def test_extra_args_refused(self):
        assert apply("m.py", "x = set([1], extra)\n", "t") is None

    def test_keyword_args_refused(self):
        assert apply("m.py", "x = set([1], key=2)\n", "t") is None

    def test_syntax_error_returns_none(self):
        assert apply("m.py", "def (:\n", "t") is None

    def test_no_set_call_noop(self):
        assert apply("m.py", "x = [1, 2, 3]\n", "t") is None


class TestInvariants:
    def test_deterministic(self):
        src = "x = set([1, 2, 3])\nz = set([a, b])\n"
        first = _new(apply("m.py", src, "t"))
        for _ in range(5):
            assert _new(apply("m.py", src, "t")) == first

    def test_output_always_parseable(self):
        sources = [
            "x = set([1, 2, 3])\n",
            "x = set((a, b))\n",
            "y = set([f(x), g(y), 'str'])\n",
            "z = foo(set([1, 2]), other)\n",
        ]
        for src in sources:
            result = apply("m.py", src, "t")
            if result is not None:
                ast.parse(result.patch_requests[0]["new_content"])

    def test_semantic_equality(self):
        src = "x = set([1, 2, 3, 2, 1])\n"
        out = _new(apply("m.py", src, "t"))
        ns_old: dict = {}
        ns_new: dict = {}
        exec(compile(src, "<old>", "exec"), ns_old)
        exec(compile(out, "<new>", "exec"), ns_new)
        assert ns_old["x"] == ns_new["x"]
        assert isinstance(ns_new["x"], set)

    def test_only_first_rewrite_but_stable(self):
        # Two rewritable calls: each apply rewrites one; result stays parseable
        # and the rewritten call is gone from the candidate set.
        src = "a = set([1, 2])\nb = set([3, 4])\n"
        out = _new(apply("m.py", src, "t"))
        ast.parse(out)
        assert out.count("set([") == 1

    def test_nested_call_preserved(self):
        src = "x = sorted(set([3, 1, 2]))\n"
        out = _new(apply("m.py", src, "t"))
        assert out == "x = sorted({3, 1, 2})\n"
