"""document-param develop objective — the PARAMETER image of document-returns: the
declared-annotation-sourced, style-matching twin that documents the INPUT contract.

Where a PUBLIC function HAS a docstring AND at least one parameter carrying a DECLARED
type annotation but does NOT already document its parameters, splice a faithful
``Args:`` section into the existing docstring listing one ``name (TYPE):`` line per
declared-annotated parameter, the type rendered VERBATIM via ``ast.unparse``, MATCHING
the docstring's convention. The Python mirror of js-document-param-types (``@param {T}
name``) and the input-contract sibling of document-returns (``Returns:``).

Covers: the already-documented gate (every convention — Google ``Args:`` /
``Arguments:`` / ``Parameters:``, Sphinx ``:param:`` / ``:type:`` / ``:arg:`` /
``:keyword:``, NumPy underline) AND the PARTIAL case (some params documented, not all
→ refuse WHOLE); the honesty gate (no declared annotation anywhere → refuse; only
annotated params get a line, an unannotated one is SKIPPED — never a bare ``name``
line); the receiver filter (``self`` / ``cls`` dropped); the ``*args`` / ``**kwargs``
collector gate (a bare collector is skipped, an UNREADABLE-annotation collector refuses
the WHOLE function); the decorator gate (``@overload`` / ``@typing.overload`` / property
setter & deleter; a plain ``@property`` getter APPLIES); the convention detector +
section renderer (Google default, Sphinx field list); the multi-line splice + indent
guard and the one-line EXPANSION (prefix/quote preserved); byte-aware non-ASCII / astral
one-liners; CRLF preservation on BOTH paths; the public/test/private NAME gate; the
``document_param`` transform (lands, re-parses, runtime-value unchanged, idempotent,
deterministic, mixed-module lands only qualifying functions, unparseable no-op);
COMPOSITION with document-returns in BOTH orders (no double-doc, no corruption); the
plan layer (lands + captures original, refuses test/fixture/non-library, unreadable
no-op); plus objective registration / facet+manifest+soundness+move_value 1:1 parity
(the FIVE registries), the COUNT pins (81 / 39), and the soundness-corpus refusals
(``params_already_documented`` + ``partial_params_documented``). Every test is pure AST
— no node, no subprocess — so all run on the fast gate.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.objectives.document_param import (
    _annotated_params,
    _collector_blocks,
    _convention,
    _documentable_target,
    _has_documented_params,
    _is_public,
    _is_refused_decoration,
    _is_simple_name_annotation,
    _positional_and_kw_args,
    _section_lines,
    document_param,
    plan_document_param,
)
from app.execution.objectives.document_returns import document_returns

_PHRASE = "the parameter types to document"


def _fn(src: str) -> ast.FunctionDef:
    """The first top-level function definition in ``src``."""
    return ast.parse(src).body[0]  # type: ignore[return-value]


def _method(src: str) -> ast.FunctionDef:
    """The first method of the first top-level class in ``src``."""
    return ast.parse(src).body[0].body[0]  # type: ignore[union-attr,return-value]


# --- the positional/keyword arg collector (receiver filtered) -----------------

def test_positional_and_kw_args_drops_receiver_keeps_rest():
    names = [a.arg for a in _positional_and_kw_args(
        _method("class C:\n def m(self, a, b, *, c): ..."))]
    assert names == ["a", "b", "c"]  # self dropped, kw-only kept
    cls_names = [a.arg for a in _positional_and_kw_args(
        _method("class C:\n def m(cls, x): ..."))]
    assert cls_names == ["x"]  # cls dropped too


def test_positional_and_kw_args_keeps_posonly_and_plain():
    names = [a.arg for a in _positional_and_kw_args(
        _fn("def f(a, b, /, c, d): ..."))]
    assert names == ["a", "b", "c", "d"]
    # A bare top-level function whose first arg is literally named self is NOT a
    # method, but the receiver filter still drops a leading self/cls by name — a
    # conservative, deterministic rule (such a function is vanishingly rare).
    assert [a.arg for a in _positional_and_kw_args(_fn("def f(self, x): ..."))] == ["x"]


# --- the simple-name annotation gate (for *args/**kwargs) ---------------------

def test_is_simple_name_annotation_accepts_name_attr_subscript():
    assert _is_simple_name_annotation(_fn("def f() -> int: ...").returns)
    assert _is_simple_name_annotation(_fn("def f() -> typing.Any: ...").returns)
    assert _is_simple_name_annotation(_fn("def f() -> list[int]: ...").returns)
    assert _is_simple_name_annotation(_fn("def f() -> dict[str, int]: ...").returns)


def test_is_simple_name_annotation_rejects_non_name_shapes():
    # A string-constant subscript base, a tuple, a call — none is a readable name.
    assert not _is_simple_name_annotation(_fn('def f() -> "x"[int]: ...').returns)
    assert not _is_simple_name_annotation(_fn("def f() -> (int, str): ...").returns)


def test_collector_blocks_only_on_unreadable_collector_annotation():
    # A bare *args / **kwargs (no annotation) does NOT block.
    assert not _collector_blocks(_fn("def f(x, *args, **kw): ..."))
    # A simple-name *args / **kwargs annotation does NOT block.
    assert not _collector_blocks(_fn("def f(*args: int, **kw: str): ..."))
    assert not _collector_blocks(_fn("def f(*args: tuple[int, ...]): ..."))
    # An UNREADABLE collector annotation (a string-subscript) blocks the function.
    assert _collector_blocks(_fn('def f(*args: "weird"[int]): ...'))


# --- the annotated-param renderer (honesty gate + skip-unannotated) ------------

def test_annotated_params_renders_declared_pairs_verbatim():
    pairs = _annotated_params(_fn("def f(x: int, y: dict[str, int]): ..."))
    assert pairs == [("x", "int"), ("y", "dict[str, int]")]


def test_annotated_params_skips_unannotated_keeps_only_typed():
    # The honesty gate: a name-only line is signature-restatement noise, so an
    # unannotated parameter is dropped — only the typed ones get a pair.
    assert _annotated_params(_fn("def f(x: int, y): ...")) == [("x", "int")]


def test_annotated_params_refuses_when_no_param_is_annotated():
    assert _annotated_params(_fn("def f(x, y): ...")) is None  # honest no-op


def test_annotated_params_refuses_no_params_or_receiver_only():
    assert _annotated_params(_fn("def f(): ...")) is None
    assert _annotated_params(_method("class C:\n def m(self): ...")) is None
    assert _annotated_params(_method("class C:\n def m(cls): ...")) is None


def test_annotated_params_refuses_unreadable_collector():
    assert _annotated_params(_fn('def f(x: int, *args: "weird"[int]): ...')) is None


# --- the already-documented gate (every convention + the partial case) --------

def test_has_documented_params_matches_google_sphinx_numpy():
    assert _has_documented_params("Doc.\n\nArgs:\n    x: in\n")
    assert _has_documented_params("Doc.\n\nArguments:\n    x: in\n")
    assert _has_documented_params("Doc.\n\nParameters:\n    x: in\n")
    assert _has_documented_params("Doc.\n\n:param x: in\n")
    assert _has_documented_params("Doc.\n\n:parameter x: in\n")
    assert _has_documented_params("Doc.\n\n:type x: int\n")
    assert _has_documented_params("Doc.\n\n:arg x: in\n")
    assert _has_documented_params("Doc.\n\n:keyword x: in\n")
    assert _has_documented_params("Doc.\n\nParameters\n----------\nx : int\n")
    assert _has_documented_params("Doc.\n\n    Parameters\n    ----------\n    x : int\n")


def test_has_documented_params_single_field_trips_partial_case():
    # A SINGLE :param: among missing siblings still trips the gate — so a half-filled
    # block refuses WHOLE rather than being merged into (the denetçi P0).
    assert _has_documented_params("Doc.\n\n:param only_one: in\n")
    # A single Google Args: line likewise.
    assert _has_documented_params("Doc.\n\nArgs:\n    only_one: in\n")


def test_has_documented_params_ignores_prose_and_stray_dashes():
    assert not _has_documented_params("It takes parameters, see below.\n")
    assert not _has_documented_params("Doc.\n\n    Notes\n    -----\n    stuff\n")
    assert not _has_documented_params("Just a one-line summary.")
    # A word-boundary guard keeps a non-field colon word out.
    assert not _has_documented_params("Doc.\n\n:parameters_note: not a field\n")
    # Prose that merely begins with "Parameters" but no underline is not a section.
    assert not _has_documented_params("Doc.\n\nParameters are validated first.\n")


# --- the convention detector + section renderer -------------------------------

def test_convention_detects_sphinx_and_defaults_google():
    assert _convention("Doc.\n\n:param x: in\n") == "sphinx"
    assert _convention("Doc.\n\nArgs:\n    x: in\n") == "google"
    assert _convention("Just plain prose.") == "google"


def test_section_lines_google_and_sphinx_shapes():
    g = _section_lines("google", "    ", [("x", "int"), ("y", "str")], "\n")
    assert g == ["\n", "    Args:\n", "        x (int):\n", "        y (str):\n"]
    s = _section_lines("sphinx", "    ", [("x", "int")], "\n")
    assert s == ["    :param x:\n", "    :type x: int\n"]


def test_section_lines_uses_the_given_terminator():
    g = _section_lines("google", "  ", [("x", "int")], "\r\n")
    assert all(line.endswith("\r\n") for line in g)


# --- the decorator + name gates (reused from the doc-family) ------------------

def test_is_refused_decoration_flags_overload_and_property_mutators():
    assert _is_refused_decoration(_fn("@overload\ndef f(x: int): ..."))
    assert _is_refused_decoration(_fn("@typing.overload\ndef f(x: int): ..."))
    assert _is_refused_decoration(_method("class C:\n @x.setter\n def x(self, v: int): ..."))
    assert _is_refused_decoration(_method("class C:\n @x.deleter\n def x(self): ..."))


def test_is_refused_decoration_allows_plain_property_getter():
    assert not _is_refused_decoration(_method("class C:\n @property\n def x(self) -> int: ..."))


def test_is_public_accepts_plain_rejects_private_dunder_test():
    assert _is_public(_fn("def good(x: int): ..."))
    assert not _is_public(_fn("def _hidden(x: int): ..."))
    assert not _is_public(_fn("def __dunder__(self, x: int): ..."))
    assert not _is_public(_fn("def test_thing(x: int): ..."))


# --- the documentable-target combinator (the full gate stack) -----------------

def test_documentable_target_returns_edit_for_a_clean_candidate():
    src = 'def f(x: int):\n    """Doc.\n\n    More.\n    """\n    return x\n'
    rows = src.splitlines(keepends=True)
    target = _documentable_target(_fn(src), rows)
    assert target is not None
    start, stop, repl = target
    assert (start, stop) == (4, 4)  # before the closing-quote line (index 4)
    assert any("Args:" in line for line in repl)


def test_documentable_target_refuses_undocumented_and_unannotated():
    assert _documentable_target(
        _fn("def f(x: int):\n    return x\n"),
        "def f(x: int):\n    return x\n".splitlines(keepends=True)) is None
    src = 'def f(x):\n    """Doc.\n\n    More.\n    """\n    return x\n'
    assert _documentable_target(_fn(src), src.splitlines(keepends=True)) is None


# --- the apply path: Google (the default + matched section) -------------------

def test_apply_plain_prose_uses_the_google_default():
    src = ('def f(x: int, y: str):\n    """Combine.\n\n    Detail.\n    """\n'
           '    return y\n')
    out = document_param(src)
    assert out is not None
    assert "\n    Args:\n        x (int):\n        y (str):\n" in out
    assert ast.parse(out) is not None
    assert ast.get_docstring(ast.parse(out).body[0]) is not None
    assert ":param" not in out  # NOT a Sphinx field jammed into a Google block


def test_apply_google_section_docstring_gets_google_args():
    src = ('def f(x: int) -> int:\n    """Do it.\n\n    Returns:\n        the result.\n'
           '    """\n    return x\n')
    out = document_param(src)
    assert out is not None
    assert "    Args:\n        x (int):\n" in out
    assert ":param" not in out


