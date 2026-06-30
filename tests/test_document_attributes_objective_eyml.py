"""document-attributes develop objective — the CLASS-ATTRIBUTE image of
document-returns: the annotation-sourced, style-matching twin that documents a
class's declared STATE.

Where a PUBLIC class HAS a docstring but does NOT already document its attributes,
splice an ``Attributes:`` section into the existing docstring listing one ``name
(TYPE)`` line per class-body annotated field (``ast.AnnAssign``), ``TYPE`` rendered
VERBATIM via ``ast.unparse(field.annotation)``, MATCHING the docstring's convention.

Covers: the verbatim annotation renderer (``dict[str, int]``, ``ClassVar[int]``,
forward-ref strings) and the unreadable-annotation drop; the class-body field walk
(simple-``Name`` targets only — ``self.x`` / ``a.b`` / nested-scope fields skipped);
the already-documented gate (every convention — Google ``Attributes:`` / Sphinx
``:ivar:``/``:cvar:``/``:var:`` / NumPy underline) INCLUDING the PARTIAL-doc refusal
(never merge a half-filled block); the convention detector + section renderer (Google
default, Sphinx ``:ivar:``/``:vartype:`` field list); the multi-line splice + indent
guard and the one-line EXPANSION (prefix/quote preserved); CRLF preservation on BOTH
paths; the public/test/private/dunder NAME gate; the ``document_attributes`` transform
(lands, re-parses, runtime-value unchanged, idempotent, deterministic, mixed-module
lands only the qualifying classes, unparseable no-op); the plan layer (lands + captures
original, refuses test/fixture/non-library, unreadable no-op); plus objective
registration / facet+manifest+soundness+move_value 1:1 parity (the FIVE registries),
the COUNT pins (81 / 39), and the soundness-corpus refusal (full + partial). Every
test is pure AST — no node, no subprocess — so all run on the fast gate.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.objectives.document_attributes import (
    _class_attributes,
    _convention,
    _documentable_target,
    _has_documented_attributes,
    _readable_annotation,
    _section_lines,
    document_attributes,
    plan_document_attributes,
)

_PHRASE = "the class attributes to document"


def _cls(src: str) -> ast.ClassDef:
    """The first top-level class definition in ``src``."""
    return ast.parse(src).body[0]  # type: ignore[return-value]


# --- the verbatim annotation renderer + the unreadable drop -------------------

def test_readable_annotation_renders_verbatim():
    cls = _cls("class C:\n    a: dict[str, int]\n    b: int\n    c: ClassVar[int]\n")
    anns = [stmt.annotation for stmt in cls.body]
    assert _readable_annotation(anns[0]) == "dict[str, int]"
    assert _readable_annotation(anns[1]) == "int"
    assert _readable_annotation(anns[2]) == "ClassVar[int]"


def test_readable_annotation_forward_ref_string_kept_verbatim():
    cls = _cls('class C:\n    a: "Box"\n')
    assert _readable_annotation(cls.body[0].annotation) == "'Box'"


# --- the class-body field walk (Name targets only) ----------------------------

def test_class_attributes_collects_annassign_name_fields_in_order():
    cls = _cls("class C:\n    host: str\n    port: int = 80\n    flag: bool = False\n")
    assert _class_attributes(cls) == [("host", "str"), ("port", "int"), ("flag", "bool")]


def test_class_attributes_skips_non_name_targets_and_unannotated():
    # ``a.b: int`` / subscript targets are not class-level NAME bindings; a bare
    # ``x = 1`` carries no annotation; neither is documented.
    cls = _cls("class C:\n    x: int\n    y = 1\n    obj.attr: int\n")
    assert _class_attributes(cls) == [("x", "int")]


def test_class_attributes_ignores_instance_only_self_assignment():
    # ``self.x = ...`` in ``__init__`` is INSTANCE state with no class-level
    # annotation — out of scope (documenting it would be inference). Empty.
    cls = _cls(
        "class C:\n    def __init__(self):\n        self.x: int = 0\n        self.y = 1\n")
    assert _class_attributes(cls) == []


def test_class_attributes_only_direct_body_not_nested_scopes():
    # A field annotated inside a nested function/class is NOT mis-attributed.
    cls = _cls(
        "class C:\n    a: int\n    def m(self):\n        local: str = 'x'\n"
        "    class Inner:\n        b: float\n")
    assert _class_attributes(cls) == [("a", "int")]


# --- the already-documented gate (every convention + PARTIAL) -----------------

def test_has_documented_attributes_matches_google_sphinx_numpy():
    assert _has_documented_attributes("Doc.\n\nAttributes:\n    x: the x.\n")
    assert _has_documented_attributes("Doc.\n\n:ivar x: the x.\n")
    assert _has_documented_attributes("Doc.\n\n:cvar y: the y.\n")
    assert _has_documented_attributes("Doc.\n\n:var z: the z.\n")
    assert _has_documented_attributes("Doc.\n\nAttributes\n----------\nx : int\n")
    assert _has_documented_attributes("Doc.\n\n    Attributes\n    ----------\n    x : int\n")
    # the inline ``Attributes: x`` form is detected too (anchored to the colon).
    assert _has_documented_attributes("Doc.\n\nAttributes: the fields.\n")


def test_has_documented_attributes_ignores_prose_and_stray_dashes():
    assert not _has_documented_attributes("It has attributes, see below.\n")
    assert not _has_documented_attributes("Doc.\n\n    Notes\n    -----\n    stuff\n")
    assert not _has_documented_attributes("Just a one-line summary.")
    # Prose that merely begins with "Attributes" but has NO colon is not a section.
    assert not _has_documented_attributes("Doc.\n\nAttributes of this class vary.\n")


# --- the convention detector ---------------------------------------------------

def test_convention_detects_sphinx_field_list_including_ivar():
    assert _convention("Doc.\n\n:param x: in.\n") == "sphinx"
    assert _convention("Doc.\n\n:ivar x: the x.\n") == "sphinx"
    assert _convention("Doc.\n\n:vartype x: int\n") == "sphinx"


def test_convention_defaults_google_for_sections_and_plain_prose():
    assert _convention("Doc.\n\nArgs:\n    x: in.\n") == "google"
    assert _convention("Just plain prose, no sections at all.") == "google"
    assert _convention("") == "google"


# --- the section renderer ------------------------------------------------------

def test_section_lines_google_and_sphinx_shapes():
    attrs = [("host", "str"), ("port", "int")]
    g = _section_lines("google", "    ", attrs, "\n")
    assert g == ["\n", "    Attributes:\n", "        host (str)\n", "        port (int)\n"]
    s = _section_lines("sphinx", "    ", attrs, "\n")
    assert s == [
        "    :ivar host: str\n", "    :vartype host: str\n",
        "    :ivar port: int\n", "    :vartype port: int\n",
    ]


def test_section_lines_uses_the_given_terminator():
    g = _section_lines("google", "  ", [("x", "int")], "\r\n")
    assert all(line.endswith("\r\n") for line in g)


# --- the documentable-target combinator (the full gate stack) -----------------

def test_documentable_target_returns_edit_for_a_clean_candidate():
    src = 'class C:\n    """Doc.\n\n    More.\n    """\n    host: str\n'
    rows = src.splitlines(keepends=True)
    target = _documentable_target(_cls(src), rows)
    assert target is not None
    start, stop, repl = target
    assert (start, stop) == (4, 4)  # before the closing-quote line (index 4)
    assert any("Attributes:" in line for line in repl)


def test_documentable_target_refuses_undocumented_class():
    src = "class C:\n    host: str\n"
    assert _documentable_target(_cls(src), src.splitlines(keepends=True)) is None


def test_documentable_target_refuses_class_without_annotated_field():
    src = 'class C:\n    """Doc.\n\n    More.\n    """\n    x = 1\n'
    assert _documentable_target(_cls(src), src.splitlines(keepends=True)) is None


# --- the apply path: Google (the default + matched section) -------------------

def test_apply_plain_prose_uses_the_google_default():
    src = 'class C:\n    """Hold config.\n\n    Detail.\n    """\n    host: str\n    port: int = 80\n'
    out = document_attributes(src)
    assert out is not None
    assert "\n    Attributes:\n        host (str)\n        port (int)\n" in out
    assert ast.parse(out) is not None  # re-parses
    assert ast.get_docstring(ast.parse(out).body[0]) is not None


def test_apply_google_section_docstring_gets_google_attributes():
    src = ('class C:\n    """Do it.\n\n    Note:\n        a thing.\n'
           '    """\n    width: int\n')
    out = document_attributes(src)
    assert out is not None
    assert "    Attributes:\n        width (int)\n" in out
    assert ":ivar" not in out  # NOT a Sphinx field jammed into the Google block


