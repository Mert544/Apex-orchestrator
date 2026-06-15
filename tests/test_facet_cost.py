"""Depth tests for the CONSTRUCTIVE "cost / effort sequencing" fortify lens.

Before this wave the three fortify L1 aspects ("null and empty inputs",
"boundary and range limits", "the explicit error path") had NO finer
vocabulary of their own, so zooming "Fortify X -> the explicit error path"
fell straight to the generic common/boundary/failure case split — no concrete
sub-direction. And across the WHOLE facet set, no lens named *how much* of a
change to do now versus later: every other lens names WHAT to build, none
named the cheapest order to build it in.

The angle this wave grounds is cost/effort sequencing: the cheapest first
slice that earns its keep, what to defer to a later pass, and the smallest
probe that would catch a regression. The fortify lens — whose operator already
asks for the SMALLEST guard that removes an edge-input failure — is the natural
home for that angle.

This file pins two claims, both ways:

1. The vocabulary genuinely carries the new cost/effort sub-directions (pure
   data), and the enrichment is append-only (it adds no new L1 facet that could
   win a per-level beam).
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

# The constructive "cost / effort sequencing" moves this wave grounds, hung
# under the three fortify L1 aspects. Each is a concrete sub-direction an
# engineer can act on. The "cheapest first slice" and "smallest probe" moves are
# shared by all three aspects; the deferral move varies per aspect.
_CHEAPEST_SLICE = "the cheapest first slice that earns its keep"
_SMALLEST_PROBE = "the smallest probe that would catch a regression"
_DEFERRAL_MOVES = (
    "the rarer shape to defer to a later pass",
    "the costlier guard to defer to a later pass",
    "the harder failure to defer to a later pass",
)
_COST_MOVES = (_CHEAPEST_SLICE, _SMALLEST_PROBE, *_DEFERRAL_MOVES)

_FORTIFY_ASPECTS = (
    "null and empty inputs",
    "boundary and range limits",
    "the explicit error path",
)

# Forbidden literal-metric tokens — the generated facet text must never contain
# these so the determinism / negative tests elsewhere stay green.
_FORBIDDEN_TOKENS = ("imported by", "LOC", "untested")


# ---------------------------------------------------------------------------
# 1. the vocabulary carries the new cost/effort sub-directions
# ---------------------------------------------------------------------------

def test_fortify_aspects_now_have_an_l2_ladder() -> None:
    """The three fortify aspects previously fell to the case split; each now
    decomposes into concrete cost/effort sequencing moves."""
    for aspect in _FORTIFY_ASPECTS:
        assert aspect in _FACETS["fortify"]            # still a pinned L1 facet
        l2 = _FACET_SUBASPECTS.get(aspect)
        assert l2 and len(l2) >= 3, f"{aspect!r} still has no L2 sub-aspects"
        # Every L2 move is itself a real, concrete direction (not a case word).
        assert all(m not in _FACET_CASES for m in l2)


def test_every_fortify_aspect_offers_the_cheapest_slice_and_probe() -> None:
    """The cost/effort angle lands on every fortify aspect: each offers the
    cheapest first slice and the smallest regression probe, plus its own
    deferral move."""
    for aspect, deferral in zip(_FORTIFY_ASPECTS, _DEFERRAL_MOVES):
        l2 = _FACET_SUBASPECTS[aspect]
        assert _CHEAPEST_SLICE in l2
        assert _SMALLEST_PROBE in l2
        assert deferral in l2


def test_each_cost_move_decomposes_one_level_further() -> None:
    """Each L2 cost/effort move carries its own L3 ladder of concrete decisions,
    so the zoom keeps real content for a third level before the case-split floor."""
    for move in _COST_MOVES:
        l3 = _FACET_SUBASPECTS.get(move)
        assert l3 and len(l3) >= 3, f"{move!r} lacks an L3 ladder"
        assert all(c not in _FACET_CASES for c in l3)


def test_no_facet_phrasing_uses_a_forbidden_metric_token() -> None:
    """Every new label (L2 and L3) must avoid literal metric tokens so the
    determinism / negative tests stay green."""
    new_keys = (*_FORTIFY_ASPECTS, *_COST_MOVES)
    for key in new_keys:
        for phrase in _FACET_SUBASPECTS[key]:
            low = phrase.lower()
            for tok in _FORBIDDEN_TOKENS:
                assert tok.lower() not in low, f"{phrase!r} contains {tok!r}"
            # No leading "N <word>" magnitude phrase (first token is not a digit run).
            assert not phrase.split()[0].isdigit(), phrase


def test_new_phrases_are_grounded_not_vague_abstractions() -> None:
    """Each new sub-idea names a concrete, actionable next step — not a bare
    abstraction. We assert each phrase carries an actionable noun an engineer
    can point at (slice / guard / probe / failure / shape / input / assertion /
    check / follow-up / marker)."""
    actionable = (
        "slice", "guard", "probe", "failure", "shape", "input", "assertion",
        "check", "follow-up", "marker", "watch", "rewrite", "lines", "rest",
    )
    for key in _COST_MOVES:
        for phrase in _FACET_SUBASPECTS[key]:
            assert any(word in phrase for word in actionable), phrase


# ---------------------------------------------------------------------------
# 2. append-only: no new L1 facet was introduced
# ---------------------------------------------------------------------------

def test_enrichment_is_append_only_for_fortify_l1() -> None:
    """The fortify L1 facet list is unchanged — no new L1 aspect was added that
    could win the per-level beam and crowd out the pinned phrases."""
    assert _FACETS["fortify"] == [
        "null and empty inputs",
        "boundary and range limits",
        "the explicit error path",
    ]


def test_no_orphan_keys_were_introduced() -> None:
    """Every new _FACET_SUBASPECTS key is reachable: it is either an L1 aspect or
    a sub-aspect of some other key (so a zoom path can descend onto it)."""
    all_subaspects = {p for subs in _FACET_SUBASPECTS.values() for p in subs}
    all_l1 = {a for aspects in _FACETS.values() for a in aspects}
    for key in (*_FORTIFY_ASPECTS, *_COST_MOVES):
        assert key in all_l1 or key in all_subaspects, f"{key!r} is an orphan key"


def test_no_cost_ladder_loops_or_duplicates() -> None:
    """No new ladder is empty, repeats its own key (which would loop the zoom),
    or contains duplicates."""
    for key in (*_FORTIFY_ASPECTS, *_COST_MOVES):
        subs = _FACET_SUBASPECTS[key]
        assert subs, f"{key!r} ladder is empty"
        assert key not in subs, f"{key!r} ladder loops on itself"
        assert len(subs) == len(set(subs)), f"{key!r} ladder has duplicates"


# ---------------------------------------------------------------------------
# 3. the engine GENUINELY EMITS the new cost/effort sub-directions
# ---------------------------------------------------------------------------

def _fortify_project(tmp: Path) -> Path:
    """A small project with a function carrying clear edge-input risk — a
    realistic subject for the fortify zoom to descend into."""
    (tmp / "app").mkdir()
    (tmp / "app" / "core.py").write_text(
        "def parse_amount(raw):\n"
        "    return int(raw) * 2\n",
        encoding="utf-8",
    )
    (tmp / "tests").mkdir()
    (tmp / "tests" / "test_core.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    return tmp


def _fortify_cfg() -> dict:
    return {
        "max_total_ideas": 4000,
        "max_idea_depth": 1,
        "breadth": 4,
        "fractal_facets": True,
        "facet_depth": 3,
        "facets_per_idea": 8,
        "security_aware": False,
    }


def _fortify_engine(tmp: Path) -> IdeaPermutationEngine:
    """A facet-zooming engine confined to the fortify lens, so the deep zoom
    lands on the cost/effort moves rather than being out-ranked by other lenses."""
    _fortify_project(tmp)
    engine = IdeaPermutationEngine(_fortify_cfg(), tmp)
    engine.operators = [op for op in DEVELOPMENT_OPERATORS if op.name == "fortify"]
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


def test_engine_emits_the_fortify_l1_and_l2_moves(tmp_path) -> None:
    labels = _emitted_facet_labels(_fortify_engine(tmp_path))
    # the three structural L1 aspects still emit (not displaced)
    for aspect in _FORTIFY_ASPECTS:
        assert aspect in labels, aspect
    # and the new cost/effort L2 moves now emit (no longer the case split)
    assert _CHEAPEST_SLICE in labels
    assert _SMALLEST_PROBE in labels
    assert any(d in labels for d in _DEFERRAL_MOVES)


def test_emitted_text_is_grounded_and_present(tmp_path) -> None:
    """The generated sub-idea text (the title and the subject) carries the new
    phrase verbatim — proof the zoom builds a concrete, grounded sub-idea."""
    rep = _fortify_engine(tmp_path).run()
    target = _CHEAPEST_SLICE
    matches = [i for i in rep.ideas if i.kind == "facet" and i.subject.endswith(target)]
    assert matches, "no facet sub-idea was built for the cheapest-first-slice move"
    node = matches[0]
    assert target in node.title
    assert f"facet: {target}" in node.source_facts


def test_engine_emits_a_deep_cost_l3_edit(tmp_path) -> None:
    """The zoom reaches a third level of concrete content under the cost/effort
    moves — proof the L3 ladder is genuinely traversed, not just present."""
    labels = _emitted_facet_labels(_fortify_engine(tmp_path))
    l3_pool = {p for move in _COST_MOVES for p in _FACET_SUBASPECTS[move]}
    assert labels & l3_pool, "no cost/effort L3 edit was emitted"


def test_fortify_emission_is_deterministic(tmp_path) -> None:
    """Same project + config -> identical emitted-label set (no time/random)."""
    _fortify_project(tmp_path)
    cfg = _fortify_cfg()

    def run_once() -> set[str]:
        eng = IdeaPermutationEngine(cfg, tmp_path)
        eng.operators = [op for op in DEVELOPMENT_OPERATORS if op.name == "fortify"]
        return _emitted_facet_labels(eng)

    assert run_once() == run_once()


def test_value_invariant_holds_with_cost_facets(tmp_path) -> None:
    """The added vocabulary keeps every node's value in [0, 1] and roots at
    novelty 1.0."""
    rep = _fortify_engine(tmp_path).run()
    assert all(0.0 <= idea.value <= 1.0 for idea in rep.ideas)
    assert all(abs(root.novelty - 1.0) < 1e-9 for root in rep.roots())


# ---------------------------------------------------------------------------
# edge / empty paths
# ---------------------------------------------------------------------------

def test_unknown_cost_label_has_no_subaspects() -> None:
    """A label in no ladder yields nothing — the floor is the case split, handled
    by the engine, not a KeyError here."""
    assert _FACET_SUBASPECTS.get("a cost phrase that does not exist") is None


def test_cost_vocabulary_is_deterministic_pure_data() -> None:
    """The vocabulary is a frozen module-level literal — importing it in a fresh
    interpreter yields an identical mapping (no time/random construction)."""
    import subprocess
    import sys

    code = (
        "from app.engine.idea_facets import _FACET_SUBASPECTS as s;"
        "print(s['the explicit error path']);"
        "print(s['the cheapest first slice that earns its keep'])"
    )

    def run() -> str:
        return subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout

    assert run() == run()
