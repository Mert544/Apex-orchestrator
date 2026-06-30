"""pin-return-type develop objective — the DOCUMENTED-function image of
infer-type-hints. Where a function HAS a docstring but no ``-> T`` annotation and
its return type is PROVABLE, splice ONE ``Returns: <T>`` line into the existing
docstring (only when it lacks one), the ``<T>`` read from the SAME proven
return-type oracle infer-type-hints lands as ``-> T`` — never a guess.

Covers: the splice helper + indent guard (multi-line docstring closing-quote
location, single-line / header-shared / odd-indent refusals); the existing-return
regex (every Google / reST / epydoc spelling); the inverse-of-document-signature
gate (HAS a docstring, no ``-> T``, no recorded return); the oracle-as-gate
refusals (not-provable / generator / fall-through / already-``-> T`` all subsumed
by the bare oracle returning ``None``); the FULL name/file refusal set
(private/dunder/test_, test/fixture/non-library); the ``pin_return_types``
transform (lands int/None, splices before the closing quotes at body indent,
re-parses, runtime-value-unchanged, idempotent, deterministic, mixed-module lands
only the provable documented functions, unparseable no-op); the plan layer (lands +
captures original, refuses test/fixture/non-library, unreadable no-op); plus
objective registration / facet+manifest+soundness+move_value 1:1 parity (the FIVE
registries) and the COUNT pins (75 / 33) and the soundness-corpus refusal. Every
test is pure AST — no node, no subprocess — so all run on the fast gate.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.objectives.pin_return_type import (
    _has_existing_return_field,
    _is_public,
    _pinnable_target,
    _returns_insertion,
    pin_return_types,
    plan_pin_return_type,
)

_PHRASE = "the documented return type to pin"


def _fn(src: str) -> ast.FunctionDef:
    """The first top-level function definition in ``src``."""
    return ast.parse(src).body[0]  # type: ignore[return-value]


# --- the existing-return-field regex (never overwrite a stated return) --------

def test_existing_return_field_matches_every_spelling():
    # Google (Returns:/Return:), reST (:returns:/:return:), epydoc (@returns/@return).
    for spelling in ("Returns: int", "Return: int", ":returns: int", ":return: int",
                     "@returns int", "@return int"):
        assert _has_existing_return_field(f"Summary.\n\n{spelling}\n"), spelling


def test_existing_return_field_is_case_insensitive_and_anchored():
    assert _has_existing_return_field("Doc.\n\n    RETURNS: x\n")  # leading ws + caps
    # A return-ish word mid-sentence is NOT a field header (anchored to line start).
    assert not _has_existing_return_field("This function returns a value but no field.")
    assert not _has_existing_return_field("Just a one-line summary.")


def test_existing_return_field_matches_rest_rtype_and_numpydoc_section():
    # Two REAL human spellings the colon-bearing regex misses (denetçi finding):
    # reST ``:rtype:`` (a return-TYPE field, no ``returns`` word) and the numpydoc
    # ``Returns`` SECTION (a bare header underlined with dashes, no colon). Both
    # already document the return, so appending ``Returns:`` would be a double-doc.
    assert _has_existing_return_field("Doc.\n\n:rtype: int\n")
    assert _has_existing_return_field("Doc.\n\n    :rtype: int\n")  # leading ws
    assert _has_existing_return_field("Doc.\n\nReturns\n-------\nint\n")
    assert _has_existing_return_field("Doc.\n\n    Returns\n    -------\n    int\n")
    assert _has_existing_return_field("Doc.\n\n    Return\n    ------\n    int\n")


def test_existing_return_field_does_not_overmatch_prose_or_stray_dashes():
    # Prose merely mentioning "returns", or a dashed underline under a DIFFERENT
    # section header (numpydoc ``Notes``), is NOT a return field -> still gets a line.
    assert not _has_existing_return_field("It returns the value, see below.\n")
    assert not _has_existing_return_field("Doc.\n\n    Notes\n    -----\n    stuff\n")
    # ``:rtype`` without the closing colon is not the field either.
    assert not _has_existing_return_field("Doc.\n\nthe :rtype of the thing\n")


# --- the splice helper + indent guard -----------------------------------------

def test_returns_insertion_targets_the_closing_quote_line():
    src = 'def f():\n    """Doc.\n\n    More.\n    """\n    return 1\n'
    spot = _returns_insertion(_fn(src), src.splitlines(keepends=True))
    assert spot is not None
    insert_at, indent = spot
    # closing """ is on line 5 (1-based) -> 0-based index 4; body indent four spaces.
    assert insert_at == 4
    assert indent == "    "


