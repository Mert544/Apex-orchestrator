"""document-returns develop objective — the RETURN-VALUE image of document-raises:
the annotation-sourced, style-matching twin that documents the SUCCESS contract.

Where a PUBLIC function HAS a docstring AND an explicit ``-> T`` return annotation
but does NOT already document its return, splice a faithful return section into the
existing docstring rendering the DECLARED annotation ``T`` VERBATIM
(``ast.unparse(fn.returns)``), MATCHING the docstring's convention.

Covers: the alias-aware refuse heads (``-> None`` / ``-> NoReturn`` / ``typing.
NoReturn`` / a from-import alias; the generator/async-generator family incl.
``typing.``/``collections.abc.``/alias spellings); the documentable-type renderer
(verbatim ``dict[str, int]``, forward-ref strings); the decorator gate
(``@overload`` / ``@typing.overload`` / property setter & deleter; a plain
``@property`` getter APPLIES); the already-documented gate (every convention —
Sphinx ``:returns:`` / ``:return:`` / ``:rtype:``, Google ``Returns:`` / ``Yields:``,
NumPy underline); the convention detector + section renderer (Google default,
Sphinx field list); the multi-line splice + indent guard and the one-line EXPANSION
(prefix/quote preserved); CRLF preservation on BOTH paths; the public/test/private
NAME gate; the ``document_returns`` transform (lands, re-parses, runtime-value
unchanged, idempotent, deterministic, mixed-module lands only the qualifying
functions, unparseable no-op); the plan layer (lands + captures original, refuses
test/fixture/non-library, unreadable no-op); plus objective registration /
facet+manifest+soundness+move_value 1:1 parity (the FIVE registries), the COUNT pins
(80 / 38), and the soundness-corpus refusal. Every test is pure AST — no node, no
subprocess — so all run on the fast gate.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.objectives.document_returns import (
    _convention,
    _documentable_return_type,
    _documentable_target,
    _has_documented_return,
    _head_name,
    _import_aliases,
    _is_public,
    _is_refused_decoration,
    _line_ending,
    _section_lines,
    document_returns,
    plan_document_returns,
)

_PHRASE = "the annotated return type to document"


def _fn(src: str) -> ast.FunctionDef:
    """The first top-level function definition in ``src``."""
    return ast.parse(src).body[0]  # type: ignore[return-value]


def _method(src: str) -> ast.FunctionDef:
    """The first method of the first top-level class in ``src``."""
    return ast.parse(src).body[0].body[0]  # type: ignore[union-attr,return-value]


def _aliases(src: str) -> dict[str, str]:
    """The import-alias map for ``src``."""
    return _import_aliases(ast.parse(src))


# --- the alias-aware annotation HEAD resolver ---------------------------------

def test_head_name_peels_subscript_and_resolves_attribute():
    assert _head_name(_fn("def f() -> Iterator[int]: ...").returns, {}) == "Iterator"
    assert _head_name(_fn("def f() -> typing.NoReturn: ...").returns, {}) == "NoReturn"
    assert _head_name(
        _fn("def f() -> collections.abc.Iterator[int]: ...").returns, {}) == "Iterator"
    assert _head_name(_fn("def f() -> dict[str, int]: ...").returns, {}) == "dict"


def test_head_name_resolves_from_import_alias():
    al = {"NR": "NoReturn", "It": "Iterator"}
    assert _head_name(_fn("def f() -> NR: ...").returns, al) == "NoReturn"
    assert _head_name(_fn("def f() -> It[int]: ...").returns, al) == "Iterator"


def test_head_name_handles_none_and_forward_ref_string():
    assert _head_name(_fn("def f() -> None: ...").returns, {}) == "None"
    # A forward-ref string is re-parsed as a type expression and recursed.
    assert _head_name(_fn('def f() -> "Iterator[int]": ...').returns, {}) == "Iterator"
    assert _head_name(_fn('def f() -> "MyClass": ...').returns, {}) == "MyClass"


# --- the documentable-type renderer (verbatim, refuse the no-value heads) ------

def test_documentable_return_type_renders_verbatim():
    assert _documentable_return_type(
        _fn("def f() -> dict[str, int]: ..."), {}) == "dict[str, int]"
    assert _documentable_return_type(_fn("def f() -> int: ..."), {}) == "int"
    assert _documentable_return_type(_fn('def f() -> "Box": ...'), {}) == "'Box'"


def test_documentable_return_type_refuses_no_value_and_generators():
    for ann in ("None", "NoReturn", "typing.NoReturn", "Iterator[int]",
                "Iterable[int]", "Generator[int, None, None]", "AsyncIterator[int]",
                "AsyncIterable[int]", "AsyncGenerator[int, None]"):
        assert _documentable_return_type(_fn(f"def f() -> {ann}: ..."), {}) is None, ann


def test_documentable_return_type_refuses_missing_annotation():
    assert _documentable_return_type(_fn("def f(): ..."), {}) is None


def test_documentable_return_type_refuses_aliased_no_value():
    al = _aliases("from typing import NoReturn as NR\n")
    assert _documentable_return_type(_fn("def f() -> NR: ..."), al) is None
    al2 = _aliases("from collections.abc import Iterator as It\n")
    assert _documentable_return_type(_fn("def f() -> It[int]: ..."), al2) is None


# --- the decorator gate (overload / property setter / deleter) -----------------

def test_is_refused_decoration_flags_overload_and_property_mutators():
    assert _is_refused_decoration(_fn("@overload\ndef f(x: int) -> int: ..."))
    assert _is_refused_decoration(_fn("@typing.overload\ndef f(x: int) -> int: ..."))
    assert _is_refused_decoration(_method("class C:\n @x.setter\n def x(self, v) -> None: ..."))
    assert _is_refused_decoration(_method("class C:\n @x.deleter\n def x(self) -> None: ..."))


def test_is_refused_decoration_allows_plain_property_getter():
    assert not _is_refused_decoration(_method("class C:\n @property\n def x(self) -> int: ..."))
    assert not _is_refused_decoration(_fn("@staticmethod\ndef f() -> int: ..."))
    assert not _is_refused_decoration(_fn("def f() -> int: ..."))


# --- the already-documented gate (every convention) ---------------------------

def test_has_documented_return_matches_sphinx_google_numpy():
    assert _has_documented_return("Doc.\n\n:returns: x\n")
    assert _has_documented_return("Doc.\n\n:return: x\n")
    assert _has_documented_return("Doc.\n\n:rtype: int\n")
    assert _has_documented_return("Doc.\n\nReturns:\n    x\n")
    assert _has_documented_return("Doc.\n\nYields:\n    x\n")
    assert _has_documented_return("Doc.\n\nReturns\n-------\nint\n")
    assert _has_documented_return("Doc.\n\n    Return\n    ------\n    int\n")


def test_has_documented_return_ignores_prose_and_stray_dashes():
    assert not _has_documented_return("It returns the value, see below.\n")
    assert not _has_documented_return("Doc.\n\n    Notes\n    -----\n    stuff\n")
    assert not _has_documented_return("Just a one-line summary.")
    # Prose that merely begins with "Returns" but has NO colon is not a field.
    assert not _has_documented_return("Doc.\n\nReturns the answer to it.\n")


def test_has_documented_return_matches_inline_returns_form():
    # The INLINE ``Returns: <type>`` form document_signature / pin_return_type emit
    # (a colon FOLLOWED by content, not a bare section header) must also be detected
    # — else a second return section would be double-doc'd onto it. The denetçi P0.
    assert _has_documented_return("Doc.\n\nReturns: int\n")
    assert _has_documented_return("Doc.\n\n    Return: the value\n")
    assert _has_documented_return("Doc.\n\nYields: each row\n")


# --- the convention detector ---------------------------------------------------

def test_convention_detects_sphinx_field_list():
    assert _convention("Doc.\n\n:param x: in\n:returns: out\n") == "sphinx"
    assert _convention("Doc.\n\n:raises ValueError: when\n") == "sphinx"
    assert _convention("Doc.\n\n:rtype: int\n") == "sphinx"


def test_convention_defaults_google_for_sections_and_plain_prose():
    assert _convention("Doc.\n\nArgs:\n    x: in\n") == "google"
    assert _convention("Just plain prose, no sections at all.") == "google"
    assert _convention("") == "google"


# --- the section renderer + line-ending helper --------------------------------

def test_section_lines_google_and_sphinx_shapes():
    g = _section_lines("google", "    ", "int", "\n")
    assert g == ["\n", "    Returns:\n", "        int\n"]
    s = _section_lines("sphinx", "    ", "int", "\n")
    assert s == ["    :returns: int\n", "    :rtype: int\n"]


def test_section_lines_uses_the_given_terminator():
    g = _section_lines("google", "  ", "int", "\r\n")
    assert all(line.endswith("\r\n") for line in g)


def test_line_ending_detects_crlf_lf_cr():
    assert _line_ending("x\r\n") == "\r\n"
    assert _line_ending("x\n") == "\n"
    assert _line_ending("x\r") == "\r"
    assert _line_ending("x") == "\n"  # final line, no terminator -> default LF


# --- the public/non-test NAME gate --------------------------------------------

def test_is_public_accepts_plain_rejects_private_dunder_test():
    assert _is_public(_fn("def good() -> int: ..."))
    assert not _is_public(_fn("def _hidden() -> int: ..."))
    assert not _is_public(_fn("def __dunder__(self) -> int: ..."))
    assert not _is_public(_fn("def test_thing() -> int: ..."))


# --- the documentable-target combinator (the full gate stack) -----------------

def test_documentable_target_returns_edit_for_a_clean_candidate():
    src = 'def f() -> int:\n    """Doc.\n\n    More.\n    """\n    return 1\n'
    rows = src.splitlines(keepends=True)
    target = _documentable_target(_fn(src), rows, {})
    assert target is not None
    start, stop, repl = target
    assert (start, stop) == (4, 4)  # before the closing-quote line (index 4)
    assert any("Returns:" in line for line in repl)


def test_documentable_target_refuses_undocumented_function():
    src = "def f() -> int:\n    return 1\n"
    assert _documentable_target(_fn(src), src.splitlines(keepends=True), {}) is None


def test_documentable_target_refuses_unannotated_function():
    src = 'def f():\n    """Doc.\n\n    More.\n    """\n    return 1\n'
    assert _documentable_target(_fn(src), src.splitlines(keepends=True), {}) is None


# --- the apply path: Google (the default + matched section) -------------------

def test_apply_plain_prose_uses_the_google_default():
    src = 'def f() -> dict[str, int]:\n    """Build the map.\n\n    Detail.\n    """\n    return {}\n'
    out = document_returns(src)
    assert out is not None
    assert "\n    Returns:\n        dict[str, int]\n" in out
    assert ast.parse(out) is not None  # re-parses
    # The docstring stays the function's FIRST statement.
    assert ast.get_docstring(ast.parse(out).body[0]) is not None


def test_apply_google_section_docstring_gets_google_returns():
    src = ('def f(x) -> int:\n    """Do it.\n\n    Args:\n        x: the input.\n'
           '    """\n    return x\n')
    out = document_returns(src)
    assert out is not None
    assert "    Returns:\n        int\n" in out
    # NOT a Sphinx field jammed into the Google block.
    assert ":returns:" not in out