# --- the apply path: Sphinx (matched field list) ------------------------------

def test_apply_sphinx_docstring_gets_sphinx_param_and_type():
    src = ('def f(x: int):\n    """Render.\n\n    :raises ValueError: when.\n'
           '    """\n    return x\n')
    out = document_param(src)
    assert out is not None
    assert "    :param x:\n" in out
    assert "    :type x: int\n" in out
    assert "Args:" not in out  # NOT a Google section jammed into a Sphinx field list


def test_apply_skips_unannotated_param_emits_only_typed_line():
    src = 'def f(x: int, y):\n    """Doc.\n\n    D.\n    """\n    return x\n'
    out = document_param(src)
    assert out is not None
    assert "x (int):" in out
    assert "y (" not in out  # the unannotated param gets NO line (no bare name)


# --- the apply path: one-line docstring EXPANSION -----------------------------

def test_apply_expands_one_line_docstring():
    src = 'def f(n: int):\n    """Double."""\n    return n\n'
    out = document_param(src)
    assert out == (
        'def f(n: int):\n    """Double.\n\n'
        '    Args:\n        n (int):\n    """\n    return n\n')


def test_apply_one_line_preserves_raw_prefix_and_quote_style():
    out_r = document_param('def f(x: int):\n    r"""Doc."""\n    return x\n')
    assert out_r is not None and out_r.splitlines()[1] == '    r"""Doc.'
    out_q = document_param("def f(x: int):\n    '''Doc.'''\n    return x\n")
    assert out_q is not None
    assert out_q.splitlines()[1] == "    '''Doc."
    assert "    '''\n" in out_q


