"""document-signature develop objective — land a PROVEN docstring on an
undocumented public function, BUT REFUSE a content-free restatement.

Covers: objective registration / reachability (a facet phrase routes to it and
the facet-map↔registry parity invariant still holds); the per-fact building
blocks the generator can still mint (param names as AST facts, a ``Returns:
<type>`` line from the existing return-type oracle or an existing ``-> T``
annotation); the CRITICAL GATE — when the return type is NOT provable it lands
NOTHING (never a placeholder skeleton); the CONTENT-FREE refusal — under the
current name+params+return template every generatable docstring merely restates
the signature, so ``document_signatures`` is a deliberate honest NO-OP (it lands
nothing rather than noise a maintainer rejects); every other refusal
(already-documented, private/dunder, ``test_*``, test/fixture file); idempotency
(a second run is a byte-identical no-op); and determinism (same input -> same
output).

NOTE (justification for this file's shape vs. the pre-fix version): the prior
tests asserted ``document_signatures(...)`` LANDED a docstring such as
``\"\"\"size. Args: xs Returns: int\"\"\"``. The pilot (DELIVERABLE B.2,
spec_pilot_revalidation_and_targeting.md) confirmed across funcy/humanize/
inflection that EVERY such docstring is a pure RESTATEMENT of the signature —
content-free noise a maintainer rejects. The fix adds ``_adds_semantic_content``
(always ``False`` under the current template) so the objective now REFUSES every
content-free docstring. These tests were updated to assert that honest no-op
while still proving the underlying per-fact machinery is intact (so the moment a
real prose source is wired the objective re-enables for content-FUL cases).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.objectives.document_signature import (
    _adds_semantic_content,
    _docstring_lines,
    _is_public_undocumented,
    _param_names,
    _provable_return_type,
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
    # unreachable and the facet/objective integrity test fails. (Refusing to land
    # content-free docstrings does NOT remove the objective — it stays registered
    # and reachable, ready to land the moment a real prose source exists.)
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(
        "the public signature to document") == "document-signature"


def test_facet_reachability_parity_invariant_holds():
    # The standing 1:1 invariant: the facet map reaches EXACTLY the registered
    # objectives. The content-free refusal adds/removes no objective, so the
    # equality is unchanged.
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


# --- the per-fact building blocks are still intact (proven facts) -------------
# These prove the machinery the objective REUSES once a prose source lands; they
# do not assert the objective lands anything (it refuses — see the next section).

def test_provable_return_type_oracle_still_proves_int():
    fn = ast.parse("def size(xs):\n    return len(xs)\n").body[0]
    assert _provable_return_type(fn) == "int"


def test_provable_return_type_proves_pure_procedure_none():
    fn = ast.parse("def emit(msg, level):\n    print(msg)\n").body[0]
    assert _provable_return_type(fn) == "None"


def test_provable_return_type_reads_existing_annotation_verbatim():
    fn = ast.parse("def parse(text) -> list[int]:\n    return decode(text)\n").body[0]
    assert _provable_return_type(fn) == "list[int]"


def test_provable_return_type_refuses_when_not_provable():
    fn = ast.parse("def combine(a, b):\n    return a + b\n").body[0]
    assert _provable_return_type(fn) is None


def test_param_names_are_pure_ast_facts():
    fn = ast.parse("def f(a, b, *args, c, **kw):\n    return 1\n").body[0]
    assert _param_names(fn) == ["a", "b", "*args", "c", "**kw"]


def test_docstring_lines_template_is_name_params_return_only():
    # The generated body carries EXACTLY name + param names + return type — no
    # prose source — which is precisely why it is content-free (the next section).
    fn = ast.parse("def size(xs):\n    return len(xs)\n").body[0]
    body = "".join(_docstring_lines(fn, "", "int"))
    assert "size." in body and "Args:" in body and "xs" in body
    assert "Returns: int" in body


# --- the CONTENT-FREE refusal: a pure signature restatement -> land NOTHING ---

def test_adds_semantic_content_is_false_under_current_template():
    # The minimal, exact predicate (spec B.2(a)): the current name+params+return
    # template is ALWAYS a pure restatement, so this is False for every function
    # -> the objective is a deliberate honest no-op until a prose source lands.
    fn = ast.parse("def size(xs):\n    return len(xs)\n").body[0]
    assert _adds_semantic_content(fn, "int") is False


def test_refuses_content_free_pilot_invalidate_case():
    # The exact pilot case: the only generatable docstring is
    # `\"\"\"invalidate. Args: *args **kwargs Returns: None\"\"\"` — a pure
    # restatement of the signature -> REFUSED (content-free), no-op.
    assert document_signatures(
        "def invalidate(*args, **kwargs):\n    memory.pop()\n") is None


def test_refuses_content_free_even_with_provable_int_return():
    # Was the standout "accept" before the fix: provable return + a param name is
    # STILL only a restatement of the signature -> refuse.
    assert document_signatures("def size(xs):\n    return len(xs)\n") is None


def test_refuses_content_free_pure_procedure_returns_none():
    assert document_signatures("def emit(msg, level):\n    print(msg)\n") is None


def test_refuses_content_free_no_param_function():
    assert document_signatures("def origin():\n    return 0\n") is None


def test_refuses_content_free_get_translation_case():
    # humanize i18n: `\"\"\"get_translation. Returns: gettext...NullTranslations\"\"\"`
    # — content-free even with a return type -> refuse.
    assert document_signatures(
        "def get_translation() -> X:\n    return X()\n") is None


def test_refuses_content_free_with_existing_annotation():
    assert document_signatures(
        "def parse(text) -> list[int]:\n    return decode(text)\n") is None


def test_refuses_every_provable_return_kind_as_content_free():
    # Each was an "accept" before; each is now a content-free restatement.
    for body in ("return 's'", "return True", "return 1.5",
                 "return [1]", "return {1: 2}"):
        assert document_signatures(f"def f(a):\n    {body}\n") is None, body


def test_refuses_content_free_method():
    assert document_signatures(
        "class C:\n    def area(self, w, h):\n        return 1\n") is None


# --- the CRITICAL GATE: not provable -> land NOTHING (no placeholder) ---------
# (Independently still holds — the return-type gate fires before the content gate.)

def test_refuses_when_return_type_not_provable():
    assert document_signatures("def combine(a, b):\n    return a + b\n") is None


def test_refuses_bare_name_return():
    assert document_signatures("def echo(x):\n    return x\n") is None


def test_refuses_fall_through_value_return():
    src = "def code(ok):\n    if ok:\n        return 200\n"
    assert document_signatures(src) is None


def test_refuses_generator():
    assert document_signatures("def gen(xs):\n    yield 1\n") is None


def test_refuses_mixed_return_types():
    src = "def f(c):\n    if c:\n        return 1\n    return 'x'\n"
    assert document_signatures(src) is None


# --- refusals: who never gets a docstring (gates BELOW the content-free one) --

def test_refuses_already_documented_function():
    src = 'def f(x):\n    """Existing."""\n    return 1\n'
    assert document_signatures(src) is None


def test_is_public_undocumented_skips_already_documented():
    # The gate that makes the pass idempotent is unchanged.
    fn = ast.parse('def f(x):\n    """Doc."""\n    return 1\n').body[0]
    assert _is_public_undocumented(fn) is False


def test_refuses_private_function():
    assert document_signatures("def _helper(x):\n    return 1\n") is None


def test_refuses_dunder_function():
    assert document_signatures(
        "def __init__(self, x):\n    self.x = x\n") is None


def test_refuses_test_function():
    assert document_signatures("def test_thing():\n    return 1\n") is None


def test_mixed_module_is_a_full_noop():
    # public+provable, private, and non-provable: NONE qualifies now (the
    # public+provable one is content-free), so the whole module is a no-op.
    src = (
        "def good(xs):\n    return len(xs)\n\n"
        "def _hidden(a):\n    return 1\n\n"
        "def murky(a, b):\n    return a + b\n"
    )
    assert document_signatures(src) is None


# --- idempotency / determinism (now: a stable no-op) --------------------------

def test_noop_is_idempotent():
    src = "def size(xs):\n    return len(xs)\n"
    assert document_signatures(src) is None
    # A second run on the (unchanged) source is the same byte-identical no-op.
    assert document_signatures(src) is None


def test_deterministic_across_two_runs():
    src = "def f(a, b, c):\n    return len(a)\n"
    assert document_signatures(src) == document_signatures(src)


def test_unparseable_source_is_none():
    assert document_signatures("def (:\n") is None


# --- plan layer: refusal, no-op, determinism, no crash -----------------------

def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def test_plan_is_noop_on_content_free_module(tmp_path: Path):
    # What used to land a docstring is now an EMPTY plan (content-free refusal):
    # no write, no blocker — an honest no-op, not a failure.
    _project(tmp_path, "app/m.py", "def size(xs):\n    return len(xs)\n")
    plan = plan_document_signature(str(tmp_path), "app/m.py")
    assert not plan.new_contents
    assert not plan.blockers


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
    one = plan_document_signature(str(tmp_path), "app/m.py").new_contents
    two = plan_document_signature(str(tmp_path), "app/m.py").new_contents
    assert one == two == {}  # a stable, byte-identical no-op


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    # A module path that does not exist -> empty no-op plan, no crash.
    plan = plan_document_signature(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: the facet engine emits the phrase that routes here ----------

def test_engine_emits_phrase_reachable_to_document_signature(tmp_path: Path):
    # Close the loop: the document lens's zoom EMITS the new phrase, and the
    # emitted phrase routes to this objective — proving the wiring connects
    # end-to-end, not just in isolation. (Unaffected by the content-free refusal:
    # the objective is still registered and reachable.)
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


# --- end-to-end: the objective is an HONEST NO-OP (content-free everywhere) --

def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_end_to_end_lands_nothing_content_free_is_honest_noop(tmp_path: Path):
    # Was "lands docstring and keeps green"; under the content-free refusal the
    # objective lands NOTHING (the docstring it could mint is a restatement) and
    # leaves the source byte-for-byte untouched — the honest no-op the North Star
    # prefers over maintainer-rejectable noise.
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    original = (
        "def total(items):\n    return len(items)\n\n"
        "def murky(a, b):\n    return a + b\n"
    )
    (tmp_path / "app" / "calc.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import total\n"
        "def test_it():\n    assert total([1, 2]) == 2\n", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="document-signature",
                               apply=True, verify=True)
    assert not result.steps        # nothing landed (honest no-op)
    assert not result.blocked      # nothing attempted -> nothing to block

    text = (tmp_path / "app" / "calc.py").read_text()
    assert text == original        # byte-for-byte untouched, no docstring
    assert '"""total.' not in text and '"""murky.' not in text
    ast.parse(text)


# --- single-line-body def: still a no-op (was a regression guard) ------------

def test_single_line_body_def_is_a_noop():
    # REGRESSION (still holds, now for the additional content-free reason): a
    # same-line-body def must never corrupt its siblings. Under the content-free
    # refusal NOTHING is documented anyway, so the result is a clean no-op — the
    # one-liner and its siblings are left exactly as-is, never corrupted.
    src = ("def flag(): return True\n\n\n"
           "def compute(a, b):\n    return [a, b]\n")
    assert document_signatures(src) is None
    # A lone single-line def documents nothing either (no-op), never corruption.
    assert document_signatures("def f(): return 1\n") is None