# --- the apply path: Sphinx (matched field list) ------------------------------

def test_apply_sphinx_docstring_gets_sphinx_returns_and_rtype():
    src = ('def f(x) -> str:\n    """Render.\n\n    :param x: the input.\n'
           '    """\n    return str(x)\n')
    out = document_returns(src)
    assert out is not None
    assert "    :returns: str\n" in out
    assert "    :rtype: str\n" in out
    # NOT a Google section jammed into the Sphinx field list.
    assert "Returns:" not in out


# --- the apply path: one-line docstring EXPANSION -----------------------------

def test_apply_expands_one_line_docstring():
    src = 'def f() -> int:\n    """Compute it."""\n    return 1\n'
    out = document_returns(src)
    assert out is not None
    assert out == (
        'def f() -> int:\n    """Compute it.\n\n'
        '    Returns:\n        int\n    """\n    return 1\n')


def test_apply_one_line_preserves_raw_prefix_and_quote_style():
    out_r = document_returns('def f() -> int:\n    r"""Doc."""\n    return 1\n')
    assert out_r is not None and out_r.splitlines()[1] == '    r"""Doc.'
    out_q = document_returns("def f() -> int:\n    '''Doc.'''\n    return 1\n")
    assert out_q is not None
    assert out_q.splitlines()[1] == "    '''Doc."  # opener keeps the ''' quote style
    assert "    '''\n" in out_q  # and so does the new closing-quote line