def test_apply_refuses_header_shared_one_liner():
    assert document_param('def f(x: int): """Doc."""\n') is None


# --- byte-aware non-ASCII / astral one-liners (denetçi P0) --------------------

def test_apply_one_line_non_ascii_no_trailing_newline_no_stray_quote():
    # col_offset / end_col_offset are UTF-8 BYTE offsets — a non-ASCII one-liner with
    # NO trailing newline must round-trip EXACTLY, with an Args section added.
    src = 'def naive(x: int):\n    """Naïve check."""'  # final line, no newline
    out = document_param(src)
    assert out is not None
    doc = ast.get_docstring(ast.parse(out).body[0])
    assert doc is not None
    assert doc.startswith("Naïve check.\n")  # NO stray trailing quote
    assert '."' not in doc.splitlines()[0]
    assert "Args:\n    x (int):" in doc


def test_apply_one_line_multi_non_ascii_skew_greater_than_one():
    src = 'def f(x: int):\n    """Résumé."""'  # two 2-byte chars, no trailing newline
    out = document_param(src)
    assert out is not None
    doc = ast.get_docstring(ast.parse(out).body[0])
    assert doc.splitlines()[0] == "Résumé."
    assert "Args:\n    x (int):" in doc


def test_apply_one_line_astral_emoji_round_trips():
    src = 'def g(x: int):\n    """Counts 🎯 hits."""\n    return x\n'
    out = document_param(src)
    assert out is not None
    assert ast.get_docstring(ast.parse(out).body[0]).splitlines()[0] == "Counts 🎯 hits."
    assert out.splitlines()[1] == '    """Counts 🎯 hits.'  # opener kept verbatim


