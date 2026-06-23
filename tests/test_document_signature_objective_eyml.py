"""document-signature develop objective — land a PROVEN docstring on an
undocumented public function.

Covers: objective registration / reachability (a facet phrase routes to it and
the facet-map↔registry parity invariant still holds); the transform documents a
public undocumented function ONLY when its return type is PROVABLE (param names
as AST facts + a ``Returns: <type>`` line from the existing return-type oracle,
or from an existing ``-> T`` annotation); the CRITICAL GATE — when the return
type is NOT provable it lands NOTHING (never a placeholder skeleton); every
refusal (already-documented, private/dunder, ``test_*``, test/fixture file); the
docstring is behaviour-preserving (the function still parses and runs) and the
``__doc__`` is set; idempotency (a second run is a byte-identical no-op); and
determinism (same input -> same output).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.objectives.document_signature import (
    document_signatures,
    plan_document_signature,
)


# --- registration / reachability ---------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "document-signature" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["document-signature"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_reachable_from_a_facet():
    # A facet phrase must route to it, else `apex objectives` shows it as
    # unreachable and the facet/objective integrity test fails.
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(
        "the public signature to document") == "document-signature"


def test_facet_reachability_parity_invariant_holds():
    # The standing 1:1 invariant: the facet map reaches EXACTLY the registered
    # objectives. Adding document-signature to BOTH sides keeps the equality.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_facet_phrase_lives_in_the_signatures_and_types_ladder():
    # The phrase is genuinely present in the document lens's ladder (so the zoom
    # can emit it), with the originals still leading.
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["signatures and types"]
    assert "the public signature to document" in ladder
    assert ladder[0] == "parameter meanings"  # originals still lead


# --- accepts: a proven docstring lands ---------------------------------------

def test_documents_public_fn_with_provable_int_return():
    out = document_signatures("def size(xs):\n    return len(xs)\n")
    assert out is not None
    assert '"""size.' in out          # name-derived summary (a fact)
    assert "Args:" in out and "xs" in out  # param name listed (an AST fact)
    assert "Returns: int" in out       # proven type from the oracle


def test_documents_pure_procedure_with_returns_none():
    # A pure procedure provably returns None (the oracle proves ``"None"``), so
    # it is documented with ``Returns: None`` — not refused.
    out = document_signatures("def emit(msg, level):\n    print(msg)\n")
    assert out is not None
    assert "Returns: None" in out
    assert "msg" in out and "level" in out


def test_documents_no_param_function_without_args_block():
    # No parameters -> the docstring omits the Args block entirely (no empty
    # section), still carrying the proven Returns line.
    out = document_signatures("def origin():\n    return 0\n")
    assert out is not None
    assert "Returns: int" in out
    assert "Args:" not in out


def test_uses_existing_return_annotation_as_proven_fact():
    # The function already declares ``-> list[int]`` (an author-declared fact)
    # but has no docstring; the annotation is read verbatim for the Returns line
    # even though the oracle refuses an already-annotated function.
    out = document_signatures(
        "def parse(text) -> list[int]:\n    return decode(text)\n")
    assert out is not None
    assert "Returns: list[int]" in out
    assert "text" in out


def test_documents_each_provable_return_kind():
    cases = {
        "return 's'": "Returns: str",
        "return True": "Returns: bool",
        "return 1.5": "Returns: float",
        "return [1]": "Returns: list[int]",
        "return {1: 2}": "Returns: dict[int, int]",
    }
    for body, expect in cases.items():
        out = document_signatures(f"def f(a):\n    {body}\n")
        assert out is not None and expect in out, body


def test_documents_method_with_correct_indentation():
    out = document_signatures(
        "class C:\n    def area(self, w, h):\n        return 1\n")
    assert out is not None
    # The docstring is indented to the method body (8 spaces), not column 0.
    assert '        """area.' in out
    assert "        Returns: int" in out


def test_documented_function_still_parses_and_runs():
    # Behaviour-preserving: docstring TEXT only — the function still runs and
    # returns the same value, and __doc__ is now set.
    out = document_signatures("def doubled(xs):\n    return len(xs)\n")
    assert out is not None
    ns: dict = {}
    exec(out, ns)  # noqa: S102 - executing our own generated, proven-safe code
    assert ns["doubled"]([1, 2, 3]) == 3
    assert ns["doubled"].__doc__.startswith("doubled.")


def test_generated_docstring_has_no_trailing_whitespace():
    # Landed code must stay lint-clean: blank separator lines are emitted empty.
    out = document_signatures("def f(a, b):\n    return len(a)\n")
    assert out is not None
    for line in out.splitlines():
        assert line == line.rstrip(), repr(line)