def test_apply_refuses_header_shared_one_liner():
    # `def f(): """Doc."""` reports the def header as the docstring-line indent.
    assert document_returns('def f() -> int: """Doc."""\n') is None


def test_apply_one_line_non_ascii_no_trailing_newline_no_stray_quote():
    # denetçi P0: col_offset / end_col_offset are UTF-8 BYTE offsets. A one-line
    # docstring with a non-ASCII char and NO trailing newline made the old str-index
    # slice over-read by one per non-ASCII char, keeping a stray ``"`` in the rebuilt
    # head (silent __doc__ corruption that still re-parsed). The body must round-trip
    # EXACTLY, with a Returns section added.
    src = 'def naive() -> bool:\n    """Naïve validation."""'  # final line, no \n
    out = document_returns(src)
    assert out is not None
    tree = ast.parse(out)  # must re-parse
    doc = ast.get_docstring(tree.body[0])
    assert doc is not None
    assert doc.startswith("Naïve validation.\n")  # NO stray trailing quote on body
    assert '."' not in doc.splitlines()[0]  # the summary line is clean
    assert "Returns:\n    bool" in doc


def test_apply_one_line_multi_non_ascii_skew_greater_than_one():
    # Two 2-byte chars (``é``×2) => a TWO-byte skew the old slice would show as ``""``.
    src = 'def f() -> bool:\n    """Résumé."""'  # no trailing newline
    out = document_returns(src)
    assert out is not None
    doc = ast.get_docstring(ast.parse(out).body[0])
    assert doc.splitlines()[0] == "Résumé."  # exactly the original body, no stray quotes
    assert "Returns:\n    bool" in doc


