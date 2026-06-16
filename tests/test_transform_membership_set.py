from __future__ import annotations

import ast

from app.execution.semantic.transforms.membership_set import apply


def _new(result) -> str:
    assert result is not None
    return result.patch_requests[0]["new_content"]


class TestMembershipSetRewrite:
    def test_list_of_ints(self):
        result = apply("m.py", "if x in [1, 2, 3]:\n    pass\n", "t")
        assert _new(result) == "if x in {1, 2, 3}:\n    pass\n"
        assert result.transform_type == "membership_set"

    def test_tuple_of_ints(self):
        result = apply("m.py", "y = x in (1, 2, 3)\n", "t")
        assert _new(result) == "y = x in {1, 2, 3}\n"

    def test_list_of_strings(self):
        out = _new(apply("m.py", "z = name in ['a', 'b', 'c']\n", "t"))
        assert out == "z = name in {'a', 'b', 'c'}\n"

    def test_not_in_list(self):
        out = _new(apply("m.py", "z = x not in [1, 2]\n", "t"))
        assert out == "z = x not in {1, 2}\n"

    def test_not_in_tuple(self):
        out = _new(apply("m.py", "z = x not in (1, 2)\n", "t"))
        assert out == "z = x not in {1, 2}\n"

    def test_mixed_constants(self):
        src = "z = x in [1, 'a', 2.5, True, None, b'q']\n"
        out = _new(apply("m.py", src, "t"))
        assert out == "z = x in {1, 'a', 2.5, True, None, b'q'}\n"

    def test_single_element_list(self):
        assert _new(apply("m.py", "z = x in [1]\n", "t")) == "z = x in {1}\n"

    def test_preserves_element_text_exactly(self):
        # Hex / underscore / quote styles must survive verbatim.
        src = 'z = x in [0xFF, 1_000, "q"]\n'
        out = _new(apply("m.py", src, "t"))
        assert out == 'z = x in {0xFF, 1_000, "q"}\n'

    def test_only_comparator_span_spliced(self):
        # Identical list text elsewhere on the line stays untouched.
        src = "z = ([1, 2], x in [1, 2])\n"
        out = _new(apply("m.py", src, "t"))
        assert out == "z = ([1, 2], x in {1, 2})\n"


class TestRefusals:
    def test_empty_list_refused(self):
        assert apply("m.py", "z = x in []\n", "t") is None

    def test_empty_tuple_refused(self):
        assert apply("m.py", "z = x in ()\n", "t") is None

    def test_name_element_refused(self):
        # A name is not a hashable constant at rewrite time.
        assert apply("m.py", "z = x in [a, b]\n", "t") is None

    def test_call_element_refused(self):
        assert apply("m.py", "z = x in [f(), 1]\n", "t") is None

    def test_list_element_refused(self):
        # An inner list is unhashable; refuse.
        assert apply("m.py", "z = x in [[1], 2]\n", "t") is None

    def test_dict_element_refused(self):
        assert apply("m.py", "z = x in [{1: 2}, 3]\n", "t") is None

    def test_starred_element_refused(self):
        assert apply("m.py", "z = x in [*a, 1]\n", "t") is None

    def test_eq_op_refused(self):
        # `==` is not a membership test.
        assert apply("m.py", "z = x == [1, 2]\n", "t") is None

    def test_comparator_name_refused(self):
        # `x in y` where y is a name, not a display.
        assert apply("m.py", "z = x in y\n", "t") is None

    def test_chained_membership_refused(self):
        # Multiple ops -> not a single membership compare.
        assert apply("m.py", "z = a in [1, 2] in c\n", "t") is None

    def test_non_membership_single_compare_refused(self):
        assert apply("m.py", "z = x < [1, 2]\n", "t") is None

    def test_comprehension_refused(self):
        assert apply("m.py", "z = x in [i for i in y]\n", "t") is None

    def test_syntax_error_returns_none(self):
        assert apply("m.py", "def (:\n", "t") is None

    def test_no_membership_noop(self):
        assert apply("m.py", "x = [1, 2, 3]\n", "t") is None


class TestInvariants:
    def test_deterministic(self):
        src = "a = x in [1, 2, 3]\nb = y not in ('p', 'q')\n"
        first = _new(apply("m.py", src, "t"))
        for _ in range(5):
            assert _new(apply("m.py", src, "t")) == first

    def test_output_always_parseable(self):
        sources = [
            "z = x in [1, 2, 3]\n",
            "z = x not in (1, 2)\n",
            "z = x in ['a', b'q', None, True]\n",
            "z = x in [a, b]\n",
            "z = x in []\n",
            "z = x == [1]\n",
            "if v in [1, 2] and w not in (3, 4):\n    pass\n",
        ]
        for src in sources:
            result = apply("m.py", src, "t")
            if result is not None:
                ast.parse(result.patch_requests[0]["new_content"])

    def test_semantic_equality_in(self):
        src = "x = 2 in [1, 2, 3]\ny = 9 in [1, 2, 3]\n"
        out = _new(apply("m.py", src, "t"))
        ns_old: dict = {}
        ns_new: dict = {}
        exec(compile(src, "<old>", "exec"), ns_old)
        exec(compile(out, "<new>", "exec"), ns_new)
        assert ns_old["x"] == ns_new["x"] is True
        assert ns_old["y"] == ns_new["y"] is False

    def test_semantic_equality_not_in(self):
        src = "x = 2 not in (1, 2, 3)\ny = 9 not in (1, 2, 3)\n"
        out = _new(apply("m.py", src, "t"))
        ns_old: dict = {}
        ns_new: dict = {}
        exec(compile(src, "<old>", "exec"), ns_old)
        exec(compile(out, "<new>", "exec"), ns_new)
        assert ns_old["x"] == ns_new["x"] is False
        assert ns_old["y"] == ns_new["y"] is True

    def test_duplicate_elements_membership_unchanged(self):
        # Set dedups, but `in`/`not in` results are identical to the list form.
        src = "x = 2 in [1, 2, 2, 3]\n"
        out = _new(apply("m.py", src, "t"))
        ns_old: dict = {}
        ns_new: dict = {}
        exec(compile(src, "<old>", "exec"), ns_old)
        exec(compile(out, "<new>", "exec"), ns_new)
        assert ns_old["x"] == ns_new["x"]
