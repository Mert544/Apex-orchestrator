"""document-yields develop objective — the GENERATOR image of document-returns: the
annotation-sourced, style-matching twin that documents the YIELD contract.

Where a PUBLIC GENERATOR (a ``yield`` / ``yield from`` in its OWN scope) HAS a
docstring AND a subscripted iterator/generator return annotation but does NOT already
document its yield, splice a faithful ``Yields:`` section into the existing docstring
rendering the YIELDED ELEMENT type VERBATIM (the first subscript arg), MATCHING the
docstring's convention.

Covers: the scope-stopping yield walker (own-scope ``yield``/``yield from``; nested
def/lambda/comprehension excluded; expression-position ``x = yield v``); the
element-type renderer (verbatim sole arg of ``Iterator[T]`` / first arg ``Y`` of
``Generator[Y, S, R]``; refuse bare-unsubscripted / non-iterator / missing annotation;
alias-aware); the already-documented gate (Google ``Yields:`` bare + inline, Sphinx
``:yields:``/``:ytype:``); the convention-matched ``Yields:`` section renderer (Google
default + Sphinx field); the public/test/private NAME gate; the ``document_yields``
transform (lands, re-parses, runtime-value unchanged, idempotent, deterministic,
one-line EXPANSION, CRLF, non-ASCII byte-aware via the shared splice, mixed-module
lands only generators, unparseable no-op); the plan layer (lands + captures original,
refuses test/fixture); THE BOUNDARY (document-returns refuses every generator,
document-yields requires one — both run on ONE generator); plus the FIVE-registry 1:1
parity, the COUNT pins (81 / 39), and the soundness-corpus refusal. Every test is pure
AST — no node, no subprocess — so all run on the fast gate.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.objectives.document_returns import document_returns
from app.execution.objectives.document_yields import (
    _element_text,
    _has_documented_yield,
    _is_generator,
    _yield_section,
    document_yields,
    plan_document_yields,
)

_PHRASE = "the yielded type to document"


def _fn(src: str) -> ast.FunctionDef:
    """The first top-level function definition in ``src``."""
    return ast.parse(src).body[0]  # type: ignore[return-value]


def _method(src: str) -> ast.FunctionDef:
    """The first method of the first top-level class in ``src``."""
    return ast.parse(src).body[0].body[0]  # type: ignore[union-attr,return-value]


# --- the scope-stopping yield walker (the IS-A-GENERATOR predicate) -----------

def test_is_generator_detects_yield_and_yield_from():
    assert _is_generator(_fn("def f():\n    yield 1\n"))
    assert _is_generator(_fn("def f():\n    yield from range(3)\n"))
    # a yield in expression position (``x = yield v``) still makes it a generator.
    assert _is_generator(_fn("def f():\n    x = yield 1\n    return x\n"))
    # a yield nested in plain control flow is still this scope's.
    assert _is_generator(_fn("def f():\n    for i in r:\n        if i:\n            yield i\n"))


def test_is_generator_is_false_for_a_plain_function():
    assert not _is_generator(_fn("def f():\n    return iter([])\n"))
    assert not _is_generator(_fn("def f():\n    return (x for x in y)\n"))  # genexp != generator
    assert not _is_generator(_fn("def f():\n    return [x for x in y]\n"))


def test_is_generator_stops_at_a_nested_scope():
    # a ``yield`` inside a nested def / lambda / comprehension belongs to THAT scope —
    # the enclosing function is NOT a generator (the document_raises stop-at-scope rule).
    nested_def = "def outer():\n    def inner():\n        yield 1\n    return inner()\n"
    assert not _is_generator(_fn(nested_def))
    nested_async = "def outer():\n    async def inner():\n        yield 1\n    return inner\n"
    assert not _is_generator(_fn(nested_async))
    # a yield buried in a generator-expression argument is the genexp's scope, not ours.
    assert not _is_generator(_fn("def outer():\n    return list(x for x in (yield_stub))\n"))


def test_is_generator_true_for_async_generator():
    assert _is_generator(_fn("async def f():\n    yield 1\n"))


# --- the element-type renderer (verbatim first subscript arg) ------------------

def test_element_text_renders_iterator_sole_arg():
    assert _element_text(_fn("def f() -> Iterator[int]: ..."), {}) == "int"
    assert _element_text(_fn("def f() -> Iterable[str]: ..."), {}) == "str"
    assert _element_text(_fn("def f() -> AsyncIterator[bytes]: ..."), {}) == "bytes"
    assert _element_text(
        _fn("def f() -> Iterator[dict[str, int]]: ..."), {}) == "dict[str, int]"


def test_element_text_renders_generator_first_arg():
    # ``Generator[Y, S, R]`` / ``AsyncGenerator[Y, S]`` yield ``Y`` (the FIRST arg).
    assert _element_text(_fn("def f() -> Generator[int, None, None]: ..."), {}) == "int"
    assert _element_text(_fn("def f() -> AsyncGenerator[Row, None]: ..."), {}) == "Row"


def test_element_text_resolves_alias_and_dotted_spellings():
    assert _element_text(_fn("def f() -> typing.Iterator[int]: ..."), {}) == "int"
    assert _element_text(
        _fn("def f() -> collections.abc.Iterator[str]: ..."), {}) == "str"
    al = {"It": "Iterator", "Gen": "Generator"}
    assert _element_text(_fn("def f() -> It[int]: ..."), al) == "int"
    assert _element_text(_fn("def f() -> Gen[str, None, None]: ..."), al) == "str"


def test_element_text_refuses_bare_unsubscripted_and_non_iterator_and_missing():
    assert _element_text(_fn("def f() -> Iterator: ..."), {}) is None  # bare, no element
    assert _element_text(_fn("def f() -> Generator: ..."), {}) is None
    assert _element_text(_fn("def f() -> list[int]: ..."), {}) is None  # not iterator/gen head
    assert _element_text(_fn("def f() -> int: ..."), {}) is None
    assert _element_text(_fn("def f(): ..."), {}) is None  # no annotation


# --- the already-documented gate (Google + Sphinx yield conventions) ----------

def test_has_documented_yield_matches_google_and_sphinx():
    assert _has_documented_yield("Doc.\n\nYields:\n    the item\n")
    assert _has_documented_yield("Doc.\n\nYields: each row\n")  # the inline form
    assert _has_documented_yield("Doc.\n\n:yields: the item\n")
    assert _has_documented_yield("Doc.\n\n:yield: the item\n")
    assert _has_documented_yield("Doc.\n\n:ytype: int\n")
    assert _has_documented_yield("Doc.\n\n    Yield: the item\n")  # indented, singular


def test_has_documented_yield_ignores_prose():
    assert not _has_documented_yield("It yields the next value, see below.\n")
    assert not _has_documented_yield("Just a one-line summary.")
    # Prose beginning with "Yields" but with NO colon is not a section header.
    assert not _has_documented_yield("Doc.\n\nYields the answer eventually.\n")
    # A Returns section is NOT a yield record (the two are distinct conventions).
    assert not _has_documented_yield("Doc.\n\nReturns:\n    the value\n")


# --- the section renderer ------------------------------------------------------

def test_yield_section_google_and_sphinx_shapes():
    g = _yield_section("google", "    ", "int", "\n")
    assert g == ["\n", "    Yields:\n", "        int\n"]
    s = _yield_section("sphinx", "    ", "int", "\n")
    assert s == ["    :yields: int\n", "    :ytype: int\n"]


def test_yield_section_uses_the_given_terminator():
    g = _yield_section("google", "  ", "int", "\r\n")
    assert all(line.endswith("\r\n") for line in g)


# --- the apply path: Google (default + matched section) -----------------------

def test_apply_plain_prose_uses_the_google_default():
    src = ('def rows() -> Iterator[int]:\n    """Stream the rows.\n\n    Detail.\n'
           '    """\n    yield 1\n')
    out = document_yields(src)
    assert out is not None
    assert "\n    Yields:\n        int\n" in out
    assert ast.parse(out) is not None
    assert ast.get_docstring(ast.parse(out).body[0]) is not None  # docstring stays first