def test_apply_one_line_non_ascii_with_trailing_newline_is_clean():
    # The trailing-newline case the old code refused "by luck" (the over-read grabbed
    # the \n so the quote check failed) must now LAND a CORRECT expansion.
    src = 'def f() -> int:\n    """Naïve."""\n    return 1\n'
    out = document_returns(src)
    assert out is not None
    assert out.splitlines()[1] == '    """Naïve.'  # opener kept verbatim, no stray quote
    doc = ast.get_docstring(ast.parse(out).body[0])
    assert doc.splitlines()[0] == "Naïve."
    # A 4-byte astral char (emoji) round-trips too.
    out2 = document_returns('def g() -> int:\n    """Counts 🎯 hits."""\n    return 1\n')
    assert out2 is not None
    assert ast.get_docstring(ast.parse(out2).body[0]).splitlines()[0] == "Counts 🎯 hits."


# --- the apply path: @property getter, methods --------------------------------

def test_apply_documents_property_getter():
    src = ('class C:\n    @property\n    def x(self) -> int:\n'
           '        """The x value."""\n        return self._x\n')
    out = document_returns(src)
    assert out is not None
    assert "        Returns:\n            int\n" in out


# --- CRLF preservation on BOTH the multi-line and one-line paths ---------------

def test_apply_preserves_crlf_multiline():
    src = 'def f() -> int:\r\n    """Doc.\r\n\r\n    More.\r\n    """\r\n    return 1\r\n'
    out = document_returns(src)
    assert out is not None
    assert "\r\n" in out
    assert "\n" not in out.replace("\r\n", "")  # no bare LF leaked in


def test_apply_preserves_crlf_one_line_expansion():
    src = 'def f() -> int:\r\n    """Doc."""\r\n    return 1\r\n'
    out = document_returns(src)
    assert out is not None
    assert "\n" not in out.replace("\r\n", "")
    assert "    Returns:\r\n" in out


# --- content-on-close-line (dogfood P-class: mid-paragraph split) --------------
# A multi-line docstring whose LAST body line is ``    text."""`` (content + the
# closing quotes on the SAME line). The section must land at the END of the body —
# before the quotes, now moved onto their own line — never spliced mid-paragraph
# (the iter_statement_blocks dogfood: the old guard only checked the indent was
# whitespace, so ``    text."""`` passed and the section landed BEFORE the content).