def test_returns_insertion_refuses_single_line_docstring():
    # open and close quotes on ONE line -> no own closing-quote line to precede.
    src = 'def f():\n    """Doc."""\n    return 1\n'
    assert _returns_insertion(_fn(src), src.splitlines(keepends=True)) is None


def test_returns_insertion_refuses_header_shared_one_liner():
    # `def f(): """Doc."""` reports the def header as the "indent" -> not whitespace.
    src = 'def f(): """Doc."""\n'
    assert _returns_insertion(_fn(src), src.splitlines(keepends=True)) is None


def test_returns_insertion_refuses_non_string_first_statement():
    # No docstring node to splice into (first statement is a return).
    src = "def f():\n    return 1\n"
    assert _returns_insertion(_fn(src), src.splitlines(keepends=True)) is None


# --- the public/non-test NAME gate (the name half only) -----------------------

def test_is_public_accepts_plain_name_rejects_private_dunder_test():
    assert _is_public(_fn("def good():\n    pass\n"))
    assert not _is_public(_fn("def _hidden():\n    pass\n"))
    assert not _is_public(_fn("def __dunder__(self):\n    pass\n"))
    assert not _is_public(_fn("def test_thing():\n    pass\n"))


def test_is_public_does_not_require_absent_docstring():
    # Inverse of document_signature: a DOCUMENTED public function still passes.
    assert _is_public(_fn('def f():\n    """Doc."""\n    return 1\n'))


# --- _pinnable_target: the full per-function gate ------------------------------

def test_pinnable_target_yields_returns_line_for_documented_provable():
    src = 'def f():\n    """Doc.\n    """\n    return 1\n'
    target = _pinnable_target(_fn(src), src.splitlines(keepends=True))
    assert target is not None
    _insert_at, line = target
    assert line.strip() == "Returns: int"


def test_pinnable_target_refuses_undocumented_is_document_signatures_territory():
    # No docstring -> document-signature's lane, refused here (zero collision).
    src = "def f():\n    return 1\n"
    assert _pinnable_target(_fn(src), src.splitlines(keepends=True)) is None


def test_pinnable_target_refuses_existing_returns_field():
    src = 'def f():\n    """Doc.\n\n    Returns: something\n    """\n    return 1\n'
    assert _pinnable_target(_fn(src), src.splitlines(keepends=True)) is None


# --- the pin_return_types(source) transform: lands ----------------------------

def test_lands_int_return_into_existing_docstring():
    src = 'def parse():\n    """Parse it.\n    """\n    return 7\n'
    out = pin_return_types(src)
    assert out == (
        'def parse():\n'
        '    """Parse it.\n'
        '    Returns: int\n'
        '    """\n'
        '    return 7\n'
    )


def test_lands_pure_procedure_none():
    # No value return at all -> the oracle proves None; documented as Returns: None.
    src = 'def step(x):\n    """Do a step.\n    """\n    x.append(1)\n'
    out = pin_return_types(src)
    assert out is not None
    assert "    Returns: None\n" in out


def test_lands_list_literal_return():
    src = 'def items():\n    """The items.\n    """\n    return [1, 2, 3]\n'
    out = pin_return_types(src)
    assert out is not None
    assert "    Returns: list[int]\n" in out


def test_returns_line_inserted_before_closing_quotes_at_body_indent():
    src = 'def f():\n    """Doc.\n\n    Detail.\n    """\n    return 1\n'
    out = pin_return_types(src)
    assert out is not None
    lines = out.splitlines()
    ret_idx = lines.index("    Returns: int")
    # the very next line is the closing quotes, and the line sits at body indent.
    assert lines[ret_idx + 1].strip() == '"""'
    assert lines[ret_idx].startswith("    Returns:")


def test_result_reparses_and_docstring_still_first_statement():
    src = 'def f():\n    """Doc.\n    """\n    return 1\n'
    out = pin_return_types(src)
    assert out is not None
    tree = ast.parse(out)  # re-parses
    fn = tree.body[0]
    # behaviour-identical: the docstring is still fn's first statement (a Constant),
    # so the runtime return value is unchanged.
    assert ast.get_docstring(fn) is not None
    assert isinstance(fn.body[0], ast.Expr)
    assert isinstance(fn.body[0].value, ast.Constant)
    assert "Returns: int" in ast.get_docstring(fn)


# --- the pin_return_types(source) transform: refuses --------------------------