def test_apply_google_section_docstring_gets_google_yields():
    src = ('def f(n) -> Generator[int, None, None]:\n    """Do it.\n\n    Args:\n'
           '        n: count.\n    """\n    yield from range(n)\n')
    out = document_yields(src)
    assert out is not None
    assert "    Yields:\n        int\n" in out
    assert ":yields:" not in out  # NOT a Sphinx field jammed into a Google block


# --- the apply path: Sphinx (matched field list) ------------------------------

def test_apply_sphinx_docstring_gets_sphinx_yields_and_ytype():
    src = ('def f(rows) -> Iterator[str]:\n    """Render.\n\n    :param rows: input.\n'
           '    """\n    yield from rows\n')
    out = document_yields(src)
    assert out is not None
    assert "    :yields: str\n" in out
    assert "    :ytype: str\n" in out
    assert "Yields:" not in out  # NOT a Google section jammed into the Sphinx field list


# --- the apply path: one-line docstring EXPANSION (shared byte-aware splice) ----

def test_apply_expands_one_line_docstring():
    src = 'def f() -> Iterator[int]:\n    """Count up."""\n    yield 1\n'
    out = document_yields(src)
    assert out is not None
    assert out == (
        'def f() -> Iterator[int]:\n    """Count up.\n\n'
        '    Yields:\n        int\n    """\n    yield 1\n')