# --- the apply path: Sphinx (matched field list) ------------------------------

def test_apply_sphinx_docstring_gets_sphinx_ivar_and_vartype():
    src = ('class C:\n    """Render.\n\n    :param x: in.\n'
           '    """\n    width: int\n')
    out = document_attributes(src)
    assert out is not None
    assert "    :ivar width: int\n" in out
    assert "    :vartype width: int\n" in out
    assert "Attributes:" not in out  # NOT a Google section in the Sphinx field list


# --- the apply path: one-line docstring EXPANSION -----------------------------

def test_apply_expands_one_line_docstring():
    src = 'class C:\n    """A point."""\n    x: int\n    y: int\n'
    out = document_attributes(src)
    assert out is not None
    assert out == (
        'class C:\n    """A point.\n\n'
        '    Attributes:\n        x (int)\n        y (int)\n    """\n    x: int\n    y: int\n')


def test_apply_one_line_preserves_raw_prefix_and_quote_style():
    out_r = document_attributes('class C:\n    r"""Doc."""\n    x: int\n')
    assert out_r is not None and out_r.splitlines()[1] == '    r"""Doc.'
    out_q = document_attributes("class C:\n    '''Doc.'''\n    x: int\n")
    assert out_q is not None
    assert out_q.splitlines()[1] == "    '''Doc."  # opener keeps the ''' quote style
    assert "    '''\n" in out_q  # and so does the new closing-quote line


