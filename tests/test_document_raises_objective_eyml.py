"""document-raises develop objective — the Python sibling of the shipped JS
document-raises-jsdoc (``@throws``). Land a docstring carrying one
``Raises: <ErrorName>`` line per DISTINCT *escaping* literal ``raise
<ErrorName>(...)`` in a PUBLIC, currently-UNDOCUMENTED function, the name read
VERBATIM off the AST — never inferred.

Covers: the escape walker / honesty gate (single / two-distinct-source-order /
duplicate-collapse / descend-if-for-while / scope-stop at nested
def/lambda/class) and its FULL refusal set (a ``raise <var>``, a lowercase factory
call, a dotted ctor, a bare re-raise, a mixed provable+unprovable body, a
try-with-except AND a try*/except* swallow guard, a raise inside a
``with``/``async with`` whose context manager could suppress it (contextlib.suppress
and the could-really-escape ``open()`` case) — while a try/finally with NO except
still lands AND a raise outside any with still lands);
the docstring block + the "a Raises line is content the signature lacks" bar; the
``document_raises`` transform (lands, refuses already-doc'd/private/dunder/test_,
the single-line-body indent guard, unparseable source, idempotence, determinism,
a mixed module landing only the provable functions with the self-validation count
dropping by exactly the landed count); the plan layer (lands + captures the
original, refuses test/fixture/non-library, unreadable no-op, determinism); plus
objective registration / facet+manifest+soundness 1:1 parity (the FIVE registries
the new objective must appear in) and the COUNT pins (74 / 32). Every test is pure
AST — no node, no subprocess — so all run on the fast gate.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.objectives.document_raises import (
    _documentable_target,
    _escaping_raises,
    _is_public_undocumented,
    _proven_raise_name,
    _raises_lines,
    document_raises,
    plan_document_raises,
)

_PHRASE = "the raised exceptions to document"


def _fn(src: str) -> ast.FunctionDef:
    """The first top-level function definition in ``src``."""
    return ast.parse(src).body[0]  # type: ignore[return-value]


# --- the escape walker / honesty gate (the soundness core) --------------------

def test_escaping_raises_single_literal():
    assert _escaping_raises(_fn("def f():\n    raise ValueError('x')\n")) == ["ValueError"]


def test_escaping_raises_two_distinct_source_order():
    fn = _fn("def f():\n    if a:\n        raise ValueError()\n    raise KeyError()\n")
    assert _escaping_raises(fn) == ["ValueError", "KeyError"]


def test_escaping_raises_duplicate_collapses():
    fn = _fn("def f():\n    raise RuntimeError()\n    raise RuntimeError()\n")
    assert _escaping_raises(fn) == ["RuntimeError"]  # one line


def test_escaping_raises_descends_if_for_while():
    # if/for/while are plain control flow that cannot swallow a raise, so a raise
    # nested in them escapes. (``with`` is handled separately: a context manager
    # COULD suppress, so a raise under it is refused — see the with-swallow tests.)
    fn = _fn(
        "def f():\n"
        "    for x in y:\n"
        "        while c:\n"
        "            if a:\n"
        "                raise IndexError()\n"
    )
    assert _escaping_raises(fn) == ["IndexError"]


def test_refuses_raise_of_variable():
    # raise <var>: r.exc is an ast.Name, not an ast.Call -> unprovable.
    assert _escaping_raises(_fn("def f():\n    raise e\n")) is None


def test_refuses_raise_of_lowercase_call():
    # raise make_error(): the callee is lowercase, a factory not a ctor -> refuse.
    assert _escaping_raises(_fn("def f():\n    raise make_error()\n")) is None


def test_refuses_dotted_ctor():
    # raise mod.Err(): r.exc.func is an ast.Attribute, not a bare Name -> refuse.
    assert _escaping_raises(_fn("def f():\n    raise mod.Err()\n")) is None


def test_refuses_bare_reraise():
    fn = _fn("def f():\n    try:\n        g()\n    finally:\n        raise\n")
    assert _escaping_raises(fn) is None


def test_refuses_mixed_provable_and_unprovable():
    # A provable raise FIRST, then an unprovable one: the whole function refuses.
    fn = _fn("def f():\n    raise ValueError()\n    raise e\n")
    assert _escaping_raises(fn) is None


def test_zero_raise_is_empty_not_none():
    # Honest no-op: nothing escapes -> [] (distinct from None = unprovable).
    assert _escaping_raises(_fn("def f():\n    return 1\n")) == []


def test_nested_def_raise_not_attributed():
    fn = _fn(
        "def f():\n"
        "    def helper():\n"
        "        raise ValueError()\n"
        "    return helper\n"
    )
    assert _escaping_raises(fn) == []  # scope-stop: helper's raise is not f's


def test_nested_lambda_raise_not_attributed():
    # A lambda body is never an ast.stmt, so its raises are invisible too.
    fn = _fn("def f():\n    g = lambda: (_ for _ in ()).throw(ValueError())\n    return g\n")
    assert _escaping_raises(fn) == []


def test_nested_class_raise_not_attributed():
    fn = _fn(
        "def f():\n"
        "    class C:\n"
        "        def m(self):\n"
        "            raise ValueError()\n"
        "    return C\n"
    )
    assert _escaping_raises(fn) == []  # scope-stop at the nested class


def test_try_with_except_refuses_whole_function():
    # A try-with-non-empty-except anywhere in the body could swallow -> refuse,
    # even though there is a direct provable raise before it.
    fn = _fn(
        "def f():\n"
        "    raise ValueError()\n"
        "    try:\n"
        "        g()\n"
        "    except Exception:\n"
        "        pass\n"
    )
    assert _escaping_raises(fn) is None


def test_direct_raise_inside_try_with_except_refuses():
    # A raise inside a try body whose except catches it -> swallow guard refuses.
    fn = _fn(
        "def f():\n"
        "    try:\n"
        "        raise ValueError()\n"
        "    except Exception:\n"
        "        pass\n"
    )
    assert _escaping_raises(fn) is None


def test_try_finally_without_except_still_attributes():
    # try/finally with NO except does NOT swallow -> the escaping raise lands.
    fn = _fn(
        "def f():\n"
        "    try:\n"
        "        raise ValueError()\n"
        "    finally:\n"
        "        cleanup()\n"
    )
    assert _escaping_raises(fn) == ["ValueError"]


def test_try_finally_raise_in_finally_attributes():
    fn = _fn(
        "def f():\n"
        "    try:\n"
        "        g()\n"
        "    finally:\n"
        "        raise RuntimeError()\n"
    )
    assert _escaping_raises(fn) == ["RuntimeError"]


def test_with_suppress_swallow_refuses():
    # contextlib.suppress(ValueError).__exit__ returns truthy -> it SWALLOWS the
    # raise. The CM body cannot be proven escaping, so the function is refused.
    fn = _fn(
        "def f():\n"
        "    with contextlib.suppress(ValueError):\n"
        "        raise ValueError('x')\n"
    )
    assert _escaping_raises(fn) is None


def test_with_raise_refused_even_if_it_would_escape():
    # We cannot prove an ARBITRARY context manager is non-suppressing (its __exit__
    # may return truthy), so a raise inside ANY with body is refused — sound even
    # though this particular `open()` CM would let the raise escape. A false
    # NEGATIVE (a missed real Raises:) is acceptable; a false positive is not.
    fn = _fn(
        "def f(p):\n"
        "    with open(p) as fh:\n"
        "        raise IOError('boom')\n"
    )
    assert _escaping_raises(fn) is None


def test_async_with_raise_refused():
    # async with has the same swallow surface as with -> a raise in its body is
    # refused (the __aexit__ may suppress).
    fn = _fn(
        "async def f(ctx):\n"
        "    async with ctx:\n"
        "        raise ValueError('x')\n"
    )
    assert _escaping_raises(fn) is None


def test_raise_before_with_in_same_body_attributes():
    # A raise OUTSIDE any with is still provably escaping; only the with-body raise
    # would be refused. Here the only raise is before the (raise-free) with body,
    # so it lands normally.
    fn = _fn(
        "def f():\n"
        "    raise KeyError()\n"
        "    with lock:\n"
        "        do_work()\n"
    )
    assert _escaping_raises(fn) == ["KeyError"]


def test_try_star_with_except_star_swallow_refuses():
    # PEP 654 try/except* can catch-and-swallow a raise exactly like a plain
    # try/except, so the TryStar swallow guard refuses it too.
    fn = _fn(
        "def f():\n"
        "    try:\n"
        "        raise ValueError('x')\n"
        "    except* ValueError:\n"
        "        pass\n"
    )
    assert _escaping_raises(fn) is None


def test_try_star_is_an_ast_try_star_node():
    # Guard the precondition: ``try/except*`` parses to ``ast.TryStar`` (NOT
    # ``ast.Try``), so the swallow guard must name BOTH types — which it now does.
    node = _fn(
        "def f():\n"
        "    try:\n"
        "        g()\n"
        "    except* ValueError:\n"
        "        pass\n"
    ).body[0]
    assert isinstance(node, ast.TryStar)


def test_async_function_escaping_raises():
    fn = _fn("async def f():\n    raise ValueError()\n")
    assert _escaping_raises(fn) == ["ValueError"]


def test_match_case_raise_is_a_conservative_noop():
    # A raise inside a ``match``/``case`` is not an ``ast.stmt`` child the walk
    # reaches (mirroring exception_hygiene._direct_raises, which also only recurses
    # ast.stmt children) -> [] (an honest under-claim no-op, never a wrong line).
    fn = _fn("def f(x):\n    match x:\n        case 1:\n            raise ValueError()\n")
    assert _escaping_raises(fn) == []


def test_proven_raise_name_reads_camelcase_ctor():
    node = _fn("def f():\n    raise ValueError('x')\n").body[0]
    assert _proven_raise_name(node) == "ValueError"


def test_proven_raise_name_refuses_bare_var_dotted_lowercase():
    # Each unprovable shape -> None (the per-raise honesty primitive).
    assert _proven_raise_name(_fn("def f():\n    raise e\n").body[0]) is None
    assert _proven_raise_name(_fn("def f():\n    raise mod.Err()\n").body[0]) is None
    assert _proven_raise_name(_fn("def f():\n    raise make_error()\n").body[0]) is None
    # a bare re-raise has exc=None
    bare = _fn("def f():\n    try:\n        g()\n    finally:\n        raise\n").body[0].finalbody[0]
    assert _proven_raise_name(bare) is None


# --- docstring block + content bar --------------------------------------------

def test_block_emits_one_raises_line_per_distinct_in_order():
    lines = _raises_lines(_fn("def name():\n    pass\n"), "    ", ["ValueError", "KeyError"])
    assert lines == [
        '    """name.\n', "\n", "    Raises:\n",
        "        ValueError\n", "        KeyError\n", '    """\n',
    ]


