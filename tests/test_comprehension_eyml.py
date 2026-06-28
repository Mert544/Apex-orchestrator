"""Acceptance battery for the deterministic COMPREHENSION core.

``app.intent.comprehension.comprehend`` is the zero-token "small-LLM" that maps a
natural-language request to an action (develop / question), a RANKED objective
list, a safety mode, and a best-effort scope — LLM-free, offline, deterministic.
This module is its regression contract:

* the ACCEPTANCE BATTERY (EN + TR) at a ≥90% pass bar — the field-test lift from
  ~14% NL→objective to ~90%+;
* DETERMINISM — same request, same Comprehension, every time;
* the SHARED-vocabulary deepening of ``resolve_objective`` AND its strict
  BACK-COMPAT (an exact name still wins; a previously-correct phrase is unchanged;
  an unknown request still returns ``None``);
* a CLI smoke for ``apex comprehend`` / ``python -m app.cli comprehend``.

Construction style mirrors ``test_objective_compiler_intents.py``.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.engine.objective_compiler import available_objectives, resolve_objective
from app.intent.comprehension import (
    CONCEPT_VOCAB,
    Comprehension,
    comprehend,
    concept_matches,
    is_removal_framed,
    name_phrase_match,
)

_REPO = Path(__file__).resolve().parents[1]


# --- The acceptance battery --------------------------------------------------
#
# A row passes if: the action is correct AND (for a develop row) at least one of
# the expected objectives is present AND the mode matches where specified. The
# objective lists are "any-of": the request must surface AT LEAST one. Mirrors the
# build spec's battery, expanded to EN + TR.
#
# (request, action, expected_any_objectives_or_None, expected_mode_or_None)
_BATTERY: tuple[tuple[str, str, tuple[str, ...] | None, str | None], ...] = (
    ("add type hints", "develop", ("infer-type-hints",), None),
    ("document the auth module", "develop",
     ("document-param", "document-returns", "document-signature",
      "generate-usage-doc"), None),
    ("fix security issues", "develop", ("harden",), None),
    ("add tests for the parser", "develop",
     ("cover-gaps", "strengthen-tests"), None),
    ("sort my imports", "develop", ("sort-imports",), None),
    ("modernize this codebase", "develop", ("modernize",), None),
    ("implement the TODO stubs", "develop", ("implement-stub",), None),
    ("just show me, don't change anything", "develop", None, "report"),
    ("clean it up automatically", "develop", None, "autonomous"),
    ("what should I improve next?", "question", (), None),
    ("why is this module so coupled?", "question", (), None),
    ("what's wrong with this code?", "question", (), None),
    ("how do I make this faster?", "question", (), None),
    # --- Turkish ---
    ("kodu temizle", "develop", ("modernize", "remove-dead-code", "sort-imports"),
     None),
    ("güvenlik açıklarını düzelt", "develop", ("harden",), None),
    ("tip belirteçleri ekle", "develop", ("infer-type-hints",), None),
    ("dökümantasyon ekle", "develop",
     ("document-param", "document-returns", "document-signature"), None),
    ("testleri güçlendir kapsamı artır", "develop",
     ("cover-gaps", "strengthen-tests"), None),
    # --- explicit objective slugs and common phrasings ---
    ("remove dead code", "develop", ("remove-dead-code",), None),
    ("clean up imports", "develop",
     ("sort-imports", "remove-unused-imports", "merge-duplicate-imports"), None),
    ("dataclassify the config", "develop", ("dataclassify",), None),
    ("wire up the exports", "develop", ("wire-exports", "wire-module-exports"),
     None),
    ("add jsdoc to the typescript", "develop",
     ("js-document-param-types", "document-export-jsdoc"), None),
)


def _row_passes(request: str, action: str,
                objs: tuple[str, ...] | None, mode: str | None) -> bool:
    c = comprehend(request)
    if c.action != action:
        return False
    if action == "develop" and objs is not None:
        if not any(o in c.objectives for o in objs):
            return False
    if mode is not None and c.mode != mode:
        return False
    return True


@pytest.mark.parametrize("req,action,objs,mode", _BATTERY)
def test_battery_row(req, action, objs, mode):
    assert _row_passes(req, action, objs, mode), (
        f"battery row failed: {req!r} -> {comprehend(req)}")


def test_battery_hit_rate_at_least_90_percent():
    """The whole battery clears the ≥90% bar (the field-test lift target)."""
    passed = sum(1 for r in _BATTERY if _row_passes(*r))
    rate = passed / len(_BATTERY)
    assert rate >= 0.90, f"hit-rate {rate:.0%} ({passed}/{len(_BATTERY)}) < 90%"


# --- The COMPOUND case: type hints AND docstrings together -------------------

def test_compound_request_yields_both_families():
    c = comprehend("add type hints and docstrings to the auth module")
    assert c.action == "develop"
    assert "infer-type-hints" in c.objectives
    assert any(o.startswith("document-") for o in c.objectives)
    # the scope hint is extracted from "the auth module"
    assert c.scope == "auth"
    # type hints lead (named first), docs follow — a stable compound ranking
    assert c.objectives.index("infer-type-hints") < c.objectives.index("document-param")


# --- ACTION / MODE / SCOPE detail --------------------------------------------

@pytest.mark.parametrize("req", [
    "what is this", "why so slow?", "how should I structure this",
    "which module is heaviest?", "are these tests enough?",
    "ne yapmalıyım?", "bu modül neden bu kadar bağımlı",
])
def test_questions_carry_no_objectives(req):
    c = comprehend(req)
    assert c.action == "question"
    assert c.objectives == []


@pytest.mark.parametrize("req,mode", [
    ("modernize but just show me the diff", "report"),
    ("clean up, dry-run only", "report"),
    ("tidy the code, don't change anything", "report"),
    ("sadece göster, değiştirme", "report"),
    ("harden everything automatically", "autonomous"),
    ("fix it, no confirm", "autonomous"),
    ("modernize otonom", "autonomous"),
    ("add type hints", "supervised"),
])
def test_mode_detection(req, mode):
    assert comprehend(req).mode == mode


@pytest.mark.parametrize("req,scope", [
    ("document the auth module", "auth"),
    ("add tests for the parser module", "parser"),
    ("fix app/engine/foo.py", "app/engine/foo.py"),
    ("type hints in bar.py", "bar.py"),
    ("implement the parse function", "parse"),
    ("modernize the Widget class", "widget"),
    ("clean up the whole project", None),
])
def test_scope_extraction(req, scope):
    assert comprehend(req).scope == scope


def test_empty_request_is_unknown():
    for blank in ("", "   ", "\t\n"):
        c = comprehend(blank)
        assert c.action == "unknown"
        assert c.objectives == []
        assert c.confidence == "low"


def test_unmatched_develop_is_low_confidence():
    c = comprehend("please make me a sandwich")
    assert c.action == "develop"
    assert c.objectives == []
    assert c.confidence == "low"


def test_matched_develop_is_high_confidence():
    assert comprehend("add type hints").confidence == "high"


# --- The allow-list filter ---------------------------------------------------

def test_objectives_allow_list_filters_and_preserves_rank():
    full = comprehend("add type hints and docstrings")
    allow = ["document-param", "infer-type-hints"]
    filtered = comprehend("add type hints and docstrings", objectives=allow)
    assert set(filtered.objectives) <= set(allow)
    # rank order from the full result is preserved among the kept objectives
    kept_full = [o for o in full.objectives if o in set(allow)]
    assert filtered.objectives == kept_full


def test_objectives_empty_allow_list_yields_nothing():
    c = comprehend("add type hints", objectives=[])
    assert c.objectives == []
    assert c.confidence == "low"


# --- DETERMINISM -------------------------------------------------------------

def test_comprehend_is_deterministic():
    samples = [r[0] for r in _BATTERY] + [
        "add type hints and docstrings to the auth module",
        "please make me a sandwich", "", "what now?",
    ]
    for request in samples:
        a = comprehend(request)
        b = comprehend(request)
        assert a == b, f"non-deterministic for {request!r}: {a} != {b}"


def test_ranking_is_stable_across_repeats():
    # The compound ranking must be byte-stable (no set/dict iteration leak).
    req = "modernize, add type hints, document, and clean up imports"
    first = comprehend(req).objectives
    for _ in range(5):
        assert comprehend(req).objectives == first


# --- VOCABULARY integrity ----------------------------------------------------

def test_every_concept_target_is_a_real_objective():
    known = set(available_objectives())
    assert CONCEPT_VOCAB
    for phrase, objs in CONCEPT_VOCAB:
        assert phrase == phrase.lower(), f"concept phrase not normalized: {phrase!r}"
        assert objs, f"empty objective list for concept {phrase!r}"
        for obj in objs:
            assert obj in known, f"concept {phrase!r} names unknown objective {obj!r}"


def test_name_phrase_match_finds_multiword_names():
    known = list(available_objectives())
    assert "sort-imports" in name_phrase_match("please sort imports now", known)
    assert "infer-type-hints" in name_phrase_match("infer type hints", known)
    # a full single-token name matches as itself
    assert "modernize" in name_phrase_match("please modernize this", known)
    # a bare AMBIGUOUS hyphen-token (heads 10 objectives) must NOT match on its
    # own — "document" is not itself an objective name, only "document-*" are
    assert name_phrase_match("document", known) == []
    # but the full multiword name does match
    assert "document-param" in name_phrase_match("document param here", known)


def test_concept_matches_dedups_preserving_order():
    out = concept_matches("type hints and more type hints")
    assert out == list(dict.fromkeys(out))  # no duplicates
    assert out[0] == "infer-type-hints"


# --- ARCHITECTURE: the shared leaf breaks the import cycle -------------------

def test_vocabulary_leaf_imports_no_app_modules():
    # The leaf must depend on stdlib ONLY (re/dataclasses) — that is what keeps
    # objective_compiler ↔ comprehension cycle-free. Assert it via its source AST.
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app" / "intent" / "vocabulary.py")
    tree = ast.parse(src.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
    assert not any(m.startswith("app.") for m in modules), (
        f"vocabulary leaf must not import any app module, found: {sorted(modules)}")


def test_comprehension_reexports_are_the_leaf_definitions():
    # The re-exports keep ``app.intent.comprehension.concept_matches`` etc. working
    # for existing callers, but the REAL definitions live in the leaf — same object.
    import app.intent.comprehension as comp
    import app.intent.vocabulary as vocab

    assert comp.concept_matches is vocab.concept_matches
    assert comp.name_phrase_match is vocab.name_phrase_match
    assert comp.CONCEPT_VOCAB is vocab.CONCEPT_VOCAB
    assert comp.is_removal_framed is vocab.is_removal_framed
    assert comp.suppress_removal is vocab.suppress_removal


def test_objective_compiler_does_not_import_comprehension():
    # resolve_objective's fallback imports the matchers from the LEAF, never from
    # comprehension — so objective_compiler has no edge back to comprehend (no
    # cycle). Assert no top-level OR lazy import of comprehension in its source.
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app" / "engine"
           / "objective_compiler.py")
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module != "app.intent.comprehension", (
                "objective_compiler must not import comprehension (would re-introduce "
                "the cycle); import the shared leaf app.intent.vocabulary instead")


# --- FIX 1: removal / negation honesty guard (LEAD-ANCHORED) -----------------
#
# Apex has no "un-add" capability, so a removal/negation-framed request that would
# otherwise match an ADD lens must NOT invert intent. comprehend → objectives=[],
# confidence="low"; resolve_objective → None (the compiler stays honestly blocked).

_MUST_SUPPRESS: tuple[str, ...] = (
    "remove docstrings", "remove type hints", "delete all the tests",
    "remove the security checks", "don't add type hints", "do not document this",
    "get rid of the type hints", "strip the docstrings",
    # a few more lead-anchored inversions
    "delete the type annotations", "never add docstrings", "skip the tests",
    "disable the security checks", "no type hints please",
)


@pytest.mark.parametrize("req", _MUST_SUPPRESS)
def test_removal_framed_comprehend_is_suppressed(req):
    c = comprehend(req)
    assert c.objectives == [], f"{req!r} should suppress all (additive) matches"
    assert c.confidence == "low"
    assert "removal" in c.rationale.lower() or "negation" in c.rationale.lower()


@pytest.mark.parametrize("req", _MUST_SUPPRESS)
def test_removal_framed_resolve_is_none(req):
    # The honest pre-vocabulary verdict: unknown objective → compiler stays blocked.
    assert resolve_objective(req) is None


# (request, an objective that MUST still be in the result) — the cue is buried
# (not leading) or an add-verb leads, so the guard must NOT over-suppress.
_MUST_NOT_OVER_SUPPRESS: tuple[tuple[str, str], ...] = (
    ("add type hints to remove ambiguity", "infer-type-hints"),
    ("document how to remove a user", "document-param"),
    ("add tests for the delete endpoint", "cover-gaps"),
    ("cover the remove_user function with tests", "cover-gaps"),
    ("harden the delete path", "harden"),
    ("implement the function that deletes a row", "implement-stub"),
)


@pytest.mark.parametrize("req,expected", _MUST_NOT_OVER_SUPPRESS)
def test_not_over_suppressed_comprehend(req, expected):
    c = comprehend(req)
    assert expected in c.objectives, f"{req!r} should still surface {expected}"
    assert c.confidence == "high"


@pytest.mark.parametrize("req,expected", _MUST_NOT_OVER_SUPPRESS)
def test_not_over_suppressed_resolve(req, expected):
    assert resolve_objective(req) is not None


# Legitimate removals resolve via the synonym/exact branch BEFORE the fallback,
# so the guard never touches them — they must still work.
@pytest.mark.parametrize("req,expected", [
    ("remove dead code", "remove-dead-code"),
    ("remove unused imports", "remove-unused-imports"),
    ("drop param", "dead-params"),
    ("strip unreachable branches", "remove-dead-code"),
    ("strip dead", "remove-dead-code"),
    ("prune import", "remove-unused-imports"),
])
def test_legitimate_removals_still_resolve(req, expected):
    assert resolve_objective(req) == expected
    assert expected in comprehend(req).objectives


def test_is_removal_framed_lead_anchored():
    # leading cue → framed
    assert is_removal_framed(["remove", "docstrings"])
    assert is_removal_framed(["get", "rid", "of", "the", "hints"])
    assert is_removal_framed(["don", "t", "add", "tests"])
    assert is_removal_framed(["do", "not", "document"])
    # buried cue → NOT framed
    assert not is_removal_framed(["add", "tests", "for", "the", "delete", "endpoint"])
    assert not is_removal_framed(["document", "how", "to", "remove", "a", "user"])
    assert not is_removal_framed([])


# --- FIX 2: word-boundary on short/ambiguous concept keys --------------------
#
# Substring matching mis-fired ("important"→import, "final exam"→add-final,
# "documentary"→document-*, "java is my favorite island"→java-*). These must die;
# the real code-intent phrasings must keep working.

@pytest.mark.parametrize("req", [
    "important", "this is important", "the most important thing",
    "final exam", "final thoughts", "the final answer",
    "java is my favorite island", "i visited java last summer",
    "slot machine", "a free time slot",
    "documentary about code", "documentary",
    "typing speed", "improve my typing speed",
    "enumerate the items", "enumerate over the list",
    "seal the envelope",
])
def test_word_boundary_kills_false_positives(req):
    c = comprehend(req)
    assert c.objectives == [], f"{req!r} must not match any objective, got {c.objectives}"
    assert resolve_objective(req) is None


@pytest.mark.parametrize("req,expected", [
    ("sort imports", "sort-imports"),
    ("imports", "sort-imports"),
    ("clean up the imports", "sort-imports"),
    ("make it final", "add-final"),
    ("make this method final", "add-final"),
    ("enum", "enforce-enum-unique"),
    ("enforce enum uniqueness", "enforce-enum-unique"),
    ("java throws", "java-document-throws"),
    ("document the java throws", "java-document-throws"),
    ("add slots", "add-slots"),
    ("add __slots__ to the dataclass", "add-slots"),
    ("type hints", "infer-type-hints"),
    ("add type annotations", "infer-type-hints"),
    ("seal the class as final", "add-final"),
])
def test_word_boundary_keeps_real_intent(req, expected):
    assert expected in comprehend(req).objectives, (
        f"{req!r} should still surface {expected}")


# --- resolve_objective: the SHARED vocabulary lifts it, BACK-COMPAT preserved -

@pytest.mark.parametrize("req,expected", [
    # NEW wins enabled by the shared vocabulary (these were ~misses before):
    ("sort my imports", "sort-imports"),
    ("modernize this codebase", "modernize"),
    ("infer type hints", "infer-type-hints"),
    ("add tests", "cover-gaps"),
    ("implement the stub", "implement-stub"),
    ("document signature", "document-signature"),
    ("dataclassify it", "dataclassify"),
    ("wire exports", "wire-exports"),
])
def test_resolve_objective_new_wins(req, expected):
    got = resolve_objective(req)
    assert got == expected
    assert got in available_objectives()


@pytest.mark.parametrize("req,expected", [
    # The pre-existing synonym rows MUST resolve exactly as before (back-compat):
    ("tidy up this module", "modernize"),
    ("clean up the code", "modernize"),
    ("refactor it", "modernize"),
    ("please optimize this", "modernize"),
    ("can we speed up the parser", "modernize"),
    ("harden the auth path", "harden"),
    ("lock down the endpoint", "harden"),
    ("fortify the request path", "harden"),
    ("secure the upload handler", "harden"),
    ("sanitize the inputs", "modernize"),
    ("sort import block", "sort-imports"),
    ("organize imports", "sort-imports"),
    ("clean up imports", "sort-imports"),
    ("drop the unused imports", "remove-unused-imports"),
    ("remove dead code", "remove-dead-code"),
    ("strip unreachable branches", "remove-dead-code"),
    ("drop unused parameters", "dead-params"),
    ("shrink the long functions", "shrink-functions"),
    ("split function into helpers", "shrink-functions"),
    ("decouple these helpers", "shrink-functions"),
    ("untangle this", "shrink-functions"),
    ("inline that helper", "inline-helpers"),
    ("remove the duplicated blocks", "dedup"),
    ("copy-paste cleanup", "dedup"),
    ("name the magic numbers", "extract-constant"),
    ("simplify boolean return", "simplify-bool-return"),
    ("turn that loop into a comprehension", "simplify-comprehension"),
])
def test_resolve_objective_backcompat_synonyms_unchanged(req, expected):
    assert resolve_objective(req) == expected


def test_resolve_objective_exact_name_always_wins():
    for name in available_objectives():
        assert resolve_objective(name) == name


def test_resolve_objective_unknown_still_none():
    for blank in ("make me a sandwich", "", "   "):
        assert resolve_objective(blank) is None
    assert resolve_objective(None) is None


def test_resolve_objective_is_deterministic():
    for phrase in ("sort my imports", "modernize this", "untangle this",
                   "make me a sandwich", "dead-params", "add tests"):
        assert resolve_objective(phrase) == resolve_objective(phrase)


# --- CLI smoke: apex comprehend / python -m app.cli comprehend ---------------

def _cli_env() -> dict:
    """Env that puts THIS worktree's ``app`` package first on the import path, so
    the subprocess resolves the code under test regardless of any editable install
    pointing elsewhere."""
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "app.cli", *args],
        capture_output=True, text=True, cwd=str(cwd or _REPO), env=_cli_env())


def test_cli_comprehend_smoke():
    res = _run_cli("comprehend", "add type hints to the auth module")
    assert res.returncode == 0
    assert "develop" in res.stdout
    assert "infer-type-hints" in res.stdout
    assert "auth" in res.stdout


def test_cli_comprehend_json():
    import json

    res = _run_cli("comprehend", "fix security issues", "--json")
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["action"] == "develop"
    assert "harden" in data["objectives"]


def test_cli_comprehend_question():
    res = _run_cli("comprehend", "what should I improve next?")
    assert res.returncode == 0
    assert "question" in res.stdout


def test_cli_comprehend_writes_nothing(tmp_path):
    # The command is read-only: running it in an empty dir creates no files.
    res = _run_cli("comprehend", "modernize the code", cwd=tmp_path)
    assert res.returncode == 0
    assert list(tmp_path.iterdir()) == []


def test_comprehension_to_dict_roundtrips():
    c = comprehend("add type hints")
    d = c.to_dict()
    assert d["action"] == "develop"
    assert d["objectives"] == c.objectives
    assert set(d) == {"request", "action", "objectives", "mode", "scope",
                      "rationale", "confidence"}
    # to_dict is a plain copy — mutating it never touches the dataclass
    d["objectives"].append("x")
    assert "x" not in c.objectives


def test_comprehension_dataclass_defaults():
    c = Comprehension(request="x")
    assert c.action == "develop"
    assert c.objectives == []
    assert c.mode == "supervised"
    assert c.scope is None
    assert c.confidence == "high"