def test_apply_content_on_close_line_lands_after_body_not_mid_paragraph():
    src = ('def f() -> dict[str, int]:\n'
           '    """Head line.\n\n'
           '    A paragraph whose final sentence ends with content and then\n'
           '    the closing triple quotes right here."""\n'
           '    return {}\n')
    orig_doc = ast.get_docstring(ast.parse(src).body[0])
    out = document_returns(src)
    assert out is not None
    new_doc = ast.get_docstring(ast.parse(out).body[0])  # must re-parse
    # the entire original body is preserved verbatim — only a section is GAINED
    assert new_doc.startswith(orig_doc), (orig_doc, new_doc)
    assert new_doc[len(orig_doc):] == "\n\nReturns:\n    dict[str, int]"
    # the section is AFTER the body content, and the close quotes moved to own line
    lines = out.splitlines()
    assert "    the closing triple quotes right here." in lines  # content intact, no quotes
    assert lines.index("    Returns:") > lines.index(
        "    the closing triple quotes right here.")
    assert lines[-2] == '    """'  # closing quotes now alone on their own line


def test_apply_content_on_close_line_preserves_quote_style_and_raw_prefix():
    # single-quote ''' style and a raw r''' prefix both carry through the split.
    out_sq = document_returns(
        "def f() -> int:\n    '''Head.\n\n    body ends here.'''\n    return 1\n")
    assert out_sq is not None
    assert out_sq.splitlines()[-2] == "    '''"  # close keeps the ''' style
    assert ast.get_docstring(ast.parse(out_sq).body[0]) == \
        "Head.\n\nbody ends here.\n\nReturns:\n    int"
    out_raw = document_returns(
        'def f() -> int:\n    r"""Head \\d.\n\n    body \\w end."""\n    return 1\n')
    assert out_raw is not None
    assert '    body \\w end.' in out_raw  # raw body line byte-identical (no unescape)
    assert ast.get_docstring(ast.parse(out_raw).body[0]).startswith(
        "Head \\d.\n\nbody \\w end.")


def test_apply_content_on_close_line_preserves_crlf():
    src = ('def f() -> int:\r\n    """Head.\r\n\r\n    body end here."""\r\n'
           '    return 1\r\n')
    out = document_returns(src)
    assert out is not None
    assert "\n" not in out.replace("\r\n", "")  # no bare LF leaked in
    assert "    Returns:\r\n" in out
    assert out.splitlines()[-2] == '    """'


def test_apply_content_on_close_line_refuses_trailing_comment():
    # bytes after the closing quotes are NOT just a line terminator -> refuse (a split
    # would strand the ``# c`` comment, corrupting the line).
    src = ('def f() -> int:\n    """Head.\n\n    body end."""  # c\n    return 1\n')
    assert ast.get_docstring(ast.parse(src).body[0]) is not None  # IS a docstring
    assert document_returns(src) is None


def test_apply_content_on_close_line_refuses_implicit_concatenation():
    # an implicitly-concatenated docstring (the closing quotes terminate only the LAST
    # part) cannot be split without orphaning the earlier part -> refuse both spellings.
    parens = ('def f() -> int:\n    ("""part one.\n\n'
              '    still one."""\n    """part two ends here.""")\n    return 1\n')
    assert ast.get_docstring(ast.parse(parens).body[0]) is not None
    assert document_returns(parens) is None
    backslash = ('def f() -> int:\n    """part one.""" \\\n'
                 '    """part two ends here."""\n    return 1\n')
    assert ast.get_docstring(ast.parse(backslash).body[0]) is not None
    assert document_returns(backslash) is None


def test_apply_dedicated_close_line_stays_byte_identical():
    # the closing """ alone on its own line — UNCHANGED behaviour (this is a fix, not a
    # rewrite): the section is inserted BEFORE that line, byte-for-byte as before.
    src = 'def f() -> int:\n    """Head.\n\n    body.\n    """\n    return 1\n'
    assert document_returns(src) == (
        'def f() -> int:\n    """Head.\n\n    body.\n\n'
        '    Returns:\n        int\n    """\n    return 1\n')


# --- the FULL refuse set on the transform (the denetçi corpus) ----------------

def test_transform_refuses_every_no_value_and_generator_return():
    body = '\n    """Doc.\n\n    Detail.\n    """\n    ...\n'
    for ann in ("None", "NoReturn", "Iterator[int]", "Iterable[int]",
                "Generator[int, None, None]", "AsyncIterator[int]",
                "AsyncGenerator[int, None]"):
        assert document_returns(f"def f() -> {ann}:{body}") is None, ann


def test_transform_refuses_aliased_no_value_and_generator():
    assert document_returns(
        'from typing import NoReturn as NR\n'
        'def f() -> NR:\n    """Doc.\n\n    D.\n    """\n    raise SystemExit\n') is None
    assert document_returns(
        'from collections.abc import Iterator as It\n'
        'def f() -> It[int]:\n    """Doc.\n\n    D.\n    """\n    yield 1\n') is None


