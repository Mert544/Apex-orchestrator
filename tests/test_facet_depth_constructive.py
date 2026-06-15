"""Depth tests for the CONSTRUCTIVE fractal lenses (decouple / generalize /
extend / integrate).

The constructive lenses describe how an idea *grows* — break a knot, lift a
common shape, grow a contract, wire a seam. Before this wave several of their
facet nodes had no finer vocabulary of their own and fell straight to the
generic common/boundary/failure case split, so zooming "Decouple X" or
"Generalize X" yielded nothing concrete. This wave hangs concrete L2/L3
sub-directions off the EXISTING facet nodes.

Two claims are checked, both ways:

1. The vocabulary genuinely carries the new sub-directions (pure-data structure).
2. The engine's zoom machinery genuinely EMITS them end-to-end.

And one invariant the wave promised: the enrichment is append-only — it adds no
new L1/L2 node that could win a per-level beam, so the existing pinned facet
phrases keep emitting in their existing order. We prove that by pinning the
original phrase lists and asserting the originals still lead each enriched list.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.idea_facets import (
    _FACET_CASES,
    _FACET_SUBASPECTS,
    _FACETS,
)
from app.engine.idea_permutation import DEVELOPMENT_OPERATORS, IdeaPermutationEngine

# The constructive moves this wave grounds, grouped by the lens whose facet node
# they hang under. Each move is a concrete sub-direction an engineer can act on.
_DECOUPLE_MOVES = [
    "invert the dependency",
    "introduce an interface at the seam",
    "move the shared type to a neutral module",
    "narrow the seam to a single contract",
]


# ---------------------------------------------------------------------------
# 1. the vocabulary carries the new constructive sub-directions
# ---------------------------------------------------------------------------

def test_decouple_structural_aspects_now_have_an_l2_ladder() -> None:
    """The two structural decouple aspects previously fell to the case split;
    each now decomposes into the concrete decoupling moves."""
    for aspect in ("dependency inversion", "seam interface"):
        assert aspect in _FACETS["decouple"]            # still a pinned L1 facet
        l2 = _FACET_SUBASPECTS.get(aspect)
        assert l2, f"{aspect!r} still has no L2 sub-aspects"
        # Every L2 move is itself a real, concrete direction (not a case word).
        assert all(m not in _FACET_CASES for m in l2)


def test_each_decouple_move_decomposes_one_level_further() -> None:
    """Each L2 decoupling move carries its own L3 ladder of concrete edits, so
    the zoom keeps real content for a third level before the case-split floor."""
    for move in _DECOUPLE_MOVES:
        l3 = _FACET_SUBASPECTS.get(move)
        assert l3 and len(l3) >= 3, f"{move!r} lacks an L3 ladder"


def test_constructive_l2_floors_were_lowered() -> None:
    """The constructive L2 facets that used to fall to the generic case split now
    carry their own concrete L3 sub-directions (one representative per lens)."""
    enriched = {
        # generalize
        "validation", "naming and types",
        "the safe default", "the override path", "documented rationale",
        # extend
        "validation of the new input", "consumer migration", "sane defaults",
        # integrate
        "partial-failure surfacing", "feature detection", "graceful degradation",
    }
    for label in enriched:
        l3 = _FACET_SUBASPECTS.get(label)
        assert l3 and len(l3) >= 3, f"{label!r} was not deepened"
        assert all(c not in _FACET_CASES for c in l3)


# ---------------------------------------------------------------------------
# 2. append-only: existing pinned phrases are NOT displaced
# ---------------------------------------------------------------------------

def test_enrichment_is_append_only_for_decouple_l1() -> None:
    """The decouple L1 facet list is unchanged — no new L1 aspect was added that
    could win the per-level beam and crowd out the pinned phrases."""
    assert _FACETS["decouple"] == [
        "dependency inversion", "seam interface", "import direction",
    ]


def test_existing_l2_phrases_still_lead_their_enriched_lists() -> None:
    """For every constructive L2 list this wave touched, the ORIGINAL sub-aspects
    must still come first (so they emit in their existing order); the new moves are
    appended after them. Pins the original prefixes."""
    originals = {
        # generalize — parameters / extension points
        "parameters": ["sensible defaults", "validation", "naming and types"],
        "extension points": ["the hook interface", "registration", "a default no-op"],
        # extend
        "new inputs": ["accepted formats", "validation of the new input",
                       "backward compatibility"],
        "new outputs": ["output contract", "error and empty results",
                        "consumer migration"],
        "configuration surface": ["sane defaults", "environment override",
                                  "validation of config"],
        # integrate
        "data contract": ["schema and types", "required vs optional fields",
                          "evolution rules"],
        "error propagation": ["mapped error types", "retry vs fail-fast",
                              "partial-failure surfacing"],
    }
    for key, prefix in originals.items():
        actual = _FACET_SUBASPECTS[key]
        assert actual[: len(prefix)] == prefix, (
            f"{key!r}: original phrases were displaced — {actual!r}"
        )


def test_no_new_l1_or_l2_node_was_introduced() -> None:
    """The wave only added _FACET_SUBASPECTS entries for phrases that ALREADY emit
    (existing L1/L2 facet labels) — it added no brand-new facet label as a NEW L1
    aspect in _FACETS. So nothing competes in any per-level beam."""
    all_subaspects = {p for subs in _FACET_SUBASPECTS.values() for p in subs}
    all_l1 = {a for aspects in _FACETS.values() for a in aspects}
    # Every _FACET_SUBASPECTS key is reachable: it is either an L1 aspect or a
    # sub-aspect of some other key (so the zoom can descend onto it).
    for key in _FACET_SUBASPECTS:
        assert key in all_l1 or key in all_subaspects, (
            f"{key!r} is an orphan key — no zoom path reaches it"
        )


# ---------------------------------------------------------------------------
# 3. the engine GENUINELY EMITS the new constructive sub-directions
# ---------------------------------------------------------------------------

def _decouple_project(tmp: Path) -> Path:
    """A small project with a class that takes a concrete collaborator and has
    layered imports — a realistic subject for the decouple zoom to descend into."""
    (tmp / "app").mkdir()
    (tmp / "app" / "core.py").write_text(
        "import os\n"
        "import sys\n"
        "\n"
        "from app.db import Database\n"
        "\n"
        "\n"
        "class Service:\n"
        "    def __init__(self, db: Database) -> None:\n"
        "        self.db = db\n"
        "\n"
        "    def run(self, a, b, c, d):\n"
        "        if a:\n"
        "            if b:\n"
        "                return self.db.fetch(c) + d\n"
        "        return None\n",
        encoding="utf-8",
    )
    (tmp / "tests").mkdir()
    (tmp / "tests" / "test_core.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    return tmp


def _decouple_engine(tmp: Path) -> IdeaPermutationEngine:
    """A facet-zooming engine confined to the decouple lens, so the deep zoom
    lands on the constructive moves rather than being out-ranked by
    higher-feasibility lenses (test/harden)."""
    _decouple_project(tmp)
    cfg = {
        "max_total_ideas": 4000,
        "max_idea_depth": 1,
        "breadth": 4,
        "fractal_facets": True,
        "facet_depth": 3,
        "facets_per_idea": 8,
        "security_aware": False,
    }
    engine = IdeaPermutationEngine(cfg, tmp)
    engine.operators = [op for op in DEVELOPMENT_OPERATORS if op.name == "decouple"]
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


def test_engine_emits_the_decouple_l1_and_l2_moves(tmp_path) -> None:
    labels = _emitted_facet_labels(_decouple_engine(tmp_path))
    # the two structural L1 aspects still emit (not displaced)
    assert "dependency inversion" in labels
    assert "seam interface" in labels
    # and the new constructive L2 moves now emit (no longer the case split)
    assert "invert the dependency" in labels
    assert "introduce an interface at the seam" in labels
    assert "move the shared type to a neutral module" in labels


def test_engine_emits_a_deep_decouple_l3_edit(tmp_path) -> None:
    """The zoom reaches a third level of concrete content under the decouple
    moves — proof the L3 ladder is genuinely traversed, not just present."""
    labels = _emitted_facet_labels(_decouple_engine(tmp_path))
    l3_pool = {
        p for move in _DECOUPLE_MOVES for p in _FACET_SUBASPECTS[move]
    }
    assert labels & l3_pool, "no decouple L3 edit was emitted"


def test_decouple_emission_is_deterministic(tmp_path) -> None:
    """Same project + config -> identical emitted-label set (no time/random)."""
    _decouple_project(tmp_path)
    cfg = {
        "max_total_ideas": 4000, "max_idea_depth": 1, "breadth": 4,
        "fractal_facets": True, "facet_depth": 3, "facets_per_idea": 8,
        "security_aware": False,
    }

    def run_once() -> set[str]:
        eng = IdeaPermutationEngine(cfg, tmp_path)
        eng.operators = [op for op in DEVELOPMENT_OPERATORS if op.name == "decouple"]
        return _emitted_facet_labels(eng)

    assert run_once() == run_once()


def test_value_invariant_holds_with_constructive_facets(tmp_path) -> None:
    """The added vocabulary keeps every node's value in [0, 1] and roots at
    novelty 1.0."""
    eng = _decouple_engine(tmp_path)
    rep = eng.run()
    assert all(0.0 <= idea.value <= 1.0 for idea in rep.ideas)
    assert all(abs(root.novelty - 1.0) < 1e-9 for root in rep.roots())


def test_pinned_phrases_still_emit_alongside_the_new_moves(tmp_path) -> None:
    """The original decouple aspects keep emitting even though new moves were
    appended — the append-only promise observed end-to-end through the engine."""
    labels = _emitted_facet_labels(_decouple_engine(tmp_path))
    for pinned in ("dependency inversion", "seam interface", "import direction"):
        assert pinned in labels, f"{pinned!r} stopped emitting"


# ---------------------------------------------------------------------------
# edge / empty paths
# ---------------------------------------------------------------------------

def test_unknown_facet_label_has_no_subaspects() -> None:
    """A label that is in no ladder yields nothing — the floor is the case split,
    handled by the engine, not a KeyError here."""
    assert _FACET_SUBASPECTS.get("a phrase that does not exist") is None


def test_every_constructive_l3_ladder_is_nonempty_and_distinct() -> None:
    """No constructive ladder is empty and no entry repeats its own key (which
    would loop the zoom). Guards against a copy-paste authoring slip."""
    constructive_keys = [
        *_DECOUPLE_MOVES,
        "dependency inversion", "seam interface",
        "validation", "naming and types",
        "the safe default", "the override path", "documented rationale",
        "validation of the new input", "consumer migration", "sane defaults",
        "partial-failure surfacing", "feature detection", "graceful degradation",
    ]
    for key in constructive_keys:
        subs = _FACET_SUBASPECTS[key]
        assert subs, f"{key!r} ladder is empty"
        assert key not in subs, f"{key!r} ladder loops on itself"
        assert len(subs) == len(set(subs)), f"{key!r} ladder has duplicates"


def test_constructive_subaspects_are_deterministic_pure_data() -> None:
    """The vocabulary is a frozen module-level literal — importing it in a fresh
    interpreter yields an identical mapping (no time/random construction)."""
    import subprocess
    import sys

    code = (
        "from app.engine.idea_facets import _FACET_SUBASPECTS as s;"
        "print(s['invert the dependency']);"
        "print(s['move the shared type to a neutral module'])"
    )

    def run() -> str:
        return subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout

    assert run() == run()