# --- the CRITICAL GATE: not provable -> land NOTHING (no placeholder) ---------

def test_refuses_when_return_type_not_provable():
    # ``a + b`` is a BinOp over names — not statically certain -> the oracle
    # refuses, so this objective lands NOTHING (no placeholder skeleton).
    assert document_signatures("def combine(a, b):\n    return a + b\n") is None


def test_refuses_bare_name_return():
    assert document_signatures("def echo(x):\n    return x\n") is None


def test_refuses_fall_through_value_return():
    # Reaches the end -> implicit ``return None`` -> true type is ``int | None``;
    # the oracle refuses rather than guess, so nothing is documented.
    src = "def code(ok):\n    if ok:\n        return 200\n"
    assert document_signatures(src) is None


def test_refuses_generator():
    # A generator returns an iterator, not a named concrete type -> refuse.
    assert document_signatures("def gen(xs):\n    yield 1\n") is None


def test_refuses_mixed_return_types():
    src = "def f(c):\n    if c:\n        return 1\n    return 'x'\n"
    assert document_signatures(src) is None


# --- refusals: who never gets a docstring ------------------------------------

def test_refuses_already_documented_function():
    src = 'def f(x):\n    """Existing."""\n    return 1\n'
    assert document_signatures(src) is None


def test_refuses_private_function():
    assert document_signatures("def _helper(x):\n    return 1\n") is None


def test_refuses_dunder_function():
    assert document_signatures(
        "def __init__(self, x):\n    self.x = x\n") is None


def test_refuses_test_function():
    assert document_signatures("def test_thing():\n    return 1\n") is None


def test_documents_only_qualifying_in_a_mixed_module():
    # public+provable -> documented; private and non-provable -> left alone.
    src = (
        "def good(xs):\n    return len(xs)\n\n"
        "def _hidden(a):\n    return 1\n\n"
        "def murky(a, b):\n    return a + b\n"
    )
    out = document_signatures(src)
    assert out is not None
    assert '"""good.' in out
    # The two non-qualifying functions gained no docstring.
    assert "_hidden." not in out.replace("def _hidden", "")
    assert '"""murky.' not in out


# --- idempotency / determinism -----------------------------------------------

def test_idempotent_second_run_is_a_noop():
    src = "def size(xs):\n    return len(xs)\n"
    once = document_signatures(src)
    assert once is not None
    # The function now HAS a docstring -> a second run refuses (byte-identical).
    assert document_signatures(once) is None


def test_deterministic_across_two_runs():
    src = "def f(a, b, c):\n    return len(a)\n"
    assert document_signatures(src) == document_signatures(src)


def test_unparseable_source_is_none():
    assert document_signatures("def (:\n") is None


# --- plan layer: refusal, no-op, determinism, rollback capture ---------------

def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def test_plan_lands_proven_docstring(tmp_path: Path):
    _project(tmp_path, "app/m.py", "def size(xs):\n    return len(xs)\n")
    plan = plan_document_signature(str(tmp_path), "app/m.py")
    landed = plan.new_contents["app/m.py"]
    assert "Returns: int" in landed and '"""size.' in landed
    assert not plan.blockers
    # The original is captured so the verified-apply engine can roll it back.
    assert plan.originals["app/m.py"] == "def size(xs):\n    return len(xs)\n"


def test_plan_refuses_when_not_provable_no_placeholder(tmp_path: Path):
    # The critical gate at the plan layer: a non-provable return yields an EMPTY
    # plan (no write, no blocker) — never a placeholder skeleton.
    _project(tmp_path, "app/m.py", "def combine(a, b):\n    return a + b\n")
    plan = plan_document_signature(str(tmp_path), "app/m.py")
    assert not plan.new_contents
    assert not plan.blockers