def test_transform_refuses_overload_and_property_mutators():
    assert document_returns(
        'from typing import overload\n'
        '@overload\ndef f(x: int) -> int:\n    """Doc.\n\n    D.\n    """\n    ...\n') is None
    assert document_returns(
        'class C:\n    @x.setter\n    def x(self, v) -> None:\n'
        '        """Doc.\n\n        D.\n        """\n        self._x = v\n') is None
    assert document_returns(
        'class C:\n    @x.deleter\n    def x(self) -> None:\n'
        '        """Doc.\n\n        D.\n        """\n        del self._x\n') is None


def test_transform_refuses_already_documented_in_every_convention():
    head = 'def f() -> int:\n    """Doc.\n\n'
    tail = '\n    """\n    return 1\n'
    for body in ("    :returns: the n", "    :return: the n", "    :rtype: int",
                 "    Returns:\n        the n", "    Yields:\n        the n",
                 "    Returns: the n",  # the inline document_signature / pin form
                 "    Returns\n    -------\n    int"):
        assert document_returns(head + body + tail) is None, body


def test_transform_refuses_undocumented_unannotated_private_and_test():
    assert document_returns("def f() -> int:\n    return 1\n") is None  # no docstring
    assert document_returns(
        'def f():\n    """Doc.\n\n    D.\n    """\n    return 1\n') is None  # no annotation
    assert document_returns(
        'def _f() -> int:\n    """Doc.\n\n    D.\n    """\n    return 1\n') is None  # private
    assert document_returns(
        'def test_f() -> int:\n    """Doc.\n\n    D.\n    """\n    return 1\n') is None  # test_


# --- behaviour-identity / idempotence / determinism ---------------------------

def test_apply_is_runtime_value_identical():
    # A return section is docstring TEXT — it changes no runtime value. We exec the
    # before and after and confirm identical results; the docstring is updated.
    src = 'def f(n: int) -> int:\n    """Double n."""\n    return n * 2\n'
    out = document_returns(src)
    assert out is not None
    before, after = {}, {}
    exec(src, before)  # noqa: S102 - controlled test source
    exec(out, after)  # noqa: S102 - controlled test source
    assert before["f"](21) == after["f"](21) == 42
    assert "Returns:" in (after["f"].__doc__ or "")


def test_apply_is_idempotent():
    src = 'def f() -> int:\n    """Compute."""\n    return 1\n'
    once = document_returns(src)
    assert once is not None
    assert document_returns(once) is None  # rule-4 now fires -> byte-identical no-op


def test_apply_is_deterministic():
    src = 'def f(x) -> dict[str, int]:\n    """Build.\n\n    Args:\n        x: in.\n    """\n    return {}\n'
    assert document_returns(src) == document_returns(src)


def test_transform_mixed_module_lands_only_qualifying_functions():
    src = (
        'def a() -> int:\n    """A."""\n    return 1\n\n\n'
        'def b() -> str:\n    """B.\n\n    Returns:\n        x\n    """\n    return "x"\n\n\n'
        'def c():\n    """C."""\n    return 1\n')
    out = document_returns(src)
    assert out is not None
    tree = ast.parse(out)
    docs = {fn.name: ast.get_docstring(fn) for fn in tree.body}
    assert "Returns:" in docs["a"]          # annotated + undocumented -> landed
    assert docs["b"].count("Returns:") == 1  # already documented -> untouched
    assert "Returns:" not in docs["c"]       # unannotated -> untouched


def test_transform_no_op_on_unparseable_source():
    assert document_returns("def f( -> int:\n    pass\n") is None


# --- the plan layer -----------------------------------------------------------

def test_plan_lands_and_captures_original(tmp_path: Path):
    root = tmp_path
    (root / "mod.py").write_text(
        'def f() -> int:\n    """Compute."""\n    return 1\n', encoding="utf-8")
    plan = plan_document_returns(str(root), "mod.py")
    assert plan.new_contents  # a rewrite is planned
    assert "Returns:" in plan.new_contents["mod.py"]
    assert plan.originals["mod.py"] == 'def f() -> int:\n    """Compute."""\n    return 1\n'