# --- @property getter, methods (self filtered) --------------------------------

def test_apply_documents_property_getter_and_method_drops_self():
    src = ('class C:\n    @property\n    def x(self) -> int:\n'
           '        """The x value."""\n        return self._x\n')
    # A property getter with NO documentable parameter (only self) is refused.
    assert document_param(src) is None
    src2 = ('class C:\n    def scale(self, factor: float):\n'
            '        """Scale it."""\n        return factor\n')
    out = document_param(src2)
    assert out is not None
    assert "            factor (float):\n" in out
    assert "self (" not in out


# --- CRLF preservation on BOTH the multi-line and one-line paths ---------------

def test_apply_preserves_crlf_multiline():
    src = 'def f(x: int):\r\n    """Doc.\r\n\r\n    More.\r\n    """\r\n    return x\r\n'
    out = document_param(src)
    assert out is not None
    assert "\r\n" in out
    assert "\n" not in out.replace("\r\n", "")


def test_apply_preserves_crlf_one_line_expansion():
    src = 'def f(x: int):\r\n    """Doc."""\r\n    return x\r\n'
    out = document_param(src)
    assert out is not None
    assert "\n" not in out.replace("\r\n", "")
    assert "    Args:\r\n" in out


# --- content-on-close-line (dogfood P-class: mid-paragraph split) --------------
# The SHARED splice_section_multiline fix: a multi-line docstring whose LAST body line
# is ``    text."""`` (content + the closing quotes on the SAME line) must take the
# ``Args:`` section at the END of the body — before the quotes moved to their own line —
# never spliced mid-paragraph.

