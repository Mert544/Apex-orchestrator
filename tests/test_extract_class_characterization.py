"""Characterization tests pinning the byte-exact behavior of extract_class.apply.

These lock the output produced before the helper-decomposition refactor so any
future change that alters a rewrite string, a refuse condition, or the rationale
is caught. Generated rewrite content is asserted character-for-character.
"""
from __future__ import annotations

from app.execution.semantic.transforms import extract_class as m


def _result_tuple(r):
    if r is None:
        return None
    return (
        r.transform_type,
        tuple(r.rationale),
        tuple(
            (p["path"], p["new_content"], p["expected_old_content"])
            for p in r.patch_requests
        ),
    )


def test_extract_single_method_with_base_class_byte_exact():
    src = (
        "class Foo:\n"
        "    def a(self):\n"
        "        return 1\n"
        "\n"
        "    def b(self):\n"
        "        return 2\n"
    )
    r = m.apply("pkg/foo.py", src, ["a"], "Extracted", "Base")
    assert _result_tuple(r) == (
        "extract_class",
        ("Extracted methods ['a'] into class 'Extracted' in pkg/foo.py.",),
        (
            (
                "pkg/foo.py",
                "class Extracted(Base):\n"
                "    def a(self):\n"
                "        return 1\n"
                "\n"
                "class Foo:\n"
                "    def a(self):\n"
                "        return 1\n"
                "\n"
                "    def b(self):\n"
                "        return 2\n",
                src,
            ),
        ),
    )


def test_extract_async_method_no_base():
    src = (
        "class Bar(object):\n"
        "    def m1(self):\n"
        "        pass\n"
        "    async def m2(self):\n"
        "        await x()\n"
    )
    r = m.apply("a.py", src, ["m2"], "Moved", None)
    new = r.patch_requests[0]["new_content"]
    assert new == (
        "class Moved:\n"
        "    async def m2(self):\n"
        "        await x()\n"
        "\n"
        "class Bar(object):\n"
        "    def m1(self):\n"
        "        pass\n"
        "    async def m2(self):\n"
        "        await x()\n"
    )
    assert r.rationale == ["Extracted methods ['m2'] into class 'Moved' in a.py."]


def test_nested_indented_class_preserves_indent():
    src = (
        "def outer():\n"
        "    class Inner:\n"
        "        def helper(self):\n"
        "            return 7\n"
        "        def keep(self):\n"
        "            return 8\n"
    )
    r = m.apply("n.py", src, ["helper"], "H", None)
    assert r.patch_requests[0]["new_content"] == (
        "def outer():\n"
        "    class H:\n"
        "        def helper(self):\n"
        "            return 7\n"
        "\n"
        "    class Inner:\n"
        "        def helper(self):\n"
        "            return 7\n"
        "        def keep(self):\n"
        "            return 8\n"
    )


def test_blank_lines_inside_method_become_bare_newline():
    src = (
        "class Baz:\n"
        "    def big(self):\n"
        "\n"
        "        a = 1\n"
        "        return a\n"
    )
    r = m.apply("b.py", src, ["big"], "Big", None)
    # The blank line inside the extracted method is rewritten to a bare "\n"
    # then re-prefixed with body_indent, yielding "    \n"; the original copy
    # left in place keeps its untouched blank "\n".
    assert r.patch_requests[0]["new_content"] == (
        "class Big:\n"
        "    def big(self):\n"
        "    \n"
        "        a = 1\n"
        "        return a\n"
        "\n"
        "class Baz:\n"
        "    def big(self):\n"
        "\n"
        "        a = 1\n"
        "        return a\n"
    )


def test_refuse_no_methods():
    assert m.apply("f.py", "class C:\n    def a(self):\n        pass\n", [], "X", None) is None


def test_refuse_no_class_name():
    assert m.apply("f.py", "class C:\n    def a(self):\n        pass\n", ["a"], "", None) is None


def test_refuse_method_not_found():
    assert m.apply("f.py", "class C:\n    def a(self):\n        pass\n", ["zzz"], "X", None) is None


def test_refuse_no_class_in_source():
    assert m.apply("f.py", "def f():\n    return 1\n", ["a"], "X", None) is None


def test_refuse_syntax_error():
    assert m.apply("f.py", "class : broken", ["a"], "X", None) is None


def test_refuse_empty_source():
    assert m.apply("f.py", "", ["a"], "X", None) is None
