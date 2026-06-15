"""Depth tests for the CONSTRUCTIVE "make it reversible" verify lens.

Before this wave the three verify L1 aspects ("stated invariants",
"boundary assertions", "proof obligations") had NO finer vocabulary of their
own, so zooming "Verify X -> proof obligations" fell straight to the generic
common/boundary/failure case split — no concrete sub-direction. The angle the
whole facet set was MISSING is rollback/safety: before a change ships, what is
the undo path if it turns out wrong, and what signal confirms it is working?

This file pins two claims, both ways:

1. The vocabulary genuinely carries the new rollback/safety sub-directions
   (pure-data structure), and the enrichment is append-only (it adds no new
   L1 facet that could win a per-level beam).
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

# The constructive "make it reversible" moves this wave grounds, hung under the
# three verify L1 aspects. Each is a concrete sub-direction an engineer can act on.
_REVERSIBILITY_MOVES = [
    "the undo path if this turns out wrong",
    "the safe toggle that gates the change",
    "the signal that confirms the change is working",
]

# Forbidden literal-metric tokens — the generated facet text must never contain
# these so the determinism / negative tests elsewhere stay green.
_FORBIDDEN_TOKENS = ("imported by", "LOC", "untested")


# ---------------------------------------------------------------------------
# 1. the vocabulary carries the new reversibility sub-directions
# ---------------------------------------------------------------------------

def test_verify_aspects_now_have_an_l2_ladder() -> None:
    """The three verify aspects previously fell to the case split; each now
    decomposes into concrete reversibility / assertion moves."""
    for aspect in ("stated invariants", "boundary assertions", "proof obligations"):
        assert aspect in _FACETS["verify"]            # still a pinned L1 facet
        l2 = _FACET_SUBASPECTS.get(aspect)
        assert l2 and len(l2) >= 3, f"{aspect!r} still has no L2 sub-aspects"
        # Every L2 move is itself a real, concrete direction (not a case word).
        assert all(m not in _FACET_CASES for m in l2)


def test_proof_obligations_carries_the_rollback_safety_moves() -> None:
    """The rollback/safety angle lands on 'proof obligations' — the strongest
    obligation a change must meet is that it can be safely backed out."""
    l2 = _FACET_SUBASPECTS["proof obligations"]
    assert l2 == _REVERSIBILITY_MOVES


def test_each_reversibility_move_decomposes_one_level_further() -> None:
    """Each L2 reversibility move carries its own L3 ladder of concrete edits, so
    the zoom keeps real content for a third level before the case-split floor."""
    for move in _REVERSIBILITY_MOVES:
        l3 = _FACET_SUBASPECTS.get(move)
        assert l3 and len(l3) >= 3, f"{move!r} lacks an L3 ladder"
        assert all(c not in _FACET_CASES for c in l3)


def test_no_facet_phrasing_uses_a_forbidden_metric_token() -> None:
    """Every new label (L2 and L3) must avoid literal metric tokens so the
    determinism / negative tests stay green."""
    new_keys = ("stated invariants", "boundary assertions", "proof obligations",
                *_REVERSIBILITY_MOVES)
    for key in new_keys:
        for phrase in _FACET_SUBASPECTS[key]:
            low = phrase.lower()
            for tok in _FORBIDDEN_TOKENS:
                assert tok.lower() not in low, f"{phrase!r} contains {tok!r}"
            # No leading "N <word>" magnitude phrase (first token is not a digit run).
            assert not phrase.split()[0].isdigit(), phrase


# ---------------------------------------------------------------------------
# 2. append-only: no new L1 facet was introduced
# ---------------------------------------------------------------------------

def test_enrichment_is_append_only_for_verify_l1() -> None:
    """The verify L1 facet list is unchanged — no new L1 aspect was added that
    could win the per-level beam and crowd out the pinned phrases."""
    assert _FACETS["verify"] == [
        "stated invariants", "boundary assertions", "proof obligations",
    ]


def test_no_orphan_keys_were_introduced() -> None:
    """Every new _FACET_SUBASPECTS key is reachable: it is either an L1 aspect or
    a sub-aspect of some other key (so a zoom path can descend onto it)."""
    all_subaspects = {p for subs in _FACET_SUBASPECTS.values() for p in subs}
    all_l1 = {a for aspects in _FACETS.values() for a in aspects}
    for key in ("stated invariants", "boundary assertions", "proof obligations",
                *_REVERSIBILITY_MOVES):
        assert key in all_l1 or key in all_subaspects, f"{key!r} is an orphan key"


def test_no_reversibility_ladder_loops_or_duplicates() -> None:
    """No new ladder is empty, repeats its own key (which would loop the zoom),
    or contains duplicates."""
    for key in ("stated invariants", "boundary assertions", "proof obligations",
                *_REVERSIBILITY_MOVES):
        subs = _FACET_SUBASPECTS[key]
        assert subs, f"{key!r} ladder is empty"
        assert key not in subs, f"{key!r} ladder loops on itself"
        assert len(subs) == len(set(subs)), f"{key!r} ladder has duplicates"


# ---------------------------------------------------------------------------
# 3. the engine GENUINELY EMITS the new reversibility sub-directions
# ---------------------------------------------------------------------------

def _verify_project(tmp: Path) -> Path:
    """A small project with a function carrying a clear pre/postcondition shape —
    a realistic subject for the verify zoom to descend into."""
    (tmp / "app").mkdir()
    (tmp / "app" / "core.py").write_text(
        "def transfer(amount, src, dst):\n"
        "    assert amount > 0\n"
        "    src.balance -= amount\n"
        "    dst.balance += amount\n"
        "    return src.balance, dst.balance\n",
        encoding="utf-8",
    )
    (tmp / "tests").mkdir()
    (tmp / "tests" / "test_core.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    return tmp


def _verify_cfg() -> dict:
    return {
        "max_total_ideas": 4000,
        "max_idea_depth": 1,
        "breadth": 4,
        "fractal_facets": True,
        "facet_depth": 3,
        "facets_per_idea": 8,
        "security_aware": False,
    }


def _verify_engine(tmp: Path) -> IdeaPermutationEngine:
    """A facet-zooming engine confined to the verify lens, so the deep zoom lands
    on the reversibility moves rather than being out-ranked by higher-feasibility
    lenses (test/harden/document)."""
    _verify_project(tmp)
    engine = IdeaPermutationEngine(_verify_cfg(), tmp)
    engine.operators = [op for op in DEVELOPMENT_OPERATORS if op.name == "verify"]
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


def test_engine_emits_the_verify_l1_and_l2_moves(tmp_path) -> None:
    labels = _emitted_facet_labels(_verify_engine(tmp_path))
    # the three structural L1 aspects still emit (not displaced)
    assert "proof obligations" in labels
    assert "stated invariants" in labels
    assert "boundary assertions" in labels
    # and the new reversibility L2 moves now emit (no longer the case split)
    assert "the undo path if this turns out wrong" in labels
    assert "the safe toggle that gates the change" in labels
    assert "the signal that confirms the change is working" in labels


def test_emitted_text_is_grounded_and_present(tmp_path) -> None:
    """The generated sub-idea text (the title and the subject) carries the new
    phrase verbatim — proof the zoom builds a concrete, grounded sub-idea."""
    rep = _verify_engine(tmp_path).run()
    target = "the undo path if this turns out wrong"
    matches = [i for i in rep.ideas if i.kind == "facet" and i.subject.endswith(target)]
    assert matches, "no facet sub-idea was built for the undo-path move"
    node = matches[0]
    assert target in node.title
    assert f"facet: {target}" in node.source_facts


def test_engine_emits_a_deep_reversibility_l3_edit(tmp_path) -> None:
    """The zoom reaches a third level of concrete content under the reversibility
    moves — proof the L3 ladder is genuinely traversed, not just present."""
    labels = _emitted_facet_labels(_verify_engine(tmp_path))
    l3_pool = {p for move in _REVERSIBILITY_MOVES for p in _FACET_SUBASPECTS[move]}
    assert labels & l3_pool, "no reversibility L3 edit was emitted"


def test_verify_emission_is_deterministic(tmp_path) -> None:
    """Same project + config -> identical emitted-label set (no time/random)."""
    _verify_project(tmp_path)
    cfg = _verify_cfg()

    def run_once() -> set[str]:
        eng = IdeaPermutationEngine(cfg, tmp_path)
        eng.operators = [op for op in DEVELOPMENT_OPERATORS if op.name == "verify"]
        return _emitted_facet_labels(eng)

    assert run_once() == run_once()


def test_value_invariant_holds_with_reversibility_facets(tmp_path) -> None:
    """The added vocabulary keeps every node's value in [0, 1] and roots at
    novelty 1.0."""
    rep = _verify_engine(tmp_path).run()
    assert all(0.0 <= idea.value <= 1.0 for idea in rep.ideas)
    assert all(abs(root.novelty - 1.0) < 1e-9 for root in rep.roots())


# ---------------------------------------------------------------------------
# edge / empty paths
# ---------------------------------------------------------------------------

def test_unknown_verify_label_has_no_subaspects() -> None:
    """A label in no ladder yields nothing — the floor is the case split, handled
    by the engine, not a KeyError here."""
    assert _FACET_SUBASPECTS.get("a reversibility phrase that does not exist") is None


def test_reversibility_vocabulary_is_deterministic_pure_data() -> None:
    """The vocabulary is a frozen module-level literal — importing it in a fresh
    interpreter yields an identical mapping (no time/random construction)."""
    import subprocess
    import sys

    code = (
        "from app.engine.idea_facets import _FACET_SUBASPECTS as s;"
        "print(s['proof obligations']);"
        "print(s['the undo path if this turns out wrong'])"
    )

    def run() -> str:
        return subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout

    assert run() == run()
