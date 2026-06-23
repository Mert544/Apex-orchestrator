"""Landability-aware idea ranking (``landability_aware``, default off).

When the opt-in flag is on, ``IdeaPermutationEngine`` lifts the value of any idea
whose subject MODULE a verifiable concrete change can land on (proven by the
cheap/pure ``idea_synthesis_signals``), so a landable contribution outranks a
pure-analysis idea on the same budget. Off by default → ``_landable_subjects``
empty → the bonus is 0.0 for every node, so existing idea sets are byte-identical.

These tests pin:
  (a) flag OFF → byte-identical run on a project with no landable subject;
  (b) flag ON + a landable subject → an equal-blend node on it scores EXACTLY
      ``+0.08`` over a sibling on a non-landable subject (and clamps at 1.0);
  (c) a pair / abstract subject earns nothing even when the flag is on;
  (d) the ``_landability_bonus`` unit (empty → 0, member → 0.08, and both the
      ``mod.py::Class.f`` symbol form and the ``mod.py :: phrase`` facet form
      reduce to ``mod.py``);
  (e) ``_scan_landable_subjects`` is best-effort: empty on any raise / flag off.
"""

from pathlib import Path

import pytest

from app.engine.idea_permutation import (
    IdeaPermutationEngine,
    _landability_bonus,
)
from app.models.idea import IdeaNode
from app.skills.relevance_scorer import RelevanceScorer


def _node(**kw) -> IdeaNode:
    """A minimal permutation-y node, overridable per test (mirrors the deep-
    mutation suite's helper so the base blend is the same known quantity)."""
    base = dict(id="x", title="T", subject="app/foo.py", operator="harden",
                operator_chain=["harden"], depth=1, feasibility=0.5,
                relevance=1.0, kind="permutation")
    base.update(kw)
    return IdeaNode(**base)


def _scored_engine(tmp_path: Path, *, landability_aware: bool = False,
                   landable: frozenset[str] | None = None) -> IdeaPermutationEngine:
    """An engine wired just enough to drive ``_score`` directly: no learning
    memory, fresh per-run novelty counters, and the landable set pre-seeded
    (the ``_begin_run`` scan is exercised separately in test (e))."""
    eng = IdeaPermutationEngine(
        {"landability_aware": landability_aware} if landability_aware else {},
        tmp_path,
    )
    eng._has_objective = False
    eng._memory = None
    eng._chain_counts = {}
    eng._subject_counts = {}
    if landable is not None:
        eng._landable_subjects = landable
    return eng


def _build_no_landable_project(tmp: Path) -> None:
    """A small project whose modules carry NO landable synthesis opportunity:
    fully-annotated, idiomatic, no fillable stub, no convertible dataclass."""
    (tmp / "app").mkdir()
    (tmp / "app" / "util.py").write_text(
        "def util() -> int:\n"
        "    return 2\n"
    )
    (tmp / "app" / "other.py").write_text(
        "def other(x: int) -> int:\n"
        "    return x + 1\n"
    )


# --- (a) flag OFF → byte-identical run --------------------------------------


def test_landability_off_is_byte_identical(tmp_path):
    # The flag defaults off, so a run with it explicitly off must produce the
    # EXACT same report as a plain run on the same project — no value shifts.
    _build_no_landable_project(tmp_path)
    cfg = {"max_total_ideas": 20, "max_idea_depth": 2, "breadth": 3}
    plain = IdeaPermutationEngine(cfg, tmp_path).run()
    off = IdeaPermutationEngine(
        {**cfg, "landability_aware": False}, tmp_path
    ).run()
    assert plain.model_dump() == off.model_dump()


def test_landability_off_leaves_landable_set_empty(tmp_path):
    # With the flag off, _begin_run must NOT run the scan: the set stays the
    # empty frozenset, so _landability_bonus short-circuits to 0.0 everywhere.
    _build_no_landable_project(tmp_path)
    eng = IdeaPermutationEngine({"max_total_ideas": 8}, tmp_path)
    eng.run()
    assert eng._landable_subjects == frozenset()


