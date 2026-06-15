"""Depth tests for the CONSTRUCTIVE "carry the callers across" migration lens.

Before this wave the whole facet set's only migration vocabulary lived under the
EXTEND lens (``new inputs``/``new outputs`` -> backward compatibility, consumer
migration), i.e. how to grow ADDITIVE surface. NOTHING named how the EXISTING
callers cross a *version-skewed* change safely. So a zoom that reached
"Integrate X -> version skew" carried only the compatibility/feature-detection
phrases and the sequencing moves (what lands first) — never the migration moves.

``version skew`` is the natural home: it is the one aspect whose whole job is two
sides on different versions. This wave EXTENDS its L2 list (originals stay FIRST,
never displaced) with the three migration/compatibility moves — a deprecation
shim, a backward-compatible default, and a staged rollout across cohorts — each
itself decomposing one level further into concrete edits.

This file pins two claims, both ways:

1. The vocabulary genuinely carries the new migration sub-directions (pure-data
   structure), and the enrichment is append-only (it adds no new L1 facet that
   could win a per-level beam and it leaves the originals first).
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

# The constructive "carry the callers across" moves this wave grounds, appended
# under the integrate ``version skew`` aspect. Each is a concrete next step an
# engineer can act on to ship a change without breaking existing callers.
_MIGRATION_MOVES = [
    "the deprecation shim that keeps old callers working",
    "the backward-compatible default for existing callers",
    "the staged rollout across caller cohorts",
]

# The five phrases ``version skew`` already emitted before this wave — they must
# stay FIRST so none is displaced from its per-level beam slot.
_VERSION_SKEW_ORIGINALS = [
    "compatibility window",
    "feature detection",
    "graceful degradation",
    "the prerequisite change that must land first",
    "the downstream work this change unblocks",
]

# Forbidden literal-metric tokens — the generated facet text must never contain
# these so the determinism / negative tests elsewhere stay green.
_FORBIDDEN_TOKENS = ("imported by", "LOC", "untested")


# ---------------------------------------------------------------------------
# 1. the vocabulary carries the new migration sub-directions
# ---------------------------------------------------------------------------

def test_version_skew_now_carries_the_migration_moves() -> None:
    """``version skew`` previously offered only compatibility/feature-detection
    and the sequencing moves; it now also carries the three migration moves."""
    l2 = _FACET_SUBASPECTS["version skew"]
    for move in _MIGRATION_MOVES:
        assert move in l2, f"{move!r} missing from version-skew L2"
    # Every migration move is itself a real, concrete direction (not a case word).
    assert all(m not in _FACET_CASES for m in _MIGRATION_MOVES)


def test_migration_moves_are_appended_originals_stay_first() -> None:
    """The five original phrases keep their order at the FRONT of the list and the
    three migration moves are appended at the END — proof the enrichment is
    append-only and never displaces a pinned phrase from its beam slot."""
    l2 = _FACET_SUBASPECTS["version skew"]
    assert l2[: len(_VERSION_SKEW_ORIGINALS)] == _VERSION_SKEW_ORIGINALS
    assert l2[len(_VERSION_SKEW_ORIGINALS):] == _MIGRATION_MOVES


def test_each_migration_move_decomposes_one_level_further() -> None:
    """Each L2 migration move carries its own L3 ladder of concrete edits, so the
    zoom keeps real content for a third level before the case-split floor."""
    for move in _MIGRATION_MOVES:
        l3 = _FACET_SUBASPECTS.get(move)
        assert l3 and len(l3) >= 3, f"{move!r} lacks an L3 ladder"
        assert all(c not in _FACET_CASES for c in l3)


def test_migration_lens_is_distinct_from_the_extend_migration_vocab() -> None:
    """The new moves are grounded under the integrate ``version skew`` aspect, NOT
    reused from the extend lens's additive-surface migration phrases — the angle
    (carry existing callers across a version-skewed change) is genuinely new."""
    # The extend-lens migration phrases hang off ``new inputs``/``new outputs``.
    extend_migration = set(_FACET_SUBASPECTS["new inputs"]) | set(
        _FACET_SUBASPECTS["new outputs"]
    )
    for move in _MIGRATION_MOVES:
        assert move not in extend_migration, f"{move!r} duplicates an extend phrase"


def test_no_facet_phrasing_uses_a_forbidden_metric_token() -> None:
    """Every label this wave AUTHORED (the L2 migration moves and their L3
    ladders) must avoid the literal metric tokens and the leading "N <word>"
    magnitude shape so the determinism / negative tests stay green. The token
    match is case-sensitive on the literal metric token (``LOC``), matching how
    the canonical negative tests detect a lines-of-code magnitude — a lowercased
    substring match would spuriously trip on words like "unblocks"."""
    for key in _MIGRATION_MOVES:
        for phrase in (key, *_FACET_SUBASPECTS[key]):
            for tok in _FORBIDDEN_TOKENS:
                assert tok not in phrase, f"{phrase!r} contains {tok!r}"
            assert not phrase.split()[0].isdigit(), phrase


# ---------------------------------------------------------------------------
# 2. append-only: no new L1 facet was introduced
# ---------------------------------------------------------------------------

def test_enrichment_is_append_only_for_integrate_l1() -> None:
    """The integrate L1 facet list is unchanged — no new L1 aspect was added that
    could win the per-level beam and crowd out the pinned phrases."""
    assert _FACETS["integrate"] == [
        "data contract", "error propagation", "version skew",
    ]


def test_no_orphan_keys_were_introduced() -> None:
    """Every new _FACET_SUBASPECTS key is reachable: it is either an L1 aspect or
    a sub-aspect of some other key (so a zoom path can descend onto it)."""
    all_subaspects = {p for subs in _FACET_SUBASPECTS.values() for p in subs}
    all_l1 = {a for aspects in _FACETS.values() for a in aspects}
    for key in _MIGRATION_MOVES:
        assert key in all_l1 or key in all_subaspects, f"{key!r} is an orphan key"


def test_no_migration_ladder_loops_or_duplicates() -> None:
    """No new ladder is empty, repeats its own key (which would loop the zoom),
    or contains duplicates."""
    for key in ("version skew", *_MIGRATION_MOVES):
        subs = _FACET_SUBASPECTS[key]
        assert subs, f"{key!r} ladder is empty"
        assert key not in subs, f"{key!r} ladder loops on itself"
        assert len(subs) == len(set(subs)), f"{key!r} ladder has duplicates"


# ---------------------------------------------------------------------------
# 3. the engine GENUINELY EMITS the new migration sub-directions
# ---------------------------------------------------------------------------

def _integrate_project(tmp: Path) -> Path:
    """A small project with a module that has a clear cross-version seam — a
    realistic subject for the integrate zoom to descend into."""
    (tmp / "app").mkdir()
    (tmp / "app" / "client.py").write_text(
        "def call(payload, version=1):\n"
        "    if version == 1:\n"
        "        return _legacy(payload)\n"
        "    return _modern(payload)\n"
        "\n"
        "def _legacy(payload):\n"
        "    return payload\n"
        "\n"
        "def _modern(payload):\n"
        "    return {'data': payload}\n",
        encoding="utf-8",
    )
    (tmp / "tests").mkdir()
    (tmp / "tests" / "test_client.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    return tmp


def _integrate_cfg() -> dict:
    return {
        "max_total_ideas": 4000,
        "max_idea_depth": 1,
        "breadth": 4,
        "fractal_facets": True,
        "facet_depth": 3,
        "facets_per_idea": 8,
        "security_aware": False,
    }


def _integrate_engine(tmp: Path) -> IdeaPermutationEngine:
    """A facet-zooming engine confined to the integrate lens, so the deep zoom
    lands on the version-skew migration moves rather than being out-ranked by
    higher-feasibility lenses (test/harden/document)."""
    _integrate_project(tmp)
    engine = IdeaPermutationEngine(_integrate_cfg(), tmp)
    engine.operators = [op for op in DEVELOPMENT_OPERATORS if op.name == "integrate"]
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


def test_engine_emits_the_version_skew_and_migration_moves(tmp_path) -> None:
    labels = _emitted_facet_labels(_integrate_engine(tmp_path))
    # version skew still emits as an L1->L2 aspect (not displaced)
    assert "version skew" in labels
    # the original sequencing/compatibility phrases still emit
    assert "compatibility window" in labels
    assert "the prerequisite change that must land first" in labels
    # and the new migration moves now emit (no longer absent)
    for move in _MIGRATION_MOVES:
        assert move in labels, f"{move!r} was not emitted"


def test_emitted_text_is_grounded_and_present(tmp_path) -> None:
    """The generated sub-idea text (the title and the subject) carries the new
    phrase verbatim — proof the zoom builds a concrete, grounded sub-idea."""
    rep = _integrate_engine(tmp_path).run()
    target = "the deprecation shim that keeps old callers working"
    matches = [i for i in rep.ideas if i.kind == "facet" and i.subject.endswith(target)]
    assert matches, "no facet sub-idea was built for the deprecation-shim move"
    node = matches[0]
    assert target in node.title
    assert f"facet: {target}" in node.source_facts


def test_engine_emits_a_deep_migration_l3_edit(tmp_path) -> None:
    """The zoom reaches a third level of concrete content under the migration
    moves — proof the L3 ladder is genuinely traversed, not just present."""
    labels = _emitted_facet_labels(_integrate_engine(tmp_path))
    l3_pool = {p for move in _MIGRATION_MOVES for p in _FACET_SUBASPECTS[move]}
    assert labels & l3_pool, "no migration L3 edit was emitted"


def test_migration_emission_is_deterministic(tmp_path) -> None:
    """Same project + config -> identical emitted-label set (no time/random)."""
    _integrate_project(tmp_path)
    cfg = _integrate_cfg()

    def run_once() -> set[str]:
        eng = IdeaPermutationEngine(cfg, tmp_path)
        eng.operators = [op for op in DEVELOPMENT_OPERATORS if op.name == "integrate"]
        return _emitted_facet_labels(eng)

    assert run_once() == run_once()


def test_emitted_migration_text_has_no_forbidden_token(tmp_path) -> None:
    """No emitted facet title built from a migration move carries a forbidden
    literal-metric token — the new vocabulary keeps the negative tests elsewhere
    green end-to-end. The match is case-sensitive on the literal metric token
    (``LOC``), as the canonical negative tests do, so the substring "loc" inside
    an ordinary word ("unblocks") does not spuriously trip."""
    rep = _integrate_engine(tmp_path).run()
    migration_titles = [
        i.title for i in rep.ideas
        if i.kind == "facet"
        and any(i.subject.endswith(m) for m in _MIGRATION_MOVES)
    ]
    assert migration_titles, "no migration facet titles were emitted to check"
    for title in migration_titles:
        for tok in _FORBIDDEN_TOKENS:
            assert tok not in title, f"{title!r} contains {tok!r}"


def test_value_invariant_holds_with_migration_facets(tmp_path) -> None:
    """The added vocabulary keeps every node's value in [0, 1] and roots at
    novelty 1.0."""
    rep = _integrate_engine(tmp_path).run()
    assert all(0.0 <= idea.value <= 1.0 for idea in rep.ideas)
    assert all(abs(root.novelty - 1.0) < 1e-9 for root in rep.roots())


# ---------------------------------------------------------------------------
# edge / empty paths
# ---------------------------------------------------------------------------

def test_unknown_migration_label_has_no_subaspects() -> None:
    """A label in no ladder yields nothing — the floor is the case split, handled
    by the engine, not a KeyError here."""
    assert _FACET_SUBASPECTS.get("a migration phrase that does not exist") is None


def test_migration_l3_bottoms_out_at_the_case_split() -> None:
    """Each migration L3 edit has no finer vocabulary of its own, so the zoom
    correctly falls to the universal case split one level deeper (no orphan key,
    no infinite descent)."""
    l3_pool = {p for move in _MIGRATION_MOVES for p in _FACET_SUBASPECTS[move]}
    for edit in l3_pool:
        assert edit not in _FACET_SUBASPECTS, f"{edit!r} unexpectedly has an L4 ladder"


def test_migration_vocabulary_is_deterministic_pure_data() -> None:
    """The vocabulary is a frozen module-level literal — importing it in a fresh
    interpreter yields an identical mapping (no time/random construction)."""
    import subprocess
    import sys

    code = (
        "from app.engine.idea_facets import _FACET_SUBASPECTS as s;"
        "print(s['version skew']);"
        "print(s['the staged rollout across caller cohorts'])"
    )

    def run() -> str:
        return subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout

    assert run() == run()