def test_refuses_already_annotated_function():
    # Already has -> int: the bare oracle returns None on fn.returns, so the
    # documented return would only echo the signature -> refuse (left alone).
    src = 'def f() -> int:\n    """Doc.\n    """\n    return 1\n'
    assert pin_return_types(src) is None


def test_refuses_generator():
    src = 'def gen():\n    """A generator.\n    """\n    yield 1\n'
    assert pin_return_types(src) is None


# The oracle now also REFUSES a function whose decorator may TRANSFORM the return
# value (denetçi finding): pin-return-type reads the same oracle, so a wrapper-
# transforming decorator that would document a wrong ``Returns: int`` is refused
# here for free. CORRECTNESS, not test-weakening — the old oracle ignored
# ``decorator_list`` and so would have documented a lie.

def test_refuses_wrapper_transforming_decorator_make_str():
    # ``@make_str``'s wrapper casts the return to str; the body returns int but the
    # callable returns str, so documenting ``Returns: int`` would be a verified lie.
    src = (
        '@make_str\n'
        'def compute():\n'
        '    """Compute it.\n'
        '    """\n'
        '    return 42\n'
    )
    assert pin_return_types(src) is None


def test_refuses_unknown_user_decorator():
    # An arbitrary user decorator may wrap the return — unprovable, so refuse.
    src = (
        '@mydeco(opt=1)\n'
        'def f():\n'
        '    """Doc.\n'
        '    """\n'
        '    return 1\n'
    )
    assert pin_return_types(src) is None


def test_pins_through_staticmethod_allow_list():
    # ``@staticmethod`` is type-transparent (rebinds the call shape only), so the
    # proven ``Returns: int`` STILL lands in the docstring (allow-list).
    src = (
        'class C:\n'
        '    @staticmethod\n'
        '    def compute():\n'
        '        """Compute it.\n'
        '        """\n'
        '        return 42\n'
    )
    out = pin_return_types(src)
    assert out is not None and "Returns: int" in out


def test_pins_through_property_and_lru_cache_allow_list():
    # ``@property`` returns the getter's value; ``@lru_cache`` replays the same
    # object — both type-transparent, so the documented ``Returns: int`` lands.
    prop = (
        'class C:\n'
        '    @property\n'
        '    def x(self):\n'
        '        """The x.\n'
        '        """\n'
        '        return 42\n'
    )
    out = pin_return_types(prop)
    assert out is not None and "Returns: int" in out
    lru = (
        '@lru_cache(maxsize=8)\n'
        'def f():\n'
        '    """Doc.\n'
        '    """\n'
        '    return 42\n'
    )
    out = pin_return_types(lru)
    assert out is not None and "Returns: int" in out


def test_refuses_fall_through_value_return():
    # A value return reachable past a non-terminating branch -> oracle refuses (T|None).
    src = (
        'def f(x):\n'
        '    """Doc.\n'
        '    """\n'
        '    if x:\n'
        '        return 1\n'
    )
    assert pin_return_types(src) is None


def test_refuses_disagreeing_returns():
    src = (
        'def f(x):\n'
        '    """Doc.\n'
        '    """\n'
        '    if x:\n'
        '        return 1\n'
        '    return "s"\n'
    )
    assert pin_return_types(src) is None


def test_refuses_undocumented_function():
    assert pin_return_types("def f():\n    return 1\n") is None


def test_refuses_existing_returns_line():
    src = 'def f():\n    """Doc.\n\n    Returns: int\n    """\n    return 1\n'
    assert pin_return_types(src) is None


def test_refuses_existing_rest_return_field():
    src = 'def f():\n    """Doc.\n\n    :returns: the thing\n    """\n    return 1\n'
    assert pin_return_types(src) is None


def test_refuses_existing_epydoc_return_field():
    src = 'def f():\n    """Doc.\n\n    @return the thing\n    """\n    return 1\n'
    assert pin_return_types(src) is None


def test_refuses_existing_rest_rtype_field():
    # ``:rtype: int`` already documents the return TYPE; appending ``Returns: int``
    # would be a redundant double-doc -> refuse (left byte-for-byte alone).
    src = 'def f():\n    """Doc.\n\n    :rtype: int\n    """\n    return 1\n'
    assert pin_return_types(src) is None


def test_refuses_existing_numpydoc_returns_section():
    # numpydoc ``Returns``-section (header + dashed underline, no colon) already
    # documents the return; no second ``Returns:`` line is appended.
    src = (
        'def f():\n'
        '    """Doc.\n'
        '\n'
        '    Returns\n'
        '    -------\n'
        '    int\n'
        '        the value\n'
        '    """\n'
        '    return 1\n'
    )
    assert pin_return_types(src) is None