# --- (b) flag ON → a landable subject scores exactly +0.08 ------------------


def test_landable_subject_scores_flat_bonus_over_sibling(tmp_path):
    # Two equal-blend nodes differing ONLY in subject: the one on a landable
    # module gets a flat +0.08, the other gets nothing. Base (no-objective,
    # depth 1, feas 0.5, first-seen subject) = 0.74 -> 0.82 vs 0.74.
    eng = _scored_engine(tmp_path, landable=frozenset({"app/foo.py"}))

    landable = _node(subject="app/foo.py")
    eng._score(landable, RelevanceScorer(""))

    eng._chain_counts = {}
    eng._subject_counts = {}
    plain = _node(subject="app/bar.py")
    eng._score(plain, RelevanceScorer(""))

    assert plain.value == pytest.approx(0.74)
    assert landable.value == pytest.approx(0.82)
    assert landable.value - plain.value == pytest.approx(0.08)


def test_landability_bonus_clamps_at_one(tmp_path):
    # A node whose blend already maxes at 1.0 (root-like inputs) plus the +0.08
    # landability bonus would reach 1.08 without the min(1.0, ...) clamp.
    eng = _scored_engine(tmp_path, landable=frozenset({"app/foo.py"}))
    n = _node(subject="app/foo.py", depth=0, feasibility=1.0, relevance=1.0)
    eng._score(n, RelevanceScorer(""))
    assert n.value == 1.0


def test_landability_bonus_applies_at_depth(tmp_path):
    # The bonus is NOT gated on root: a deep permutation child inheriting its
    # root's landable subject is lifted too. Depth-3 child vs an identical
    # non-landable sibling: same base blend, +0.08 only on the landable one.
    eng = _scored_engine(tmp_path, landable=frozenset({"app/foo.py"}))

    deep = _node(subject="app/foo.py", depth=3,
                 operator_chain=["harden", "test", "simplify"])
    eng._score(deep, RelevanceScorer(""))

    eng._chain_counts = {}
    eng._subject_counts = {}
    sibling = _node(subject="app/bar.py", depth=3,
                    operator_chain=["harden", "test", "simplify"])
    eng._score(sibling, RelevanceScorer(""))

    assert deep.value - sibling.value == pytest.approx(0.08)


# --- (c) pair / abstract subjects earn nothing ------------------------------


def test_pair_and_abstract_subjects_earn_no_bonus(tmp_path):
    # A module-PAIR subject (A <-> B) and an ABSTRACT subject ("CI pipeline")
    # name no single .py module, so neither matches the landable set even with
    # the flag on — they score exactly as without any bonus.
    eng = _scored_engine(tmp_path, landable=frozenset({"app/foo.py"}))

    pair = _node(subject="app/foo.py <-> app/bar.py", operator="decouple",
                 operator_chain=["decouple"], kind="pair")
    eng._score(pair, RelevanceScorer(""))

    eng._chain_counts = {}
    eng._subject_counts = {}
    abstract = _node(subject="CI pipeline", operator="observe",
                     operator_chain=["observe"], kind="synthesis")
    eng._score(abstract, RelevanceScorer(""))

    # Same base blend (depth 1, feas 0.5, first-seen subject) and NO bonus.
    assert pair.value == pytest.approx(0.74)
    assert abstract.value == pytest.approx(0.74)


# --- (d) _landability_bonus unit --------------------------------------------


def test_landability_bonus_empty_set_is_zero():
    # The off-by-default case: an empty landable set short-circuits to 0.0 even
    # for a node whose subject would otherwise match.
    assert _landability_bonus(_node(subject="app/foo.py"), frozenset()) == 0.0


def test_landability_bonus_member_is_cap():
    assert _landability_bonus(
        _node(subject="app/foo.py"), frozenset({"app/foo.py"})
    ) == 0.08