def test_apply_content_on_close_line_lands_after_body_not_mid_paragraph():
    src = ('def f(data: bytes):\n'
           '    """Head line.\n\n'
           '    A paragraph whose final sentence ends with content and then\n'
           '    the closing triple quotes right here."""\n'
           '    return data\n')
    orig_doc = ast.get_docstring(ast.parse(src).body[0])
    out = document_param(src)
    assert out is not None
    new_doc = ast.get_docstring(ast.parse(out).body[0])  # must re-parse
    assert new_doc.startswith(orig_doc), (orig_doc, new_doc)
    assert new_doc[len(orig_doc):] == "\n\nArgs:\n    data (bytes):"
    lines = out.splitlines()
    assert "    the closing triple quotes right here." in lines  # content intact
    assert lines.index("    Args:") > lines.index(
        "    the closing triple quotes right here.")
    assert lines[-2] == '    """'  # closing quotes moved to their own line


def test_apply_content_on_close_line_preserves_crlf():
    src = ('def f(x: int):\r\n    """Head.\r\n\r\n    body end here."""\r\n'
           '    return x\r\n')
    out = document_param(src)
    assert out is not None
    assert "\n" not in out.replace("\r\n", "")
    assert "    Args:\r\n" in out
    assert out.splitlines()[-2] == '    """'


def test_apply_content_on_close_line_refuses_trailing_comment_and_concat():
    cmt = ('def f(x: int):\n    """Head.\n\n    body end."""  # c\n    return x\n')
    assert ast.get_docstring(ast.parse(cmt).body[0]) is not None
    assert document_param(cmt) is None
    concat = ('def f(x: int):\n    """one.""" \\\n'
              '    """two ends here."""\n    return x\n')
    assert ast.get_docstring(ast.parse(concat).body[0]) is not None
    assert document_param(concat) is None


def test_apply_dedicated_close_line_stays_byte_identical():
    src = 'def f(x: int):\n    """Head.\n\n    body.\n    """\n    return x\n'
    assert document_param(src) == (
        'def f(x: int):\n    """Head.\n\n    body.\n\n'
        '    Args:\n        x (int):\n    """\n    return x\n')


# --- the FULL refuse set on the transform (the denetçi corpus) ----------------

def test_transform_refuses_already_documented_in_every_convention():
    head = 'def f(x: int):\n    """Doc.\n\n'
    tail = '\n    """\n    return x\n'
    for body in ("    Args:\n        x (int): in", "    Arguments:\n        x: in",
                 "    Parameters:\n        x: in", "    :param x: in",
                 "    :type x: int", "    :arg x: in", "    :keyword x: in",
                 "    Parameters\n    ----------\n    x : int"):
        assert document_param(head + body + tail) is None, body


def test_transform_refuses_partial_documentation_whole_function():
    # Some params documented, not all -> REFUSE the WHOLE function (never half-fill).
    google_partial = ('def f(a: int, b: str):\n    """Doc.\n\n'
                      '    Args:\n        a (int): only a.\n    """\n    return b\n')
    assert document_param(google_partial) is None
    sphinx_partial = ('def f(host: str, port: int):\n    """Doc.\n\n'
                      '    :param host: only host.\n    :type host: str\n'
                      '    """\n    return host\n')
    assert document_param(sphinx_partial) is None


def test_transform_refuses_no_declared_param_annotation():
    assert document_param(
        'def f(x, y):\n    """Doc.\n\n    D.\n    """\n    return x\n') is None


def test_transform_refuses_no_params_or_receiver_only():
    assert document_param(
        'def f():\n    """Doc.\n\n    D.\n    """\n    return 1\n') is None
    assert document_param(
        'class C:\n    def m(self):\n        """Doc.\n\n        D.\n        """\n'
        '        return 1\n') is None


def test_transform_refuses_unreadable_collector_annotation():
    assert document_param(
        'def f(x: int, *args: "weird"[int]):\n    """Doc.\n\n    D.\n    """\n'
        '    return x\n') is None