def test_apply_one_line_preserves_raw_prefix_and_quote_style():
    out_r = document_yields('def f() -> Iterator[int]:\n    r"""Doc."""\n    yield 1\n')
    assert out_r is not None and out_r.splitlines()[1] == '    r"""Doc.'
    out_q = document_yields("def f() -> Iterator[int]:\n    '''Doc.'''\n    yield 1\n")
    assert out_q is not None
    assert out_q.splitlines()[1] == "    '''Doc."
    assert "    '''\n" in out_q


def test_apply_one_line_non_ascii_no_stray_quote():
    # The shared byte-aware splice (col_offset / end_col_offset are UTF-8 BYTE offsets)
    # round-trips a non-ASCII one-line docstring exactly — no stray closing quote kept
    # in the rebuilt head (the document_returns byte-offset P0, reused here). A 2-byte
    # ``ï`` and a 4-byte astral emoji both survive.
    src = 'def naive() -> Iterator[int]:\n    """Naïve 🎯 stream."""\n    yield 1\n'
    out = document_yields(src)
    assert out is not None
    doc = ast.get_docstring(ast.parse(out).body[0])
    assert doc is not None
    assert doc.startswith("Naïve 🎯 stream.\n")  # body verbatim, NO stray trailing quote
    assert '."' not in doc.splitlines()[0]       # summary line is clean
    assert "Yields:\n    int" in doc


# --- CRLF preservation on BOTH paths (shared splice) --------------------------

def test_apply_preserves_crlf_multiline():
    src = ('def f() -> Iterator[int]:\r\n    """Doc.\r\n\r\n    More.\r\n    """\r\n'
           '    yield 1\r\n')
    out = document_yields(src)
    assert out is not None
    assert "\r\n" in out
    assert "\n" not in out.replace("\r\n", "")  # no bare LF leaked in
    assert "    Yields:\r\n" in out


def test_apply_preserves_crlf_one_line_expansion():
    src = 'def f() -> Iterator[int]:\r\n    """Doc."""\r\n    yield 1\r\n'
    out = document_yields(src)
    assert out is not None
    assert "\n" not in out.replace("\r\n", "")
    assert "    Yields:\r\n" in out


# --- content-on-close-line (dogfood P-class: mid-paragraph split) --------------
# The iter_statement_blocks dogfood that CAUGHT this bug: a multi-line docstring whose
# LAST body line is ``    text."""`` (content + closing quotes on the SAME line). The
# ``Yields:`` section must land at the END of the body — before the quotes moved to
# their own line — never spliced mid-paragraph (the shared splice_section_multiline fix).

def test_apply_content_on_close_line_lands_after_body_not_mid_paragraph():
    src = ('def f() -> Iterator[int]:\n'
           '    """Head line.\n\n'
           '    A paragraph whose final sentence ends with content and then\n'
           '    the closing triple quotes right here."""\n'
           '    yield 1\n')
    orig_doc = ast.get_docstring(ast.parse(src).body[0])
    out = document_yields(src)
    assert out is not None
    new_doc = ast.get_docstring(ast.parse(out).body[0])  # must re-parse
    assert new_doc.startswith(orig_doc), (orig_doc, new_doc)
    assert new_doc[len(orig_doc):] == "\n\nYields:\n    int"
    lines = out.splitlines()
    assert "    the closing triple quotes right here." in lines  # content intact
    assert lines.index("    Yields:") > lines.index(
        "    the closing triple quotes right here.")
    assert lines[-2] == '    """'  # closing quotes moved to their own line