def test_apply_refuses_header_shared_one_liner():
    # `class C: """Doc."""` reports the class header as the docstring-line indent.
    assert document_attributes('class C: """Doc."""\nx: int\n') is None


def test_apply_one_line_non_ascii_no_trailing_newline_no_stray_quote():
    # The byte-offset P0: col_offset / end_col_offset are UTF-8 BYTE offsets. A
    # one-line docstring with a non-ASCII char and NO trailing newline must round-trip
    # the body EXACTLY (no stray ``"``), with an Attributes section added.
    src = 'class Naive:\n    """Naïve cfg."""\n    hote: str'  # final line, no \n
    out = document_attributes(src)
    assert out is not None
    doc = ast.get_docstring(ast.parse(out).body[0])  # must re-parse
    assert doc is not None
    assert doc.startswith("Naïve cfg.\n")  # NO stray trailing quote on body
    assert '."' not in doc.splitlines()[0]
    assert "Attributes:\n    hote (str)" in doc


def test_apply_one_line_multi_non_ascii_skew_greater_than_one():
    # Two 2-byte chars (``é``×2) => a TWO-byte skew the old str-slice would mis-handle.
    src = 'class C:\n    """Résumé."""\n    x: int'  # no trailing newline
    out = document_attributes(src)
    assert out is not None
    doc = ast.get_docstring(ast.parse(out).body[0])
    assert doc.splitlines()[0] == "Résumé."  # exactly the original body, no stray quotes
    assert "Attributes:\n    x (int)" in doc


def test_apply_one_line_astral_char_round_trips():
    out = document_attributes('class C:\n    """Counts 🎯 hits."""\n    n: int\n')
    assert out is not None
    assert ast.get_docstring(ast.parse(out).body[0]).splitlines()[0] == "Counts 🎯 hits."


# --- CRLF preservation on BOTH the multi-line and one-line paths ---------------