def test_transform_skips_bare_collectors_documents_typed_params():
    src = 'def f(x: int, *args, **kw):\n    """Doc.\n\n    D.\n    """\n    return x\n'
    out = document_param(src)
    assert out is not None
    assert "x (int):" in out
    # The bare collectors get NO Args line (they are unannotated).
    doc = ast.get_docstring(ast.parse(out).body[0])
    args_block = doc.split("Args:")[1]
    assert "args" not in args_block and "kw" not in args_block


def test_transform_refuses_overload_and_property_mutators():
    assert document_param(
        'from typing import overload\n'
        '@overload\ndef f(x: int):\n    """Doc.\n\n    D.\n    """\n    ...\n') is None
    assert document_param(
        'class C:\n    @x.setter\n    def x(self, v: int):\n'
        '        """Doc.\n\n        D.\n        """\n        self._x = v\n') is None
    assert document_param(
        'class C:\n    @x.deleter\n    def x(self):\n'
        '        """Doc.\n\n        D.\n        """\n        del self._x\n') is None


def test_transform_refuses_undocumented_private_and_test():
    assert document_param("def f(x: int):\n    return x\n") is None  # no docstring
    assert document_param(
        'def _f(x: int):\n    """Doc.\n\n    D.\n    """\n    return x\n') is None
    assert document_param(
        'def test_f(x: int):\n    """Doc.\n\n    D.\n    """\n    return x\n') is None


# --- behaviour-identity / idempotence / determinism / composition -------------

def test_apply_is_runtime_value_identical():
    src = 'def f(n: int):\n    """Double n."""\n    return n * 2\n'
    out = document_param(src)
    assert out is not None
    before, after = {}, {}
    exec(src, before)  # noqa: S102 - controlled test source
    exec(out, after)  # noqa: S102 - controlled test source
    assert before["f"](21) == after["f"](21) == 42
    assert "Args:" in (after["f"].__doc__ or "")


def test_apply_is_idempotent():
    src = 'def f(x: int):\n    """Compute."""\n    return x\n'
    once = document_param(src)
    assert once is not None
    assert document_param(once) is None  # the already-documented gate now fires


def test_apply_is_deterministic():
    src = ('def f(x: int, y: dict[str, int]):\n    """Build.\n\n    Detail.\n'
           '    """\n    return y\n')
    assert document_param(src) == document_param(src)


def test_transform_mixed_module_lands_only_qualifying_functions():
    src = (
        'def a(x: int):\n    """A."""\n    return x\n\n\n'
        'def b(y: str):\n    """B.\n\n    Args:\n        y (str): in.\n    """\n'
        '    return y\n\n\n'
        'def c(z):\n    """C."""\n    return z\n')
    out = document_param(src)
    assert out is not None
    docs = {fn.name: ast.get_docstring(fn) for fn in ast.parse(out).body}
    assert "Args:" in docs["a"]               # annotated + undocumented -> landed
    assert docs["b"].count("Args:") == 1       # already documented -> untouched
    assert "Args:" not in docs["c"]            # unannotated -> untouched


def test_compose_with_document_returns_both_orders_no_double_doc():
    src = ('def f(x: int) -> bool:\n    """Check.\n\n    Detail.\n    """\n'
           '    return bool(x)\n')
    # Order 1: returns first, then param.
    a = document_param(document_returns(src))
    assert a is not None
    assert a.count("Returns:") == 1 and a.count("Args:") == 1
    assert ast.get_docstring(ast.parse(a).body[0]) is not None
    # Order 2: param first, then returns.
    b = document_returns(document_param(src))
    assert b is not None
    assert b.count("Returns:") == 1 and b.count("Args:") == 1
    assert ast.get_docstring(ast.parse(b).body[0]) is not None
    # Both compositions are now fully documented -> both objectives refuse again.
    assert document_param(a) is None and document_returns(a) is None
    assert document_param(b) is None and document_returns(b) is None


def test_transform_no_op_on_unparseable_source():
    assert document_param("def f(x: int -> :\n    pass\n") is None


# --- the plan layer -----------------------------------------------------------

def test_plan_lands_and_captures_original(tmp_path: Path):
    (tmp_path / "mod.py").write_text(
        'def f(x: int):\n    """Compute."""\n    return x\n', encoding="utf-8")
    plan = plan_document_param(str(tmp_path), "mod.py")
    assert plan.new_contents
    assert "Args:" in plan.new_contents["mod.py"]
    assert plan.originals["mod.py"] == 'def f(x: int):\n    """Compute."""\n    return x\n'