def test_apply_content_on_close_line_preserves_crlf():
    src = ('def f() -> Iterator[int]:\r\n    """Head.\r\n\r\n    body end here."""\r\n'
           '    yield 1\r\n')
    out = document_yields(src)
    assert out is not None
    assert "\n" not in out.replace("\r\n", "")
    assert "    Yields:\r\n" in out
    assert out.splitlines()[-2] == '    """'


def test_apply_content_on_close_line_refuses_trailing_comment_and_concat():
    cmt = ('def f() -> Iterator[int]:\n    """Head.\n\n    body end."""  # c\n'
           '    yield 1\n')
    assert ast.get_docstring(ast.parse(cmt).body[0]) is not None
    assert document_yields(cmt) is None
    concat = ('def f() -> Iterator[int]:\n    """one.""" \\\n'
              '    """two ends here."""\n    yield 1\n')
    assert ast.get_docstring(ast.parse(concat).body[0]) is not None
    assert document_yields(concat) is None


def test_apply_dedicated_close_line_stays_byte_identical():
    src = ('def f() -> Iterator[int]:\n    """Head.\n\n    body.\n    """\n'
           '    yield 1\n')
    assert document_yields(src) == (
        'def f() -> Iterator[int]:\n    """Head.\n\n    body.\n\n'
        '    Yields:\n        int\n    """\n    yield 1\n')


# --- @property getter generator, methods --------------------------------------

def test_apply_documents_method_generator():
    src = ('class C:\n    def rows(self) -> Iterator[int]:\n'
           '        """The rows."""\n        yield self._x\n')
    out = document_yields(src)
    assert out is not None
    assert "        Yields:\n            int\n" in out


# --- THE BOUNDARY: document-returns refuses generators, document-yields requires one

def test_boundary_one_generator_gets_yields_never_returns():
    # THE denetçi prime attack, pinned: run BOTH objectives on the SAME generator.
    # document-yields LANDS a Yields: (never a Returns:); document-returns REFUSES it.
    gen = 'def stream() -> Iterator[int]:\n    """Stream ints."""\n    yield 1\n'
    y = document_yields(gen)
    assert y is not None
    assert "Yields:" in y
    assert "Returns:" not in y  # a generator NEVER gets a Returns section
    assert document_returns(gen) is None  # document-returns refuses every generator


def test_boundary_holds_across_the_whole_iterator_generator_family():
    # Every recognised iterator/generator family + alias spelling: document-yields
    # lands, document-returns refuses — the mutual exclusion is airtight.
    cases = [
        ("Iterator[int]", "", ""),
        ("Iterable[str]", "", ""),
        ("Generator[int, None, None]", "", ""),
        ("AsyncIterator[bytes]", "", "async "),
        ("AsyncGenerator[int, None]", "", "async "),
        ("typing.Iterator[int]", "import typing\n", ""),
        ("collections.abc.Iterator[int]", "import collections.abc\n", ""),
        ("It[int]", "from collections.abc import Iterator as It\n", ""),
    ]
    for ann, imp, apfx in cases:
        src = f'{imp}{apfx}def f() -> {ann}:\n    """Doc."""\n    yield 1\n'
        y = document_yields(src)
        assert y is not None and "Yields:" in y and "Returns:" not in y, ann
        assert document_returns(src) is None, ann


def test_boundary_non_generator_iterator_return_is_neither_objectives_yields():
    # A function annotated ``-> Iterator[int]`` that does NOT yield (returns an iterator
    # object) is NOT a generator: document-yields refuses it (no own-scope yield) and
    # document-returns refuses it too (iterator head is in its refuse set) — so it gets
    # NO yield doc and NO return doc. Neither objective over-reaches.
    src = 'def f() -> Iterator[int]:\n    """Doc."""\n    return iter([1, 2])\n'
    assert document_yields(src) is None
    assert document_returns(src) is None


# --- the FULL refuse set on the transform -------------------------------------

def test_transform_refuses_non_generator():
    # has the iterator annotation + docstring but NO yield -> not our business.
    assert document_yields(
        'def f() -> Iterator[int]:\n    """Doc."""\n    return iter([])\n') is None
    # yields only in a NESTED def -> the outer is not a generator.
    assert document_yields(
        'def outer() -> Iterator[int]:\n    """Doc."""\n'
        '    def inner():\n        yield 1\n    return inner()\n') is None