def test_plan_is_noop_when_nothing_documentable(tmp_path: Path):
    (tmp_path / "mod.py").write_text(
        'def f() -> None:\n    """Boom."""\n    return None\n', encoding="utf-8")
    plan = plan_document_returns(str(tmp_path), "mod.py")
    assert not plan.new_contents


def test_plan_refuses_test_file(tmp_path: Path):
    (tmp_path / "test_mod.py").write_text(
        'def f() -> int:\n    """Compute."""\n    return 1\n', encoding="utf-8")
    plan = plan_document_returns(str(tmp_path), "test_mod.py")
    assert not plan.new_contents


def test_plan_lands_non_ascii_one_liner_without_corruption(tmp_path: Path):
    # The denetçi P0 lands via the plan layer too — a module-on-disk one-line
    # non-ASCII docstring must expand with a byte-perfect body, no stray quote.
    (tmp_path / "mod.py").write_text(
        'def f() -> bool:\n    """Naïve check."""\n    return True\n', encoding="utf-8")
    plan = plan_document_returns(str(tmp_path), "mod.py")
    assert plan.new_contents
    landed = plan.new_contents["mod.py"]
    assert ast.get_docstring(ast.parse(landed).body[0]).splitlines()[0] == "Naïve check."


# --- the FIVE-registry 1:1 parity + count pins --------------------------------

def test_objective_is_registered_and_pursuable():
    from app.engine.objective_compiler import available_objectives

    assert "document-returns" in set(available_objectives())


def test_facet_map_stays_in_sync_with_the_registry():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_facet_phrase_is_substring_order_safe():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    keys = list(FACET_OBJECTIVE_MAP)
    assert _PHRASE in keys
    for other in keys:
        if other == _PHRASE:
            continue
        assert _PHRASE not in other, f"{_PHRASE!r} is a substring of {other!r}"
        assert other not in _PHRASE, f"{other!r} is a substring of {_PHRASE!r}"


def test_facet_phrase_distinct_from_sibling_doc_phrases():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective("the public signature to document") == "document-signature"
    assert facet_to_objective("the documented return type to pin") == "pin-return-type"
    assert facet_to_objective("the raised exceptions to document") == "document-raises"
    assert facet_to_objective(_PHRASE) == "document-returns"


def test_facet_phrase_lives_in_the_signatures_and_types_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["signatures and types"]
    assert _PHRASE in ladder
    assert ladder[0] == "parameter meanings"  # originals still lead
    # appended AFTER the inferred-oracle sibling.
    assert ladder.index(_PHRASE) > ladder.index("the documented return type to pin")


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "document-returns" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


def test_move_value_tier_is_the_existing_docstring_splice_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("document_returns") == 0.66
    # The same doc-surface tier as its existing-docstring-splice sibling.
    assert move_value("document_returns") == move_value("pin_return_type")
    assert objective_value("document-returns") == 0.66
    assert objective_value("document-returns") != DEFAULT_VALUE  # not the fallback


def test_soundness_strategy_declared_and_not_scope_verify():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert "document-returns" in SOUNDNESS_STRATEGY
    assert SOUNDNESS_STRATEGY["document-returns"].startswith(
        "behavior-identical-docstring-only")
    assert "document-returns" not in SCOPE_VERIFY_ALLOWLIST
    assert strategy_subset_of_registry() == []  # no stale strategy entry


def test_north_star_and_soundness_audits_pass():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


def test_counts_are_thirty_eight_concrete_of_eighty():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    names = set(available_objectives())
    assert len(names) == 88  # 88 after js-cover-gaps (88th, CONCRETE) registered
    assert len(classify_objectives(names)["CONCRETE"]) == 43  # js-cover-gaps (88th) is CONCRETE


# --- the soundness-corpus refusal (the must-refuse shape) ---------------------

def test_refuses_on_returns_already_documented_corpus():
    # document-returns is NOT expensive (pure AST), so it is swept on the DEFAULT
    # cheap path. On the standing ``returns_already_documented`` shape every function
    # already records its return (one per convention), so the objective MUST refuse.
    from app.engine.objective_compiler import _objectives_map
    from app.engine.soundness_audit import _changed_files, _classify_cell, corpus_root, repo_root

    _fitness, moves = _objectives_map()["document-returns"]
    changed = _changed_files(moves, corpus_root(repo_root()) / "returns_already_documented")
    assert _classify_cell("returns_already_documented", "document-returns", changed) == "refused"