def test_plan_refuses_test_file(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", "def helper():\n    return 1\n")
    plan = plan_document_signature(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents
    assert not plan.blockers


def test_plan_refuses_fixture_file(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", "def helper():\n    return 1\n")
    plan = plan_document_signature(str(tmp_path), "fixtures/sample.py")
    assert not plan.new_contents


def test_plan_is_noop_when_already_documented(tmp_path: Path):
    _project(tmp_path, "app/m.py",
             'def f(x):\n    """Doc."""\n    return 1\n')
    plan = plan_document_signature(str(tmp_path), "app/m.py")
    assert not plan.new_contents


def test_plan_is_deterministic_across_two_runs(tmp_path: Path):
    src = "def a(xs):\n    return len(xs)\n\ndef b():\n    return 's'\n"
    _project(tmp_path, "app/m.py", src)
    one = plan_document_signature(str(tmp_path), "app/m.py").new_contents.get("app/m.py")
    two = plan_document_signature(str(tmp_path), "app/m.py").new_contents.get("app/m.py")
    assert one == two and one is not None
    assert "Returns: int" in one and "Returns: str" in one


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    # A module path that does not exist -> empty no-op plan, no crash.
    plan = plan_document_signature(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: the facet engine emits the phrase that routes here ----------

def test_engine_emits_phrase_reachable_to_document_signature(tmp_path: Path):
    # Close the loop: the document lens's zoom EMITS the new phrase, and the
    # emitted phrase routes to this objective — proving the wiring connects
    # end-to-end, not just in isolation.
    from app.engine.facet_develop import facet_to_objective
    from app.engine.idea_permutation import (
        DEVELOPMENT_OPERATORS,
        IdeaPermutationEngine,
    )

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def compute(a, b):\n    return [a, b]\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")

    cfg = {
        "max_total_ideas": 50000, "max_idea_depth": 1, "breadth": 8,
        "fractal_facets": True, "facet_depth": 3, "facets_per_idea": 12,
        "security_aware": False,
    }
    engine = IdeaPermutationEngine(cfg, tmp_path)
    engine.operators = [op for op in DEVELOPMENT_OPERATORS if op.name == "document"]
    rep = engine.run()

    emitted = {
        fact.split("facet:", 1)[1].strip()
        for idea in rep.ideas if idea.kind == "facet"
        for fact in idea.source_facts if fact.startswith("facet:")
    }
    assert "the public signature to document" in emitted
    reachable = {
        obj for phrase in emitted
        if (obj := facet_to_objective(phrase)) is not None
    }
    assert "document-signature" in reachable


# --- end-to-end: gated apply, real landing, auto-rollback --------------------

def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_end_to_end_lands_docstring_and_keeps_green(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    (tmp_path / "app" / "calc.py").write_text(
        "def total(items):\n    return len(items)\n\n"
        "def murky(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import total\n"
        "def test_it():\n    assert total([1, 2]) == 2\n", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="document-signature",
                               apply=True, verify=True)
    assert result.steps  # a verified move landed
    assert result.steps[0].verified is True

    text = (tmp_path / "app" / "calc.py").read_text()
    assert '"""total.' in text          # proven docstring landed
    assert "Returns: int" in text
    assert '"""murky.' not in text       # non-provable function untouched

    # Behaviour preserved: the suite still imports and runs.
    import ast as _ast
    _ast.parse(text)


def test_end_to_end_auto_rollback_on_docstring_rejecting_suite(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    original = "def code():\n    return 7\n"
    (tmp_path / "app" / "mod.py").write_text(original, encoding="utf-8")
    # A suite that REJECTS the docstring: when it lands, __doc__ becomes non-None
    # and this test fails, so the verified apply must roll the file back.
    (tmp_path / "tests" / "test_mod.py").write_text(
        "from app.mod import code\n"
        "def test_undocumented():\n    assert code() == 7\n"
        "    assert code.__doc__ is None\n", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="document-signature",
                               apply=True, verify=True)
    assert not result.steps          # nothing landed
    assert result.blocked            # the move was blocked (rolled back)
    # The file is byte-for-byte restored — never-fake-green.
    assert (tmp_path / "app" / "mod.py").read_text() == original


def test_single_line_body_def_does_not_suppress_the_rest_of_the_module():
    # REGRESSION: a same-line-body def (`def f(): return 1`) makes the shared
    # `_body_insertion` report the HEADER text as the docstring "indent", which
    # corrupts the insertion. That corrupt placement used to fail the module's
    # batch self-validation and return None — silently dropping the docstrings of
    # EVERY OTHER function in the module. The single-line def must now be SKIPPED
    # (its indent is not pure whitespace), leaving its siblings documentable.
    src = ("def flag(): return True\n\n\n"
           "def compute(a, b):\n    return [a, b]\n")
    out = document_signatures(src)
    assert out is not None                       # the batch is NOT dropped
    assert "def compute(a, b):" in out and "Returns: list" in out  # sibling documented
    # The one-liner is left exactly as-is (skipped, never corrupted) and the
    # result carries exactly one docstring (compute's), so flag was not touched.
    assert "def flag(): return True" in out
    assert out.count('"""') == 2
    # A lone single-line def documents nothing (no-op), never corruption.
    assert document_signatures("def f(): return 1\n") is None
