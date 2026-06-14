"""Tests for the fractal facet VOCABULARY (``app/engine/idea_facets``).

These assert that the engine's zoom machinery genuinely EMITS the new
"redundant control flow" sub-aspect phrases — and that each emitted phrase
routes, end-to-end, to the develop objective it names. The vocabulary is pure
data: a phrase is only reachable if it sits in ``_FACETS`` / ``_FACET_SUBASPECTS``
where ``_facet_vocab`` can descend to it. So "is this phrase in the data" and "does
the engine emit it" are the same claim, checked both ways below.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.facet_develop import facet_to_objective
from app.engine.idea_facets import (
    _FACET_CAVEAT_RULES,
    _FACET_SUBASPECTS,
    _FACETS,
)
from app.engine.idea_permutation import DEVELOPMENT_OPERATORS, IdeaPermutationEngine

# The new redundant-control-flow ladder: (emitted L3 phrase, intended objective).
# Each phrase is a sub-aspect the simplify lens now zooms into; each objective is
# the verified develop campaign that performs exactly that tidy.
_NEW_LADDER: list[tuple[str, str]] = [
    ("boolean return simplification", "simplify-bool-return"),
    ("ternary that returns a boolean", "simplify-ternary-bool"),
    ("redundant else after return", "remove-redundant-else"),
    ("collapsible nested conditionals", "merge-nested-if"),
    ("get-with-default lookup", "simplify-dict-get"),
    ("manual index loop", "use-enumerate"),
    ("redundant pass statement", "remove-pointless-pass"),
    ("statements after an unconditional return",
     "remove-unreachable-after-terminator"),
]


def _simplify_project(tmp: Path) -> Path:
    """A project with long, complex, simplify-relevant code so the zoom has a
    rich subject to descend into."""
    (tmp / "app").mkdir()
    (tmp / "app" / "core.py").write_text(
        "def check(flag):\n"
        "    if flag:\n"
        "        return True\n"
        "    else:\n"
        "        return False\n"
        "\n\n"
        "def long_complex_refactor_candidate(a, b, c, d, e, f, g):\n"
        "    total = 0\n"
        "    if a > 0:\n"
        "        if b > 0:\n"
        "            if c > 0:\n"
        "                total += 1\n"
        "            else:\n"
        "                total -= 1\n"
        "        elif d > 0:\n"
        "            total += 2\n"
        "    if e > 0:\n"
        "        for x in range(e):\n"
        "            if x % 2 == 0:\n"
        "                total += x\n"
        "            else:\n"
        "                total -= x\n"
        "    if g > 0:\n"
        "        total *= g\n"
        "    else:\n"
        "        total = 0\n"
        "    if total > 100:\n"
        "        return \"big\"\n"
        "    elif total > 10:\n"
        "        return \"medium\"\n"
        "    return \"small\"\n",
        encoding="utf-8",
    )
    (tmp / "tests").mkdir()
    (tmp / "tests" / "test_core.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    return tmp


def _emitted_facet_labels(engine: IdeaPermutationEngine) -> set[str]:
    """Run the engine and collect every facet phrase its zoom machinery emitted."""
    rep = engine.run()
    labels: set[str] = set()
    for idea in rep.ideas:
        if idea.kind != "facet":
            continue
        for fact in idea.source_facts:
            if fact.startswith("facet:"):
                labels.add(fact.split("facet:", 1)[1].strip())
    return labels


def _simplify_engine(tmp: Path) -> IdeaPermutationEngine:
    """A facet-zooming engine confined to the simplify lens, so the deep zoom
    lands on the new ladder rather than being out-ranked by higher-feasibility
    lenses (test/harden). Restricting ``operators`` is a harness convenience —
    the vocabulary and zoom logic are exercised unchanged."""
    _simplify_project(tmp)
    cfg = {
        "max_total_ideas": 2000,
        "max_idea_depth": 1,
        "breadth": 4,
        "fractal_facets": True,
        "facet_depth": 3,
        "facets_per_idea": 8,
        "security_aware": False,
    }
    engine = IdeaPermutationEngine(cfg, tmp)
    engine.operators = [op for op in DEVELOPMENT_OPERATORS if op.name == "simplify"]
    return engine


# ---- the vocabulary is wired into the simplify lens (pure-data structure) ----

def test_redundant_control_flow_is_a_simplify_aspect() -> None:
    assert "redundant control flow" in _FACETS["simplify"]


def test_new_aspect_has_a_subaspect_ladder() -> None:
    """The L1 aspect decomposes into L2 groups, and each L2 group into the L3
    transform phrases — the same three-level ladder the other simplify aspects use."""
    l2 = _FACET_SUBASPECTS["redundant control flow"]
    assert l2 == ["redundant conditionals", "collapsible structure",
                  "unreachable or no-op statements"]
    # Every L2 label has its own L3 vocabulary (the routing phrases).
    for label in l2:
        assert _FACET_SUBASPECTS.get(label), f"{label!r} has no L3 sub-aspects"


def test_every_new_phrase_appears_in_an_l3_ladder() -> None:
    """Each routing phrase is genuinely present in the vocabulary so the zoom can
    reach it — not just in the objective map."""
    all_l3 = {p for subs in _FACET_SUBASPECTS.values() for p in subs}
    for phrase, _ in _NEW_LADDER:
        assert phrase in all_l3, f"{phrase!r} is in no sub-aspect ladder"


# ---- the engine GENUINELY EMITS the phrases (end-to-end through the zoom) ----

def test_engine_emits_the_new_l1_and_l2_aspects(tmp_path) -> None:
    labels = _emitted_facet_labels(_simplify_engine(tmp_path))
    assert "redundant control flow" in labels          # L1
    assert "redundant conditionals" in labels          # L2
    assert "collapsible structure" in labels           # L2
    assert "unreachable or no-op statements" in labels  # L2


def test_engine_emits_every_new_l3_phrase_end_to_end(tmp_path) -> None:
    """The headline claim: the engine's facet machinery EMITS each new L3 phrase,
    and ``facet_to_objective`` routes that emitted phrase to its objective."""
    labels = _emitted_facet_labels(_simplify_engine(tmp_path))
    for phrase, objective in _NEW_LADDER:
        assert phrase in labels, f"engine never emitted {phrase!r}"
        assert facet_to_objective(phrase) == objective


@pytest.mark.parametrize("phrase, objective", _NEW_LADDER)
def test_each_emitted_phrase_routes(phrase: str, objective: str) -> None:
    assert facet_to_objective(phrase) == objective


def test_emission_is_deterministic(tmp_path) -> None:
    """Same project + config -> identical emitted-label set (no time/random)."""
    _simplify_project(tmp_path)
    cfg = {
        "max_total_ideas": 2000, "max_idea_depth": 1, "breadth": 4,
        "fractal_facets": True, "facet_depth": 3, "facets_per_idea": 8,
        "security_aware": False,
    }

    def run_once() -> set[str]:
        eng = IdeaPermutationEngine(cfg, tmp_path)
        eng.operators = [op for op in DEVELOPMENT_OPERATORS if op.name == "simplify"]
        return _emitted_facet_labels(eng)

    assert run_once() == run_once()


def test_value_invariant_holds_with_new_facets(tmp_path) -> None:
    """Adding vocabulary must not push any node's value outside [0, 1], and roots
    keep ``novelty == 1.0``."""
    eng = _simplify_engine(tmp_path)
    rep = eng.run()
    assert all(0.0 <= idea.value <= 1.0 for idea in rep.ideas)
    assert all(abs(root.novelty - 1.0) < 1e-9 for root in rep.roots())


# ---- caveats: the new sub-concerns get their own stress test, not the broad one ----

def test_new_phrases_get_the_control_flow_caveat() -> None:
    """The engine's per-phrase caveat must interrogate the rewrite's equivalence,
    not fall through to the broad dead-code caveat (which several of these phrases'
    keywords — 'redundant', 'unreachable' — would otherwise match)."""
    from app.engine.idea_permutation import IdeaPermutationEngine as _Eng

    control_flow_caveat = (
        "What behavior changes if this 'equivalent' rewrite is wrong about a "
        "side effect or falsy edge?"
    )
    for phrase, _ in _NEW_LADDER:
        assert _Eng._facet_caveat(phrase) == control_flow_caveat, (
            f"{phrase!r} got the wrong caveat"
        )


def test_control_flow_caveat_precedes_the_broad_dead_code_rule() -> None:
    """Ordering invariant for caveats: the specific control-flow rule must come
    before the broad ('redundant'/'unreachable') rule it would otherwise lose to."""
    def first_index(*keywords: str) -> int:
        for i, (keys, _) in enumerate(_FACET_CAVEAT_RULES):
            if any(k in keys for k in keywords):
                return i
        return -1

    specific = first_index("boolean return", "redundant else")
    broad = first_index("redundant", "unreachable")
    assert specific != -1 and broad != -1
    assert specific < broad