def test_plan_is_noop_when_nothing_documentable(tmp_path: Path):
    (tmp_path / "mod.py").write_text(
        'def f(x):\n    """No types."""\n    return x\n', encoding="utf-8")
    plan = plan_document_param(str(tmp_path), "mod.py")
    assert not plan.new_contents


def test_plan_refuses_test_file(tmp_path: Path):
    (tmp_path / "test_mod.py").write_text(
        'def f(x: int):\n    """Compute."""\n    return x\n', encoding="utf-8")
    plan = plan_document_param(str(tmp_path), "test_mod.py")
    assert not plan.new_contents


def test_plan_lands_non_ascii_one_liner_without_corruption(tmp_path: Path):
    (tmp_path / "mod.py").write_text(
        'def f(x: int):\n    """Naïve check."""\n    return True\n', encoding="utf-8")
    plan = plan_document_param(str(tmp_path), "mod.py")
    assert plan.new_contents
    landed = plan.new_contents["mod.py"]
    assert ast.get_docstring(ast.parse(landed).body[0]).splitlines()[0] == "Naïve check."


# --- the FIVE-registry 1:1 parity + count pins --------------------------------

def test_objective_is_registered_and_pursuable():
    from app.engine.objective_compiler import available_objectives

    assert "document-param" in set(available_objectives())


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

    assert facet_to_objective("the annotated return type to document") == "document-returns"
    assert facet_to_objective(
        "the exported parameter types to document in jsdoc") == "js-document-param-types"
    assert facet_to_objective(_PHRASE) == "document-param"


def test_facet_phrase_lives_in_the_signatures_and_types_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["signatures and types"]
    assert _PHRASE in ladder
    assert ladder[0] == "parameter meanings"  # originals still lead
    assert ladder.index(_PHRASE) > ladder.index("the annotated return type to document")


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "document-param" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_move_value_tier_is_the_doc_surface_cluster_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("document_param") == 0.68
    # The same doc-surface cluster tier as its JS mirror.
    assert move_value("document_param") == move_value("js_document_param_types")
    assert objective_value("document-param") == 0.68
    assert objective_value("document-param") != DEFAULT_VALUE


def test_soundness_strategy_declared_and_not_scope_verify():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert "document-param" in SOUNDNESS_STRATEGY
    assert SOUNDNESS_STRATEGY["document-param"].startswith(
        "behavior-identical-docstring-only")
    assert "document-param" not in SCOPE_VERIFY_ALLOWLIST
    assert strategy_subset_of_registry() == []


def test_north_star_and_soundness_audits_pass():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


def test_counts_are_forty_one_concrete_of_eighty_three():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    names = set(available_objectives())
    assert len(names) == 86  # 86 after modernize-typing (86th, TIDY) registered
    assert len(classify_objectives(names)["CONCRETE"]) == 41  # promote-staticmethod (85th) is TIDY, not CONCRETE


# --- the soundness-corpus refusals (the must-refuse shapes) -------------------

def test_refuses_on_params_already_documented_corpus():
    # document-param is NOT expensive (pure AST), so it is swept on the DEFAULT cheap
    # path. On the standing ``params_already_documented`` shape every function already
    # records its parameters (one per convention), so the objective MUST refuse.
    from app.engine.objective_compiler import _objectives_map
    from app.engine.soundness_audit import _changed_files, _classify_cell, corpus_root, repo_root

    _fitness, moves = _objectives_map()["document-param"]
    changed = _changed_files(moves, corpus_root(repo_root()) / "params_already_documented")
    assert _classify_cell("params_already_documented", "document-param", changed) == "refused"


def test_refuses_on_partial_params_documented_corpus():
    # The PARTIAL trap: some params documented, not all. document-param MUST refuse the
    # WHOLE function rather than merge into the half-filled block.
    from app.engine.objective_compiler import _objectives_map
    from app.engine.soundness_audit import _changed_files, _classify_cell, corpus_root, repo_root

    _fitness, moves = _objectives_map()["document-param"]
    changed = _changed_files(moves, corpus_root(repo_root()) / "partial_params_documented")
    assert _classify_cell("partial_params_documented", "document-param", changed) == "refused"