def test_transform_refuses_bare_unsubscripted_iterator_generator():
    for ann in ("Iterator", "Generator", "Iterable", "AsyncIterator", "AsyncGenerator"):
        src = f'def f() -> {ann}:\n    """Doc."""\n    yield 1\n'
        assert document_yields(src) is None, ann


def test_transform_refuses_non_iterator_annotation_and_missing_annotation():
    # a generator whose return is NOT an iterator/generator head (or absent) -> refuse
    # (document-yields documents ONLY the recognised subscripted iterator/generator).
    assert document_yields(
        'def f() -> list[int]:\n    """Doc."""\n    yield 1\n') is None
    assert document_yields('def f():\n    """Doc."""\n    yield 1\n') is None


def test_transform_refuses_already_documented_in_every_convention():
    head = 'def f() -> Iterator[int]:\n    """Doc.\n\n'
    tail = '\n    """\n    yield 1\n'
    for body in ("    Yields:\n        the n", "    Yields: the n",
                 "    :yields: the n", "    :yield: the n", "    :ytype: int"):
        assert document_yields(head + body + tail) is None, body


def test_transform_refuses_undocumented_private_and_test():
    assert document_yields(
        'def f() -> Iterator[int]:\n    yield 1\n') is None  # no docstring
    assert document_yields(
        'def _f() -> Iterator[int]:\n    """Doc."""\n    yield 1\n') is None  # private
    assert document_yields(
        'def __dunder__(self) -> Iterator[int]:\n    """Doc."""\n    yield 1\n') is None
    assert document_yields(
        'def test_f() -> Iterator[int]:\n    """Doc."""\n    yield 1\n') is None  # test_


def test_transform_refuses_header_shared_one_liner():
    # ``def f(): """Doc."""`` reports the def header as the docstring-line indent.
    assert document_yields('def f() -> Iterator[int]: """Doc."""\n') is None


# --- behaviour-identity / idempotence / determinism ---------------------------

def test_apply_is_runtime_value_identical():
    # A Yields section is docstring TEXT — it changes no runtime value. Exec before and
    # after and confirm the generator still yields the same items; the docstring grows.
    src = 'def f(n: int) -> Iterator[int]:\n    """Count up."""\n    yield from range(n)\n'
    out = document_yields(src)
    assert out is not None
    before, after = {}, {}
    exec(src, before)  # noqa: S102 - controlled test source
    exec(out, after)  # noqa: S102 - controlled test source
    assert list(before["f"](3)) == list(after["f"](3)) == [0, 1, 2]
    assert "Yields:" in (after["f"].__doc__ or "")


def test_apply_is_idempotent():
    src = 'def f() -> Iterator[int]:\n    """Count."""\n    yield 1\n'
    once = document_yields(src)
    assert once is not None
    assert document_yields(once) is None  # now documented -> byte-identical no-op


def test_apply_is_deterministic():
    src = ('def f(x) -> Generator[int, None, None]:\n    """Build.\n\n    Args:\n'
           '        x: in.\n    """\n    yield x\n')
    assert document_yields(src) == document_yields(src)


def test_transform_mixed_module_lands_only_qualifying_generators():
    src = (
        'def a() -> Iterator[int]:\n    """A."""\n    yield 1\n\n\n'
        'def b() -> Iterator[str]:\n    """B.\n\n    Yields:\n        x\n    """\n'
        '    yield "x"\n\n\n'
        'def c() -> int:\n    """C."""\n    return 1\n\n\n'
        'def d() -> Iterator[int]:\n    """D."""\n    return iter([])\n')
    out = document_yields(src)
    assert out is not None
    tree = ast.parse(out)
    docs = {fn.name: ast.get_docstring(fn) for fn in tree.body}
    assert "Yields:" in docs["a"]            # generator + undocumented -> landed
    assert docs["b"].count("Yields:") == 1   # already documented -> untouched
    assert "Yields:" not in (docs["c"] or "")  # non-generator return -> untouched
    assert "Yields:" not in (docs["d"] or "")  # iterator return but no yield -> untouched


def test_transform_no_op_on_unparseable_source():
    assert document_yields("def f( -> Iterator[int]:\n    yield 1\n") is None


