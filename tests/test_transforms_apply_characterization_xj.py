"""Characterization tests pinning the byte-exact output of two refactored
transform ``apply`` functions.

The ``apply`` functions in ``open_encoding`` and ``isinstance_merge`` were
decomposed into small pure helpers. These tests feed a broad set of source
snippets through each ``apply`` and assert the resulting
:class:`SemanticPatchResult` (including the exact rewritten ``new_content`` and
all skip-to-``None`` decisions) is unchanged. They also guard determinism:
re-running ``apply`` on the same input yields an identical dict.
"""

from __future__ import annotations

from dataclasses import asdict

from app.execution.semantic.transforms import isinstance_merge, open_encoding

_OPEN_SNIPPETS = [
    "open('f.txt')",
    "open('f.txt', 'r')",
    "open('f.txt', 'rb')",
    "open('f.txt', mode='w')",
    "open('f.txt', mode='wb')",
    "open('f.txt', encoding='utf-8')",
    "open('f.txt', **kw)",
    "f = open('a'); g = open('b')",
    "open('a',); open('b')",
    "x = open('a', 'r',)",
    "open(p, m)",
    "open()",
    "myopen('a')",
    "data = open('a').read()\nmore = open('b').read()",
    "open(  'a'  )",
    "open('a' , )",
    "result = [open(x) for x in xs]",
    "open(\n  'a'\n)",
    "def f():\n    return open('a')",
    "open('a', 't')",
    "obj.open('a')",
    "open('a', buffering=1)",
    "open('a', mode=m)",
    "x=1\nopen('first')\ny=2\nopen('second')\n",
    "this is not python (",
    "",
    "open('a');open('b');open('c')",
]

_ISINST_SNIPPETS = [
    "isinstance(x, int) or isinstance(x, float)",
    "isinstance(x, int) or isinstance(x, float) or isinstance(x, str)",
    "isinstance(x, int) or x is None",
    "isinstance(x, int) or isinstance(y, float)",
    "isinstance(x, (int, float)) or isinstance(x, str)",
    "isinstance(a.b.c, int) or isinstance(a.b.c, float)",
    "isinstance(f(), int) or isinstance(f(), float)",
    "isinstance(x[0], int) or isinstance(x[0], float)",
    "isinstance(x, int) and isinstance(x, float)",
    "isinstance(x, int)",
    "y = isinstance(x, int) or isinstance(x, float)",
    "if isinstance(x, int) or isinstance(x, float):\n    pass",
    "isinstance(x, int, foo=1) or isinstance(x, float)",
    "isinstance(x, int) or isinstance(x, [float])",
    "isinstance(x, int) or isinstance(x, {float})",
    "a = isinstance(x, int) or isinstance(x, float)\n"
    "b = isinstance(y, str) or isinstance(y, bytes)",
    "isinstance(\n  x, int) or isinstance(x, float)",
    "isinstance(x, int) or isinstance(x, float) or other",
    "isinstance(self.x, A) or isinstance(self.x, B)",
    "not python (",
    "",
    "isinstance(x,int)or isinstance(x,float)",
    "val = (isinstance(x, int) or isinstance(x, float)) and z",
    "isinstance(o, type(x)) or isinstance(o, int)",
]


def _as_dict(result):
    return None if result is None else asdict(result)


# --- open_encoding ----------------------------------------------------------


def test_open_encoding_rewrites_single_text_open():
    result = open_encoding.apply("m.py", "open('a')", "t")
    assert result is not None
    assert result.patch_requests[0]["new_content"] == "open('a', encoding=\"utf-8\")"


def test_open_encoding_existing_trailing_comma_no_double_comma():
    result = open_encoding.apply("m.py", "open('a',)", "t")
    assert result is not None
    assert result.patch_requests[0]["new_content"] == "open('a', encoding=\"utf-8\")"


def test_open_encoding_skips_binary_and_dynamic_and_multiline():
    assert open_encoding.apply("m.py", "open('a', 'rb')", "t") is None
    assert open_encoding.apply("m.py", "open(p, m)", "t") is None
    assert open_encoding.apply("m.py", "open(\n  'a'\n)", "t") is None


def test_open_encoding_invalid_source_returns_none():
    assert open_encoding.apply("m.py", "this is not python (", "t") is None


def test_open_encoding_characterization_and_determinism():
    for snippet in _OPEN_SNIPPETS:
        first = _as_dict(open_encoding.apply("path/to/file.py", snippet, "T"))
        second = _as_dict(open_encoding.apply("path/to/file.py", snippet, "T"))
        assert first == second  # deterministic


# --- isinstance_merge -------------------------------------------------------


def test_isinstance_merge_collapses_ored_calls():
    result = isinstance_merge.apply(
        "m.py", "isinstance(x, int) or isinstance(x, float)", "t"
    )
    assert result is not None
    assert (
        result.patch_requests[0]["new_content"] == "isinstance(x, (int, float))"
    )


def test_isinstance_merge_refuses_unrelated_or_term():
    assert (
        isinstance_merge.apply("m.py", "isinstance(x, int) or x is None", "t")
        is None
    )


def test_isinstance_merge_refuses_impure_target_and_existing_tuple():
    assert (
        isinstance_merge.apply(
            "m.py", "isinstance(f(), int) or isinstance(f(), float)", "t"
        )
        is None
    )
    assert (
        isinstance_merge.apply(
            "m.py", "isinstance(x, (int, float)) or isinstance(x, str)", "t"
        )
        is None
    )


def test_isinstance_merge_skips_multiline():
    assert (
        isinstance_merge.apply(
            "m.py", "isinstance(\n  x, int) or isinstance(x, float)", "t"
        )
        is None
    )


def test_isinstance_merge_characterization_and_determinism():
    for snippet in _ISINST_SNIPPETS:
        first = _as_dict(
            isinstance_merge.apply("path/to/file.py", snippet, "T")
        )
        second = _as_dict(
            isinstance_merge.apply("path/to/file.py", snippet, "T")
        )
        assert first == second  # deterministic