def test_apply_preserves_crlf_multiline():
    src = 'class C:\r\n    """Doc.\r\n\r\n    More.\r\n    """\r\n    x: int\r\n'
    out = document_attributes(src)
    assert out is not None
    assert "\r\n" in out
    assert "\n" not in out.replace("\r\n", "")  # no bare LF leaked in


def test_apply_preserves_crlf_one_line_expansion():
    src = 'class C:\r\n    """Doc."""\r\n    x: int\r\n'
    out = document_attributes(src)
    assert out is not None
    assert "\n" not in out.replace("\r\n", "")
    assert "    Attributes:\r\n" in out


# --- content-on-close-line (dogfood P-class: mid-paragraph split) --------------
# The SHARED splice_section_multiline fix, on the CLASS family: a multi-line class
# docstring whose LAST body line is ``    text."""`` (content + closing quotes on the
# SAME line) must take the ``Attributes:`` section at the END of the body — before the
# quotes moved to their own line — never spliced mid-paragraph.

def test_apply_content_on_close_line_lands_after_body_not_mid_paragraph():
    src = ('class C:\n'
           '    """Head line.\n\n'
           '    A paragraph whose final sentence ends with content and then\n'
           '    the closing triple quotes right here."""\n'
           '    x: int\n    y: int\n')
    orig_doc = ast.get_docstring(ast.parse(src).body[0])
    out = document_attributes(src)
    assert out is not None
    new_doc = ast.get_docstring(ast.parse(out).body[0])  # must re-parse
    assert new_doc.startswith(orig_doc), (orig_doc, new_doc)
    assert new_doc[len(orig_doc):] == "\n\nAttributes:\n    x (int)\n    y (int)"
    lines = out.splitlines()
    assert "    the closing triple quotes right here." in lines  # content intact
    assert lines.index("    Attributes:") > lines.index(
        "    the closing triple quotes right here.")
    assert lines[-3] == '    """'  # closing quotes moved to their own line (before x/y)


def test_apply_content_on_close_line_preserves_crlf():
    src = ('class C:\r\n    """Head.\r\n\r\n    body end here."""\r\n'
           '    x: int\r\n')
    out = document_attributes(src)
    assert out is not None
    assert "\n" not in out.replace("\r\n", "")
    assert "    Attributes:\r\n" in out


def test_apply_content_on_close_line_refuses_trailing_comment_and_concat():
    cmt = ('class C:\n    """Head.\n\n    body end."""  # c\n    x: int\n')
    assert ast.get_docstring(ast.parse(cmt).body[0]) is not None
    assert document_attributes(cmt) is None
    concat = ('class C:\n    """one.""" \\\n'
              '    """two ends here."""\n    x: int\n')
    assert ast.get_docstring(ast.parse(concat).body[0]) is not None
    assert document_attributes(concat) is None


def test_apply_dedicated_close_line_stays_byte_identical():
    src = 'class C:\n    """Head.\n\n    body.\n    """\n    x: int\n'
    assert document_attributes(src) == (
        'class C:\n    """Head.\n\n    body.\n\n'
        '    Attributes:\n        x (int)\n    """\n    x: int\n')


# --- the unreadable-annotation drop / refuse ----------------------------------

def test_apply_documents_only_readable_fields_when_some_unreadable(monkeypatch):
    # When some field annotations are unreadable, only the readable ones are emitted.
    import app.execution.objectives.document_attributes as mod

    real = mod._readable_annotation

    def fake(node):
        # Treat any field annotated as a bare ``str`` Name as unreadable.
        if isinstance(node, ast.Name) and node.id == "str":
            return None
        return real(node)

    monkeypatch.setattr(mod, "_readable_annotation", fake)
    src = 'class C:\n    """Doc.\n\n    D.\n    """\n    a: int\n    b: str\n'
    out = document_attributes(src)
    assert out is not None
    assert "a (int)" in out
    assert "b (str)" not in out  # the unreadable one is dropped