# --- the plan layer -----------------------------------------------------------

def test_plan_lands_and_captures_original(tmp_path: Path):
    (tmp_path / "mod.py").write_text(
        'def f() -> Iterator[int]:\n    """Count."""\n    yield 1\n', encoding="utf-8")
    plan = plan_document_yields(str(tmp_path), "mod.py")
    assert plan.new_contents
    assert "Yields:" in plan.new_contents["mod.py"]
    assert plan.originals["mod.py"] == (
        'def f() -> Iterator[int]:\n    """Count."""\n    yield 1\n')


def test_plan_is_noop_when_nothing_documentable(tmp_path: Path):
    (tmp_path / "mod.py").write_text(
        'def f() -> Iterator:\n    """Bare."""\n    yield 1\n', encoding="utf-8")
    plan = plan_document_yields(str(tmp_path), "mod.py")
    assert not plan.new_contents


def test_plan_refuses_test_file(tmp_path: Path):
    (tmp_path / "test_mod.py").write_text(
        'def f() -> Iterator[int]:\n    """Count."""\n    yield 1\n', encoding="utf-8")
    plan = plan_document_yields(str(tmp_path), "test_mod.py")
    assert not plan.new_contents


# --- the FIVE-registry 1:1 parity + count pins --------------------------------

def test_objective_is_registered_and_pursuable():
    from app.engine.objective_compiler import available_objectives

    assert "document-yields" in set(available_objectives())


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
    assert facet_to_objective("the raised exceptions to document") == "document-raises"
    assert facet_to_objective(_PHRASE) == "document-yields"


def test_facet_phrase_lives_in_the_signatures_and_types_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["signatures and types"]
    assert _PHRASE in ladder
    assert ladder[0] == "parameter meanings"  # originals still lead
    # appended AFTER the annotation-sourced return sibling.
    assert ladder.index(_PHRASE) > ladder.index("the annotated return type to document")


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "document-yields" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


def test_move_value_is_the_fact_documenting_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("document_yields") == 0.68
    # The same fact-documenting tier as its failure-contract sibling document_raises.
    assert move_value("document_yields") == move_value("document_raises")
    assert objective_value("document-yields") == 0.68
    assert objective_value("document-yields") != DEFAULT_VALUE  # not the fallback


def test_soundness_strategy_declared_and_not_scope_verify():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert "document-yields" in SOUNDNESS_STRATEGY
    assert SOUNDNESS_STRATEGY["document-yields"].startswith(
        "behavior-identical-docstring-only")
    assert "document-yields" not in SCOPE_VERIFY_ALLOWLIST
    assert strategy_subset_of_registry() == []  # no stale strategy entry


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
    assert len(names) == 90  # 89 after js-strengthen-tests (89th, CONCRETE) registered
    assert len(classify_objectives(names)["CONCRETE"]) == 45  # js-strengthen-tests (89th) is CONCRETE


# --- the soundness-corpus refusal (the must-refuse shape + the boundary) -------

def test_refuses_on_yields_already_documented_corpus():
    # document-yields is NOT expensive (pure AST), so it is swept on the DEFAULT cheap
    # path. On the standing ``yields_already_documented`` shape every generator already
    # records its yield (one per convention), so the objective MUST refuse.
    from app.engine.objective_compiler import _objectives_map
    from app.engine.soundness_audit import _changed_files, _classify_cell, corpus_root, repo_root

    _fitness, moves = _objectives_map()["document-yields"]
    changed = _changed_files(moves, corpus_root(repo_root()) / "yields_already_documented")
    assert _classify_cell("yields_already_documented", "document-yields", changed) == "refused"


def test_document_returns_also_refuses_the_yields_corpus_boundary():
    # The boundary, pinned at the corpus level: every function on the
    # yields_already_documented shape carries an iterator/generator return, so
    # document-returns refuses it too — a generator is never given a Returns section.
    from app.engine.objective_compiler import _objectives_map
    from app.engine.soundness_audit import _changed_files, _classify_cell, corpus_root, repo_root

    _fitness, moves = _objectives_map()["document-returns"]
    changed = _changed_files(moves, corpus_root(repo_root()) / "yields_already_documented")
    assert _classify_cell("yields_already_documented", "document-returns", changed) == "refused"
