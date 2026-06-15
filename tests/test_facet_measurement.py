"""Depth tests for the CONSTRUCTIVE "close the measurement loop" observe lens.

Before this wave every observe sub-aspect named a signal to EMIT (a counter, a
log field, a span), but across the WHOLE observe lens nothing named what the
signal is actually FOR. Instrumentation with no question to answer, no baseline
to compare against, and no action when it trips is shelf-ware. The angle the
observe lens was MISSING is the measurement loop: the question a signal should
answer, the baseline/threshold that makes it actionable, and the action taken
when it crosses that line.

This file pins two claims, both ways:

1. The vocabulary genuinely carries the new measurement-loop sub-directions
   (pure-data structure), and the enrichment is append-only (it adds no new L1
   facet that could win a per-level beam, and the original emit-the-signal
   phrases stay FIRST in each observe L2 list).
2. The engine's zoom machinery genuinely EMITS them end-to-end, deterministically.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.idea_facets import (
    _FACET_CASES,
    _FACET_SUBASPECTS,
    _FACETS,
)
from app.engine.idea_permutation import DEVELOPMENT_OPERATORS, IdeaPermutationEngine

# The measurement-loop moves this wave grounds, appended under the three observe
# L1 aspects. Each is a concrete sub-direction an engineer can act on.
_MEASUREMENT_MOVES = [
    "the question this metric should answer",
    "the baseline or threshold that makes it actionable",
    "the action taken when it crosses the threshold",
    "the question a search of these logs should answer",
    "the action taken when the log pattern appears",
    "the latency question this span should answer",
]

# The original emit-the-signal phrases that must stay FIRST (undisturbed beam).
_OBSERVE_ORIGINAL_L2 = {
    "key metrics": ["counters", "latency histograms", "error rates"],
    "structured logs": ["correlation ids", "level discipline", "no secret leakage"],
    "trace spans": ["span boundaries", "attributes", "error recording"],
}

# Forbidden literal tokens — generated facet text must never contain these so the
# determinism / negative tests elsewhere stay green.
_FORBIDDEN_TOKENS = ("imported by", "LOC", "untested")


# ---------------------------------------------------------------------------
# 1. the vocabulary carries the new measurement-loop sub-directions
# ---------------------------------------------------------------------------

def test_observe_l2_lists_are_extended_originals_first() -> None:
    """Each observe L2 list keeps its emit-the-signal phrases FIRST, then carries
    the appended measurement-loop moves — append-only, so the beam is undisturbed."""
    for aspect, original in _OBSERVE_ORIGINAL_L2.items():
        assert aspect in _FACETS["observe"]            # still a pinned L1 facet
        l2 = _FACET_SUBASPECTS[aspect]
        assert l2[: len(original)] == original, f"{aspect!r} reordered its originals"
        appended = l2[len(original):]
        assert appended, f"{aspect!r} gained no measurement move"
        assert all(m in _MEASUREMENT_MOVES for m in appended)
        assert all(m not in _FACET_CASES for m in l2)


def test_every_measurement_move_decomposes_one_level_further() -> None:
    """Each measurement-loop L2 move carries its own L3 ladder of concrete edits, so
    the zoom keeps real content for a third level before the case-split floor."""
    for move in _MEASUREMENT_MOVES:
        l3 = _FACET_SUBASPECTS.get(move)
        assert l3 and len(l3) >= 3, f"{move!r} lacks an L3 ladder"
        assert all(c not in _FACET_CASES for c in l3)


def test_no_facet_phrasing_uses_a_forbidden_token() -> None:
    """Every new label (L2 move and its L3 ladder) avoids the forbidden literal
    tokens and the leading 'N <word>' magnitude shape."""
    new_keys = (*_OBSERVE_ORIGINAL_L2, *_MEASUREMENT_MOVES)
    for key in new_keys:
        for phrase in _FACET_SUBASPECTS[key]:
            low = phrase.lower()
            for tok in _FORBIDDEN_TOKENS:
                assert tok.lower() not in low, f"{phrase!r} contains {tok!r}"
            assert not phrase.split()[0].isdigit(), phrase


# ---------------------------------------------------------------------------
# 2. append-only: no new L1 facet was introduced, no ladder loops
# ---------------------------------------------------------------------------

def test_enrichment_is_append_only_for_observe_l1() -> None:
    """The observe L1 facet list is unchanged — no new L1 aspect was added that
    could win the per-level beam and crowd out the pinned phrases."""
    assert _FACETS["observe"] == ["key metrics", "structured logs", "trace spans"]


def test_no_orphan_keys_were_introduced() -> None:
    """Every new _FACET_SUBASPECTS key is reachable: it is either an L1 aspect or a
    sub-aspect of some other key (so a zoom path can descend onto it)."""
    all_subaspects = {p for subs in _FACET_SUBASPECTS.values() for p in subs}
    all_l1 = {a for aspects in _FACETS.values() for a in aspects}
    for key in (*_OBSERVE_ORIGINAL_L2, *_MEASUREMENT_MOVES):
        assert key in all_l1 or key in all_subaspects, f"{key!r} is an orphan key"


def test_no_measurement_ladder_loops_or_duplicates() -> None:
    """No new ladder is empty, repeats its own key (which would loop the zoom), or
    contains duplicates."""
    for key in (*_OBSERVE_ORIGINAL_L2, *_MEASUREMENT_MOVES):
        subs = _FACET_SUBASPECTS[key]
        assert subs, f"{key!r} ladder is empty"
        assert key not in subs, f"{key!r} ladder loops on itself"
        assert len(subs) == len(set(subs)), f"{key!r} ladder has duplicates"


# ---------------------------------------------------------------------------
# 3. the engine GENUINELY EMITS the new measurement-loop sub-directions
# ---------------------------------------------------------------------------

def _observe_project(tmp: Path) -> Path:
    """A small project with a function worth instrumenting — a realistic subject
    for the observe zoom to descend into."""
    (tmp / "app").mkdir()
    (tmp / "app" / "core.py").write_text(
        "def handle(request):\n"
        "    result = process(request)\n"
        "    return result\n",
        encoding="utf-8",
    )
    (tmp / "tests").mkdir()
    (tmp / "tests" / "test_core.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    return tmp


def _observe_cfg() -> dict:
    return {
        "max_total_ideas": 4000,
        "max_idea_depth": 1,
        "breadth": 4,
        "fractal_facets": True,
        "facet_depth": 3,
        "facets_per_idea": 8,
        "security_aware": False,
    }


def _observe_engine(tmp: Path) -> IdeaPermutationEngine:
    """A facet-zooming engine confined to the observe lens, so the deep zoom lands
    on the measurement moves rather than being out-ranked by higher-feasibility
    lenses."""
    _observe_project(tmp)
    engine = IdeaPermutationEngine(_observe_cfg(), tmp)
    engine.operators = [op for op in DEVELOPMENT_OPERATORS if op.name == "observe"]
    return engine


def _emitted_facet_labels(engine: IdeaPermutationEngine) -> set[str]:
    rep = engine.run()
    labels: set[str] = set()
    for idea in rep.ideas:
        if idea.kind != "facet":
            continue
        for fact in idea.source_facts:
            if fact.startswith("facet:"):
                labels.add(fact.split("facet:", 1)[1].strip())
    return labels


def test_engine_emits_the_observe_l1_and_measurement_moves(tmp_path) -> None:
    labels = _emitted_facet_labels(_observe_engine(tmp_path))
    # the three structural L1 aspects still emit (not displaced)
    assert "key metrics" in labels
    assert "structured logs" in labels
    assert "trace spans" in labels
    # the original emit-the-signal L2 phrases still emit
    assert "counters" in labels
    # and at least one new measurement-loop move now emits (no longer the case split)
    assert labels & set(_MEASUREMENT_MOVES), "no measurement-loop move was emitted"


def test_emitted_text_is_grounded_and_present(tmp_path) -> None:
    """The generated sub-idea text (the title and the subject) carries the new
    phrase verbatim — proof the zoom builds a concrete, grounded sub-idea."""
    rep = _observe_engine(tmp_path).run()
    target = "the question this metric should answer"
    matches = [i for i in rep.ideas if i.kind == "facet" and i.subject.endswith(target)]
    assert matches, "no facet sub-idea was built for the metric-question move"
    node = matches[0]
    assert target in node.title
    assert f"facet: {target}" in node.source_facts


def test_engine_emits_a_deep_measurement_l3_edit(tmp_path) -> None:
    """The zoom reaches a third level of concrete content under the measurement
    moves — proof the L3 ladder is genuinely traversed, not just present."""
    labels = _emitted_facet_labels(_observe_engine(tmp_path))
    l3_pool = {p for move in _MEASUREMENT_MOVES for p in _FACET_SUBASPECTS[move]}
    assert labels & l3_pool, "no measurement L3 edit was emitted"


def test_observe_emission_is_deterministic(tmp_path) -> None:
    """Same project + config -> identical emitted-label set (no time/random)."""
    _observe_project(tmp_path)
    cfg = _observe_cfg()

    def run_once() -> set[str]:
        eng = IdeaPermutationEngine(cfg, tmp_path)
        eng.operators = [op for op in DEVELOPMENT_OPERATORS if op.name == "observe"]
        return _emitted_facet_labels(eng)

    assert run_once() == run_once()


def test_value_invariant_holds_with_measurement_facets(tmp_path) -> None:
    """The added vocabulary keeps every node's value in [0, 1] and roots at
    novelty 1.0."""
    rep = _observe_engine(tmp_path).run()
    assert all(0.0 <= idea.value <= 1.0 for idea in rep.ideas)
    assert all(abs(root.novelty - 1.0) < 1e-9 for root in rep.roots())


# ---------------------------------------------------------------------------
# edge / empty paths
# ---------------------------------------------------------------------------

def test_unknown_measurement_label_has_no_subaspects() -> None:
    """A label in no ladder yields nothing — the floor is the case split, handled
    by the engine, not a KeyError here."""
    assert _FACET_SUBASPECTS.get("a measurement phrase that does not exist") is None


def test_measurement_vocabulary_is_deterministic_pure_data() -> None:
    """The vocabulary is a frozen module-level literal — importing it in a fresh
    interpreter yields an identical mapping (no time/random construction)."""
    import subprocess
    import sys

    code = (
        "from app.engine.idea_facets import _FACET_SUBASPECTS as s;"
        "print(s['key metrics']);"
        "print(s['the question this metric should answer'])"
    )

    def run() -> str:
        return subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout

    assert run() == run()