def test_block_single_raises_line():
    lines = _raises_lines(_fn("def g():\n    pass\n"), "    ", ["RuntimeError"])
    assert lines == [
        '    """g.\n', "\n", "    Raises:\n", "        RuntimeError\n", '    """\n',
    ]


def test_raises_line_is_content_the_signature_lacks():
    # The honesty/content bar: a non-empty escaping set is always landable (a
    # Raises line names a fact the signature never carries), so _documentable_target
    # yields a placement. (A signature restatement could not, by construction.)
    src = "def f(x):\n    raise ValueError()\n"
    fn = _fn(src)
    target = _documentable_target(fn, src.splitlines(keepends=True))
    assert target is not None
    _insert_at, doc_lines = target
    assert any("Raises:" in line for line in doc_lines)


# --- the document_raises(source) transform ------------------------------------

def test_lands_docstring_with_raises_block():
    src = "def parse(x):\n    raise ValueError('bad')\n"
    out = document_raises(src)
    assert out == (
        'def parse(x):\n'
        '    """parse.\n\n    Raises:\n        ValueError\n    """\n'
        "    raise ValueError('bad')\n"
    )


def test_refuses_already_documented():
    src = 'def f():\n    """already."""\n    raise ValueError()\n'
    assert document_raises(src) is None