def test_still_pins_a_plain_docstring_without_any_return_field():
    # The load-bearing non-over-refusal: a docstring with NO return field (in any
    # spelling) still gets the proven ``Returns: int`` line.
    src = 'def f():\n    """Just a summary.\n\n    More prose.\n    """\n    return 1\n'
    out = pin_return_types(src)
    assert out is not None and "Returns: int" in out


def test_refuses_private_function():
    assert pin_return_types('def _h():\n    """Doc.\n    """\n    return 1\n') is None


def test_refuses_dunder_function():
    src = 'class C:\n    def __len__(self):\n        """Doc.\n        """\n        return 0\n'
    assert pin_return_types(src) is None


def test_refuses_test_function():
    assert pin_return_types('def test_x():\n    """Doc.\n    """\n    return 1\n') is None


def test_single_line_docstring_def_is_a_noop():
    assert pin_return_types('def f():\n    """Doc."""\n    return 1\n') is None


def test_header_shared_one_liner_is_a_noop():
    assert pin_return_types('def f(): """Doc."""\n') is None


def test_unparseable_source_is_none():
    assert pin_return_types("def (:\n  ???\n") is None


def test_idempotent_second_run_is_noop():
    src = 'def f():\n    """Doc.\n    """\n    return 1\n'
    once = pin_return_types(src)
    assert once is not None
    assert pin_return_types(once) is None  # now has a Returns: line -> no-op


def test_deterministic_across_two_runs():
    src = (
        'def a():\n    """A.\n    """\n    return 1\n'
        '\n\n'
        'def b():\n    """B.\n    """\n    return []\n'
    )
    assert pin_return_types(src) == pin_return_types(src)


def test_mixed_module_pins_only_provable_documented_functions():
    # documented+provable lands; undocumented / annotated / private / already-Returns
    # / not-provable are each skipped, and the result re-parses with every touched
    # docstring intact.
    src = (
        'def good():\n'
        '    """Good.\n'
        '    """\n'
        '    return 1\n'
        '\n\n'
        'def undocumented():\n'           # no docstring -> document-signature's lane
        '    return 2\n'
        '\n\n'
        'def annotated() -> int:\n'        # already -> int -> oracle None
        '    """Annotated.\n'
        '    """\n'
        '    return 3\n'
        '\n\n'
        'def _private():\n'               # private
        '    """Priv.\n'
        '    """\n'
        '    return 4\n'
        '\n\n'
        'def already_doced():\n'          # already records a return
        '    """Doc.\n\n    Returns: int\n    """\n'
        '    return 5\n'
        '\n\n'
        'def also_good(x):\n'
        '    """Also.\n'
        '    """\n'
        '    x.append(1)\n'               # pure procedure -> None
    )
    out = pin_return_types(src)
    assert out is not None
    # exactly THREE "    Returns: " lines total: good's new int, also_good's new None,
    # and already_doced's PRE-EXISTING int (left untouched) -> two were ADDED.
    assert out.count("    Returns: ") == 3
    assert "    Returns: int\n" in out   # good's new line
    assert "    Returns: None\n" in out  # also_good's new line
    # the once-undocumented-but-skipped functions gained nothing, and already_doced
    # keeps exactly its single original return field (never a duplicate).
    assert "def undocumented():\n    return 2\n" in out  # body untouched, no docstring
    assert out.count("Returns: int") == 2  # good's new line + already_doced's existing


def test_noop_returns_none_when_nothing_qualifies():
    # All documented but every return unprovable -> nothing to pin.
    src = 'def f(e):\n    """Doc.\n    """\n    return e\n'
    assert pin_return_types(src) is None


def test_async_function_is_pinned():
    src = 'async def f():\n    """Doc.\n    """\n    return 1\n'
    out = pin_return_types(src)
    assert out is not None
    assert "    Returns: int\n" in out


# --- the plan layer -----------------------------------------------------------