def test_apply_refuses_class_when_no_field_readable(monkeypatch):
    import app.execution.objectives.document_attributes as mod

    monkeypatch.setattr(mod, "_readable_annotation", lambda node: None)
    src = 'class C:\n    """Doc.\n\n    D.\n    """\n    a: int\n    b: str\n'
    assert document_attributes(src) is None  # nothing readable -> refuse the class


# --- the FULL refuse set on the transform (the denetçi corpus) ----------------

def test_transform_refuses_undocumented_and_no_annotated_field():
    assert document_attributes("class C:\n    host: str\n") is None  # no docstring
    assert document_attributes(
        'class C:\n    """Doc.\n\n    D.\n    """\n    x = 1\n') is None  # no annotated field


def test_transform_refuses_instance_only_self_assignment():
    # A class whose only state is ``self.x`` (no class-level annotation) is refused —
    # documenting it would be inference, out of scope.
    src = ('class C:\n    """Doc.\n\n    D.\n    """\n'
           '    def __init__(self):\n        self.x: int = 0\n')
    assert document_attributes(src) is None


def test_transform_refuses_private_dunder_and_test_class():
    body = '\n    """Doc.\n\n    D.\n    """\n    x: int\n'
    assert document_attributes(f"class _C:{body}") is None       # private
    assert document_attributes(f"class __C__:{body}") is None    # dunder
    assert document_attributes(f"class test_C:{body}") is None   # test_


def test_transform_refuses_already_documented_in_every_convention():
    head = 'class C:\n    """Doc.\n\n'
    tail = '\n    """\n    x: int\n'
    for body in ("    :ivar x: the x", "    :cvar x: the x", "    :var x: the x",
                 "    Attributes:\n        x: the x",
                 "    Attributes: the fields",  # the inline form
                 "    Attributes\n    ----------\n    x : int"):
        assert document_attributes(head + body + tail) is None, body


def test_transform_refuses_partially_documented_class():
    # PARTIAL doc: a half-filled ``Attributes:`` block naming only one of two fields.
    # The WHOLE class is refused — never merge into an author's partial block.
    src = ('class C:\n    """Doc.\n\n    Attributes:\n        host: the host.\n'
           '    """\n    host: str\n    port: int = 80\n')
    assert document_attributes(src) is None
    # PARTIAL via Sphinx: only one field carries an :ivar:.
    src2 = ('class C:\n    """Doc.\n\n    :ivar host: the host.\n'
            '    """\n    host: str\n    port: int = 80\n')
    assert document_attributes(src2) is None


# --- behaviour-identity / idempotence / determinism ---------------------------

def test_apply_is_runtime_value_identical():
    # An attributes section is docstring TEXT — it changes no runtime value. We exec
    # before/after and confirm the class behaves identically; the docstring updates.
    src = ('class Point:\n    """A point."""\n    x: int = 0\n    y: int = 0\n'
           '    def total(self):\n        return self.x + self.y\n')
    out = document_attributes(src)
    assert out is not None
    before, after = {}, {}
    exec(src, before)  # noqa: S102 - controlled test source
    exec(out, after)  # noqa: S102 - controlled test source
    bp, ap = before["Point"](), after["Point"]()
    ap.x, ap.y = 3, 4
    bp.x, bp.y = 3, 4
    assert bp.total() == ap.total() == 7
    assert "Attributes:" in (after["Point"].__doc__ or "")


def test_apply_is_idempotent():
    src = 'class C:\n    """A config."""\n    host: str\n'
    once = document_attributes(src)
    assert once is not None
    assert document_attributes(once) is None  # now documented -> byte-identical no-op


def test_apply_is_deterministic():
    src = 'class C:\n    """Build.\n\n    Args:\n        n: in.\n    """\n    a: int\n    b: str\n'
    assert document_attributes(src) == document_attributes(src)