def test_refuses_private_function():
    assert document_raises("def _helper():\n    raise ValueError()\n") is None


def test_refuses_dunder_function():
    src = "class C:\n    def __init__(self):\n        raise ValueError()\n"
    assert document_raises(src) is None


def test_refuses_test_function():
    assert document_raises("def test_thing():\n    raise ValueError()\n") is None


def test_single_line_body_def_is_a_noop():
    # `def f(): raise ValueError()` reports the HEADER as indent (not whitespace);
    # the indent guard refuses it rather than corrupting the line.
    assert document_raises("def f(): raise ValueError()\n") is None


def test_zero_escaping_raise_function_is_a_noop():
    assert document_raises("def f(x):\n    return x + 1\n") is None


def test_unprovable_shape_function_is_a_noop():
    assert document_raises("def f(e):\n    raise e\n") is None


def test_with_suppress_lands_no_raises_docstring():
    # End-to-end: a function whose ONLY raise is under contextlib.suppress is
    # refused -> nothing lands (no false ``Raises:``).
    src = (
        "def f():\n"
        "    with contextlib.suppress(ValueError):\n"
        "        raise ValueError('x')\n"
    )
    assert document_raises(src) is None


def test_with_open_raise_lands_no_raises_docstring():
    # End-to-end: a raise inside ``with open(...)`` is refused (the CM could
    # suppress), so no docstring is landed even though it would really escape.
    src = (
        "def f(p):\n"
        "    with open(p) as fh:\n"
        "        raise IOError('boom')\n"
    )
    assert document_raises(src) is None