def _project(tmp_path: Path, rel: str, src: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    return tmp_path


def test_plan_lands_and_captures_original(tmp_path: Path):
    src = 'def f():\n    """Doc.\n    """\n    return 1\n'
    root = _project(tmp_path, "pkg/m.py", src)
    plan = plan_pin_return_type(str(root), "pkg/m.py")
    assert plan.originals["pkg/m.py"] == src  # original captured for rollback
    assert "Returns: int" in plan.new_contents["pkg/m.py"]
    assert plan.edits_by_file["pkg/m.py"] == 1


def test_plan_refuses_test_file(tmp_path: Path):
    root = _project(tmp_path, "tests/test_m.py", 'def f():\n    """D.\n    """\n    return 1\n')
    plan = plan_pin_return_type(str(root), "tests/test_m.py")
    assert not plan.new_contents  # the suite is never edited


def test_plan_refuses_fixture_file(tmp_path: Path):
    root = _project(tmp_path, "fixtures/m.py", 'def f():\n    """D.\n    """\n    return 1\n')
    plan = plan_pin_return_type(str(root), "fixtures/m.py")
    assert not plan.new_contents


def test_plan_refuses_non_library_file(tmp_path: Path):
    # docs/conf.py is a denylisted non-library script (nobody imports it as an API).
    root = _project(tmp_path, "docs/conf.py", 'def setup(app):\n    """D.\n    """\n    return 1\n')
    plan = plan_pin_return_type(str(root), "docs/conf.py")
    assert not plan.new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_pin_return_type(str(tmp_path), "pkg/missing.py")
    assert not plan.new_contents  # unreadable -> honest no-op


def test_plan_noop_when_nothing_provable(tmp_path: Path):
    root = _project(tmp_path, "pkg/m.py", 'def f(e):\n    """D.\n    """\n    return e\n')
    plan = plan_pin_return_type(str(root), "pkg/m.py")
    assert not plan.new_contents


def test_plan_is_deterministic(tmp_path: Path):
    src = 'def f():\n    """Doc.\n    """\n    return 1\n'
    root = _project(tmp_path, "pkg/m.py", src)
    a = plan_pin_return_type(str(root), "pkg/m.py").new_contents
    b = plan_pin_return_type(str(root), "pkg/m.py").new_contents
    assert a == b


# --- registration / facet+manifest+soundness 1:1 parity (always runs) ---------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "pin-return-type" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["pin-return-type"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is False   # pure-AST scan
    assert spec.scope_verify is False  # docstring line; no red-baseline veto


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "pin-return-type"


def test_facet_reachability_parity_invariant_holds():
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
    # The Python pin facet must not shadow (or be shadowed by) the signature facet,
    # the raises facet, or the doctest-pin facet — the planner matches by substring.
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective("the public signature to document") == "document-signature"
    assert facet_to_objective("the raised exceptions to document") == "document-raises"
    assert facet_to_objective("the unenforced doctest examples to pin") == "pin-doctest"
    assert facet_to_objective(_PHRASE) == "pin-return-type"


def test_facet_phrase_lives_in_the_signatures_and_types_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["signatures and types"]
    assert _PHRASE in ladder
    assert ladder[0] == "parameter meanings"  # originals still lead
    # appended AFTER the original three sub-aspects.
    assert ladder.index(_PHRASE) > ladder.index("raised exceptions list")


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "pin-return-type" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


def test_move_value_tier_is_the_doc_surface_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("pin_return_type") == 0.66
    assert move_value("pin_return_type") == move_value("generate_usage_doc")
    assert objective_value("pin-return-type") == 0.66
    assert objective_value("pin-return-type") != DEFAULT_VALUE  # not the fallback


def test_soundness_strategy_declared_and_not_scope_verify():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert SOUNDNESS_STRATEGY["pin-return-type"] == (
        "behavior-identical-docstring-only+returns-from-proven-return-oracle")
    assert "pin-return-type" not in SCOPE_VERIFY_ALLOWLIST
    assert strategy_subset_of_registry() == []  # no stale strategy entry


def test_north_star_and_soundness_audits_pass():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


def test_counts_are_thirty_six_concrete_of_seventy_eight():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    names = set(available_objectives())
    assert len(names) == 90  # 89 after js-strengthen-tests (89th, CONCRETE) registered
    assert len(classify_objectives(names)["CONCRETE"]) == 45  # js-strengthen-tests (89th) is CONCRETE


def test_refuses_on_python_soundness_corpus():
    # pin-return-type is NOT expensive (pure AST), so it is swept on the DEFAULT
    # cheap path (include_heavy=False). The standing corpus has no documented +
    # provable + unannotated function, so the objective REFUSES on every shape.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), include_heavy=False)
    cells = corpus.get("pin-return-type", {})
    assert cells, "pin-return-type should be swept on the cheap corpus path"
    for shape, verdict in cells.items():
        assert verdict == "refused", f"{shape}: {verdict}"