def test_landability_bonus_non_member_is_zero():
    assert _landability_bonus(
        _node(subject="app/foo.py"), frozenset({"app/bar.py"})
    ) == 0.0


def test_landability_bonus_reduces_symbol_subject_to_module():
    # A symbol-granular subject ("mod.py::Class.f") reduces to its module so a
    # function-level idea on a landable module is still lifted.
    assert _landability_bonus(
        _node(subject="app/foo.py::Widget.render"), frozenset({"app/foo.py"})
    ) == 0.08


def test_landability_bonus_reduces_facet_subject_to_module():
    # A facet subject ("mod.py :: phrase") reduces to its leaf module too, so a
    # facet under a landable leaf inherits the bonus.
    assert _landability_bonus(
        _node(subject="app/foo.py :: error handling", kind="facet"),
        frozenset({"app/foo.py"}),
    ) == 0.08


# --- (e) _scan_landable_subjects is best-effort -----------------------------


def test_scan_landable_subjects_empty_when_flag_off(tmp_path):
    # Direct call honors the flag-off contract via _begin_run: the run never
    # populates the set. (Covered functionally by the byte-identical test; this
    # asserts the scan's own empty default on a no-landable project.)
    _build_no_landable_project(tmp_path)
    eng = IdeaPermutationEngine({"landability_aware": True}, tmp_path)
    profile = eng.profiler.profile()
    # No module here carries a landable synthesis opportunity.
    assert eng._scan_landable_subjects(profile) == frozenset()


def test_scan_landable_subjects_swallows_errors(tmp_path, monkeypatch):
    # Best-effort: if a synthesis signal raises, the scan yields the empty set
    # rather than perturbing the run. Force one signal to blow up.
    eng = IdeaPermutationEngine({"landability_aware": True}, tmp_path)

    class _Boom:
        def __getattr__(self, _name):
            def _raise(*_a, **_k):
                raise RuntimeError("boom")
            return _raise

    import app.engine.idea_synthesis_signals as real_sigs  # noqa: F401
    monkeypatch.setitem(
        __import__("sys").modules, "app.engine.idea_synthesis_signals", _Boom()
    )

    class _Profile:
        module_to_tests = {"app/foo.py": []}

    assert eng._scan_landable_subjects(_Profile()) == frozenset()


def test_scan_landable_subjects_empty_on_no_candidates(tmp_path):
    # No .py modules anywhere on the profile -> no candidates -> empty set,
    # without even importing the signals.
    eng = IdeaPermutationEngine({"landability_aware": True}, tmp_path)

    class _Empty:
        module_to_tests: dict = {}

    assert eng._scan_landable_subjects(_Empty()) == frozenset()


def test_landable_candidates_unions_module_lists_and_caps():
    # The candidate set unions module_to_tests keys with the module-valued
    # lists, keeps only .py paths, sorts, and caps at the limit.
    class _Profile:
        module_to_tests = {"app/z.py": [], "tests/test_z.py": []}
        untested_modules = ["app/a.py", "docs/readme.md"]
        modernizable_modules = ["app/a.py"]  # dup folds away
        module_fanin = {"app/m.py": 3}

    cands = IdeaPermutationEngine._landable_candidates(_Profile())
    assert cands == ["app/a.py", "app/m.py", "app/z.py", "tests/test_z.py"]
    assert all(c.endswith(".py") for c in cands)


def test_scan_landable_subjects_finds_real_landable_module(tmp_path):
    # End-to-end (flag on): a module with a PROVABLE return-type hint the
    # infer-type-hints lander would land must appear in the scanned set.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "inferable.py").write_text(
        "def f():\n"
        "    return 1\n"
    )
    eng = IdeaPermutationEngine({"landability_aware": True}, tmp_path)
    profile = eng.profiler.profile()
    landable = eng._scan_landable_subjects(profile)
    assert "app/inferable.py" in landable