def test_try_star_swallow_lands_no_raises_docstring():
    # End-to-end: a try/except* that swallows the raise is refused -> nothing lands.
    src = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('x')\n"
        "    except* ValueError:\n"
        "        pass\n"
    )
    assert document_raises(src) is None


def test_try_finally_still_lands_raises_docstring():
    # Regression guard: a try/finally with NO except does NOT swallow, so the
    # escaping ``KeyError`` is STILL documented end-to-end.
    src = (
        "def f():\n"
        "    try:\n"
        "        raise KeyError('k')\n"
        "    finally:\n"
        "        cleanup()\n"
    )
    out = document_raises(src)
    assert out is not None
    assert '"""f.\n' in out
    assert "        KeyError\n" in out


def test_plain_top_level_raise_still_lands_raises_docstring():
    # Regression guard: a bare top-level raise (no with/try) is documented exactly
    # as before — only CM-enclosed raises change behaviour.
    src = "def f(x):\n    raise ValueError('bad')\n"
    out = document_raises(src)
    assert out is not None
    assert "    Raises:\n" in out
    assert "        ValueError\n" in out


def test_unparseable_source_is_none():
    assert document_raises("def (:\n  ???\n") is None


def test_idempotent_second_run_is_noop():
    src = "def f():\n    raise ValueError()\n"
    once = document_raises(src)
    assert once is not None
    assert document_raises(once) is None  # now documented -> byte-identical no-op


def test_deterministic_across_two_runs():
    src = "def a():\n    raise ValueError()\n\n\ndef b():\n    raise KeyError()\n"
    assert document_raises(src) == document_raises(src)


def test_mixed_module_lands_only_provable_functions():
    # public+escaping lands; private / unprovable / zero-raise / already-doc'd /
    # test_ are skipped, and the self-validation count drops by EXACTLY the landed
    # count (else the whole change is refused).
    src = (
        "def good():\n"
        "    raise ValueError()\n"
        "\n\n"
        "def _private():\n"
        "    raise KeyError()\n"
        "\n\n"
        "def unprovable(e):\n"
        "    raise e\n"
        "\n\n"
        "def silent(x):\n"
        "    return x\n"
        "\n\n"
        "def also_good():\n"
        "    raise RuntimeError()\n"
    )
    out = document_raises(src)
    assert out is not None
    assert out.count('"""') == 4  # exactly TWO docstrings landed (open+close each)
    assert '"""good.\n' in out
    assert '"""also_good.\n' in out
    assert "        ValueError\n" in out
    assert "        RuntimeError\n" in out
    # the skipped functions gained nothing
    assert "_private." not in out
    assert "unprovable." not in out
    assert "silent." not in out


# --- the plan layer -----------------------------------------------------------