def test_transform_mixed_module_lands_only_qualifying_classes():
    src = (
        'class A:\n    """A."""\n    x: int\n\n\n'
        'class B:\n    """B.\n\n    Attributes:\n        y: the y.\n    """\n    y: str\n\n\n'
        'class C:\n    """C."""\n    z = 1\n')
    out = document_attributes(src)
    assert out is not None
    tree = ast.parse(out)
    docs = {c.name: ast.get_docstring(c) for c in tree.body}
    assert "Attributes:" in docs["A"]          # annotated + undocumented -> landed
    assert docs["B"].count("Attributes:") == 1  # already documented -> untouched
    assert "Attributes:" not in docs["C"]       # no annotated field -> untouched


def test_transform_no_op_on_unparseable_source():
    assert document_attributes("class C( :\n    pass\n") is None


# --- the plan layer -----------------------------------------------------------

def test_plan_lands_and_captures_original(tmp_path: Path):
    root = tmp_path
    original = 'class C:\n    """A config."""\n    host: str\n'
    (root / "mod.py").write_text(original, encoding="utf-8")
    plan = plan_document_attributes(str(root), "mod.py")
    assert plan.new_contents  # a rewrite is planned
    assert "Attributes:" in plan.new_contents["mod.py"]
    assert plan.originals["mod.py"] == original


def test_plan_is_noop_when_nothing_documentable(tmp_path: Path):
    (tmp_path / "mod.py").write_text(
        'class C:\n    """Doc."""\n    x = 1\n', encoding="utf-8")  # no annotated field
    plan = plan_document_attributes(str(tmp_path), "mod.py")
    assert not plan.new_contents


def test_plan_refuses_test_file(tmp_path: Path):
    (tmp_path / "test_mod.py").write_text(
        'class C:\n    """A config."""\n    host: str\n', encoding="utf-8")
    plan = plan_document_attributes(str(tmp_path), "test_mod.py")
    assert not plan.new_contents


def test_plan_lands_non_ascii_one_liner_without_corruption(tmp_path: Path):
    (tmp_path / "mod.py").write_text(
        'class C:\n    """Naïve cfg."""\n    host: str\n', encoding="utf-8")
    plan = plan_document_attributes(str(tmp_path), "mod.py")
    assert plan.new_contents
    landed = plan.new_contents["mod.py"]
    assert ast.get_docstring(ast.parse(landed).body[0]).splitlines()[0] == "Naïve cfg."


# --- the FIVE-registry 1:1 parity + count pins --------------------------------

def test_objective_is_registered_and_pursuable():
    from app.engine.objective_compiler import available_objectives

    assert "document-attributes" in set(available_objectives())


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
    assert facet_to_objective("the annotated return type to document") == "document-returns"
    assert facet_to_objective("the raised exceptions to document") == "document-raises"
    assert facet_to_objective(_PHRASE) == "document-attributes"


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
    assert "document-attributes" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


def test_move_value_tier_is_the_documented_section_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("document_attributes") == 0.68
    # The same documented-from-declared-annotation tier as document_signature/raises.
    assert move_value("document_attributes") == move_value("document_raises")
    assert objective_value("document-attributes") == 0.68
    assert objective_value("document-attributes") != DEFAULT_VALUE  # not the fallback


def test_soundness_strategy_declared_and_not_scope_verify():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert "document-attributes" in SOUNDNESS_STRATEGY
    assert SOUNDNESS_STRATEGY["document-attributes"].startswith(
        "behavior-identical-docstring-only")
    assert "document-attributes" not in SCOPE_VERIFY_ALLOWLIST
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


# --- the soundness-corpus refusal (the must-refuse shape) ---------------------

def test_refuses_on_attributes_already_documented_corpus():
    # document-attributes is NOT expensive (pure AST), so it is swept on the DEFAULT
    # cheap path. On the standing ``attributes_already_documented`` shape every class
    # already records its attributes (fully — one per convention — AND partially), so
    # the objective MUST refuse.
    from app.engine.objective_compiler import _objectives_map
    from app.engine.soundness_audit import _changed_files, _classify_cell, corpus_root, repo_root

    _fitness, moves = _objectives_map()["document-attributes"]
    changed = _changed_files(moves, corpus_root(repo_root()) / "attributes_already_documented")
    assert _classify_cell(
        "attributes_already_documented", "document-attributes", changed) == "refused"