def _project(tmp_path: Path, rel: str, src: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    return tmp_path


def test_plan_lands_and_captures_original(tmp_path: Path):
    src = "def f():\n    raise ValueError()\n"
    root = _project(tmp_path, "pkg/m.py", src)
    plan = plan_document_raises(str(root), "pkg/m.py")
    assert plan.originals["pkg/m.py"] == src  # original captured for rollback
    assert plan.new_contents["pkg/m.py"]
    assert "Raises:" in plan.new_contents["pkg/m.py"]
    assert plan.edits_by_file["pkg/m.py"] == 1


def test_plan_refuses_test_file(tmp_path: Path):
    root = _project(tmp_path, "tests/test_m.py", "def f():\n    raise ValueError()\n")
    plan = plan_document_raises(str(root), "tests/test_m.py")
    assert not plan.new_contents  # the suite is never edited


def test_plan_refuses_fixture_file(tmp_path: Path):
    root = _project(tmp_path, "fixtures/m.py", "def f():\n    raise ValueError()\n")
    plan = plan_document_raises(str(root), "fixtures/m.py")
    assert not plan.new_contents


def test_plan_refuses_non_library_file(tmp_path: Path):
    # docs/conf.py is a denylisted non-library script (nobody imports it as an API).
    root = _project(tmp_path, "docs/conf.py", "def setup(app):\n    raise ValueError()\n")
    plan = plan_document_raises(str(root), "docs/conf.py")
    assert not plan.new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_document_raises(str(tmp_path), "pkg/missing.py")
    assert not plan.new_contents  # unreadable -> honest no-op


def test_plan_noop_when_nothing_provable(tmp_path: Path):
    root = _project(tmp_path, "pkg/m.py", "def f(x):\n    return x\n")
    plan = plan_document_raises(str(root), "pkg/m.py")
    assert not plan.new_contents


def test_plan_is_deterministic(tmp_path: Path):
    src = "def f():\n    raise ValueError()\n"
    root = _project(tmp_path, "pkg/m.py", src)
    a = plan_document_raises(str(root), "pkg/m.py").new_contents
    b = plan_document_raises(str(root), "pkg/m.py").new_contents
    assert a == b


def test_is_public_undocumented_is_the_shared_gate():
    # Reused VERBATIM from document_signature (import identity), so the refusal
    # semantics are exactly the shared lane's.
    from app.execution.objectives import document_signature

    assert _is_public_undocumented is document_signature._is_public_undocumented


# --- registration / facet+manifest+soundness 1:1 parity (always runs) ---------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "document-raises" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["document-raises"]
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is False  # pure-AST scan (unlike the node-spawning JS sibling)
    assert spec.scope_verify is False  # docstring insert; no red-baseline veto


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "document-raises"


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
    # The Python doc facet must not shadow (or be shadowed by) the signature facet
    # or the three JSDoc facets — the planner matches by substring.
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective("the public signature to document") == "document-signature"
    assert facet_to_objective("the thrown error types to document in jsdoc") \
        == "document-raises-jsdoc"
    assert facet_to_objective(_PHRASE) == "document-raises"


def test_facet_phrase_lives_in_the_raised_exceptions_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["raised exceptions"]
    assert _PHRASE in ladder
    assert ladder[0] == "which type when"  # originals still lead
    # appended AFTER the three original sub-aspects.
    assert ladder.index(_PHRASE) > ladder.index("error message contract")


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "document-raises" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


def test_move_value_tier_matches_doc_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("document_raises") == 0.68
    assert move_value("document_raises") == move_value("document_signature")
    assert objective_value("document-raises") == 0.68
    assert objective_value("document-raises") != DEFAULT_VALUE  # not the fallback


def test_soundness_strategy_declared_and_not_scope_verify():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert SOUNDNESS_STRATEGY["document-raises"] == (
        "behavior-identical-docstring-only"
        "+raises-from-literal-raise-Name-verbatim"
        "+escape-only(stop-at-nested-scope,try-with-except-refuses)")
    # scope_verify=False -> it must NOT be in the audited allowlist.
    assert "document-raises" not in SCOPE_VERIFY_ALLOWLIST
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
    assert len(names) == 85  # 85 after promote-staticmethod (85th, TIDY) registered
    assert len(classify_objectives(names)["CONCRETE"]) == 41  # promote-staticmethod (85th) is TIDY, not CONCRETE


def test_refuses_on_python_soundness_corpus():
    # document-raises is NOT expensive (pure AST), so it is swept on the DEFAULT
    # cheap path (include_heavy=False). The standing corpus is Python-shaped with
    # ZERO `raise` statements, so the objective REFUSES on every fixture shape.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), include_heavy=False)
    cells = corpus.get("document-raises", {})
    assert cells, "document-raises should be swept on the cheap corpus path"
    for shape, verdict in cells.items():
        assert verdict == "refused", f"{shape}: {verdict}"
