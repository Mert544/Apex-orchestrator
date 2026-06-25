"""Landability-aware idea ranking (``landability_aware``, default off).

When the opt-in flag is on, ``IdeaPermutationEngine`` lifts the value of any idea
whose subject MODULE a verifiable concrete change can land on (proven by the
honest ``idea_synthesis_signals``), so a landable contribution outranks a
pure-analysis idea on the same budget. The lift is now GRADED by the BUYER VALUE
of the move that would land (the shared ``move_value`` table): a stub-landable
module earns the full ``_LANDABILITY_CAP``, a sort-landable one a fraction — so a
high-value concrete contribution outranks a low-value one (the binary→graded
upgrade). Off by default → ``_landable_subjects`` empty → the bonus is 0.0 for
every node, so existing idea sets are byte-identical.

These tests pin:
  (a) flag OFF → byte-identical run on a project with no landable subject;
  (b) flag ON + a landable subject → the bonus is GRADED by ``move_value``: a
      stub subject (value 1.0) scores ``+0.08``, a sort subject (0.18) ``≈+0.014``,
      and the stub idea outranks the sort idea (and clamps at 1.0);
  (c) a pair / abstract subject earns nothing even when the flag is on;
  (d) the ``_landability_bonus`` unit (empty → 0, graded by value, and both the
      ``mod.py::Class.f`` symbol form and the ``mod.py :: phrase`` facet form
      reduce to ``mod.py``);
  (e) ``_scan_landable_subjects`` is best-effort: empty on any raise / flag off;
  (f) the DEEP cost tier surfaces the high-value suite-cost signals only when
      ``landability_deep`` is on, and the per-subject value equals
      ``move_value(<objective's operator>)`` — proving Layers (a) and (b) share
      one value model.
"""

from pathlib import Path

import pytest

from app.engine.idea_permutation import (
    IdeaPermutationEngine,
    _facet_landable_bonus,
    _landability_bonus,
)
from app.engine.move_value import move_value
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
                   landable: dict[str, float] | None = None) -> IdeaPermutationEngine:
    """An engine wired just enough to drive ``_score`` directly: no learning
    memory, fresh per-run novelty counters, and the landable mapping pre-seeded
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
    # With the flag off, _begin_run must NOT run the scan: the mapping stays the
    # empty dict, so _landability_bonus short-circuits to 0.0 everywhere.
    _build_no_landable_project(tmp_path)
    eng = IdeaPermutationEngine({"max_total_ideas": 8}, tmp_path)
    eng.run()
    assert eng._landable_subjects == {}


# --- (b) flag ON → a landable subject scores a GRADED bonus -----------------


def test_landable_subject_scores_graded_bonus_over_sibling(tmp_path):
    # Two equal-blend nodes differing ONLY in subject: the one on a STUB-landable
    # module (value 1.0) gets the full +0.08, the other gets nothing. Base
    # (no-objective, depth 1, feas 0.5, first-seen subject) = 0.74 -> 0.82 vs 0.74.
    eng = _scored_engine(tmp_path, landable={"app/foo.py": move_value("implement_stub")})

    landable = _node(subject="app/foo.py")
    eng._score(landable, RelevanceScorer(""))

    eng._chain_counts = {}
    eng._subject_counts = {}
    plain = _node(subject="app/bar.py")
    eng._score(plain, RelevanceScorer(""))

    assert plain.value == pytest.approx(0.74)
    assert landable.value == pytest.approx(0.82)
    assert landable.value - plain.value == pytest.approx(0.08)


def test_landability_bonus_is_graded_by_move_value(tmp_path):
    # The binary→graded upgrade: a STUB-landable subject (value 1.0) earns the
    # full 0.08; a SORT-landable subject (value 0.18) earns ≈0.0144; the stub idea
    # outranks the sort idea. Both share the one move_value table.
    stub_v = move_value("implement_stub")
    sort_v = move_value("sort_imports")
    eng = _scored_engine(tmp_path, landable={"app/stub.py": stub_v, "app/sort.py": sort_v})

    stub = _node(subject="app/stub.py")
    eng._score(stub, RelevanceScorer(""))
    eng._chain_counts = {}
    eng._subject_counts = {}
    sortn = _node(subject="app/sort.py")
    eng._score(sortn, RelevanceScorer(""))

    assert stub.value - 0.74 == pytest.approx(0.08)
    assert sortn.value - 0.74 == pytest.approx(round(0.08 * sort_v, 4))
    assert stub.value > sortn.value


def test_landability_bonus_clamps_at_one(tmp_path):
    # A node whose blend already maxes at 1.0 (root-like inputs) plus the +0.08
    # landability bonus would reach 1.08 without the min(1.0, ...) clamp.
    eng = _scored_engine(tmp_path, landable={"app/foo.py": move_value("implement_stub")})
    n = _node(subject="app/foo.py", depth=0, feasibility=1.0, relevance=1.0)
    eng._score(n, RelevanceScorer(""))
    assert n.value == 1.0


def test_landability_bonus_applies_at_depth(tmp_path):
    # The bonus is NOT gated on root: a deep permutation child inheriting its
    # root's landable subject is lifted too. Depth-3 child vs an identical
    # non-landable sibling: same base blend, +0.08 only on the landable one.
    eng = _scored_engine(tmp_path, landable={"app/foo.py": move_value("implement_stub")})

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
    # name no single .py module, so neither matches the landable mapping even with
    # the flag on — they score exactly as without any bonus.
    eng = _scored_engine(tmp_path, landable={"app/foo.py": move_value("implement_stub")})

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


def test_landability_bonus_empty_mapping_is_zero():
    # The off-by-default case: an empty landable mapping short-circuits to 0.0
    # even for a node whose subject would otherwise match.
    assert _landability_bonus(_node(subject="app/foo.py"), {}) == 0.0


def test_landability_bonus_member_is_graded_cap():
    # A value-1.0 (stub) subject earns the full cap; a value-0.18 (sort) a fraction.
    assert _landability_bonus(
        _node(subject="app/foo.py"), {"app/foo.py": 1.0}
    ) == 0.08
    assert _landability_bonus(
        _node(subject="app/foo.py"), {"app/foo.py": 0.18}
    ) == round(0.08 * 0.18, 4)


def test_landability_bonus_non_member_is_zero():
    assert _landability_bonus(
        _node(subject="app/foo.py"), {"app/bar.py": 1.0}
    ) == 0.0


def test_landability_bonus_reduces_symbol_subject_to_module():
    # A symbol-granular subject ("mod.py::Class.f") reduces to its module so a
    # function-level idea on a landable module is still lifted.
    assert _landability_bonus(
        _node(subject="app/foo.py::Widget.render"), {"app/foo.py": 1.0}
    ) == 0.08


def test_landability_bonus_reduces_facet_subject_to_module():
    # A facet subject ("mod.py :: phrase") reduces to its leaf module too, so a
    # facet under a landable leaf inherits the bonus.
    assert _landability_bonus(
        _node(subject="app/foo.py :: error handling", kind="facet"),
        {"app/foo.py": 1.0},
    ) == 0.08


# --- (e) _scan_landable_subjects is best-effort -----------------------------


def test_scan_landable_subjects_empty_when_flag_off(tmp_path):
    # Direct call honors the flag-off contract via _begin_run: the run never
    # populates the mapping. (Covered functionally by the byte-identical test;
    # this asserts the scan's own empty default on a no-landable project.)
    _build_no_landable_project(tmp_path)
    eng = IdeaPermutationEngine({"landability_aware": True}, tmp_path)
    profile = eng.profiler.profile()
    # No module here carries a landable synthesis opportunity.
    assert eng._scan_landable_subjects(profile) == {}


def test_scan_landable_subjects_swallows_errors(tmp_path, monkeypatch):
    # Best-effort: if a synthesis signal raises, the scan yields the empty mapping
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

    assert eng._scan_landable_subjects(_Profile()) == {}


def test_scan_landable_subjects_empty_on_no_candidates(tmp_path):
    # No .py modules anywhere on the profile -> no candidates -> empty mapping,
    # without even importing the signals.
    eng = IdeaPermutationEngine({"landability_aware": True}, tmp_path)

    class _Empty:
        module_to_tests: dict = {}

    assert eng._scan_landable_subjects(_Empty()) == {}


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
    # infer-type-hints lander would land must appear in the scanned mapping, with
    # the value of its move (infer_type_hints).
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "inferable.py").write_text(
        "def f():\n"
        "    return 1\n"
    )
    eng = IdeaPermutationEngine({"landability_aware": True}, tmp_path)
    profile = eng.profiler.profile()
    landable = eng._scan_landable_subjects(profile)
    assert "app/inferable.py" in landable
    assert landable["app/inferable.py"] == move_value("infer_type_hints")


# --- (f) the DEEP cost tier + shared value model ----------------------------


def test_deep_scan_gates_high_value_signals(tmp_path):
    # An UNTESTED module carries a cover-gaps opportunity (a suite-cost signal):
    # it appears in the mapping ONLY with landability_deep on, and at the cover_gaps
    # value. Without deep, the cheap tier alone yields nothing for it.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "untested.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")

    shallow = IdeaPermutationEngine({"landability_aware": True}, tmp_path)
    shallow_map = shallow._scan_landable_subjects(shallow.profiler.profile())

    deep = IdeaPermutationEngine(
        {"landability_aware": True, "landability_deep": True}, tmp_path)
    deep_map = deep._scan_landable_subjects(deep.profiler.profile())

    assert "app/untested.py" not in shallow_map  # cover-gaps is a deep-tier signal
    assert deep_map.get("app/untested.py") == move_value("cover_gaps")


def test_landability_values_share_move_value_table(tmp_path):
    # The per-subject value the scan records IS move_value(<objective's operator>),
    # proving Layers (a) and (b) use one value model — checked on the cheap
    # inferable signal (no suite cost).
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "inferable.py").write_text(
        "def f():\n    return 1\n")
    eng = IdeaPermutationEngine({"landability_aware": True}, tmp_path)
    landable = eng._scan_landable_subjects(eng.profiler.profile())
    assert landable["app/inferable.py"] == move_value("infer_type_hints")


# --- (g) value-aware facet zoom (a.3) ---------------------------------------


def test_facet_landable_lift_grades_by_objective_value():
    # A facet phrase naming a Tier-1 contribution earns the full cap; a phrase
    # naming a low-value tidy a fraction; a phrase routing to nothing earns 0.0.
    tier1 = _node(kind="facet", subject="app/foo.py :: x",
                  source_facts=["facet: the function the red test calls"])
    assert _facet_landable_bonus(tier1) == round(0.08 * move_value("tdd_implement"), 4)

    tidy = _node(kind="facet", subject="app/foo.py :: x",
                 source_facts=["facet: an unsorted import block"])
    assert _facet_landable_bonus(tidy) == round(0.08 * move_value("sort_imports"), 4)

    nowhere = _node(kind="facet", subject="app/foo.py :: x",
                    source_facts=["facet: some generic case split"])
    assert _facet_landable_bonus(nowhere) == 0.0

    # No facet: source fact (off-by-construction for a non-facet) → 0.0.
    assert _facet_landable_bonus(_node(source_facts=[])) == 0.0


def test_facet_landable_lift_drills_to_concrete(tmp_path):
    # A leaf facet whose phrase routes to a Tier-1 objective outranks a sibling
    # case-split facet that routes to nothing — so the value spike selects it.
    eng = _scored_engine(tmp_path, landability_aware=True, landable={})

    concrete = _node(kind="facet", subject="app/foo.py :: x", operator="test",
                     operator_chain=["test"],
                     source_facts=["facet: the function the red test calls"])
    eng._score(concrete, RelevanceScorer(""))

    eng._chain_counts = {}
    eng._subject_counts = {}
    casesplit = _node(kind="facet", subject="app/bar.py :: y", operator="test",
                      operator_chain=["test"],
                      source_facts=["facet: some generic case split"])
    eng._score(casesplit, RelevanceScorer(""))

    assert concrete.value > casesplit.value


def test_facet_lift_off_when_flag_off(tmp_path):
    # With landability_aware OFF, the facet lift is a no-op (byte-identical): a
    # Tier-1-routing facet scores exactly as a non-routing one.
    eng = _scored_engine(tmp_path, landability_aware=False, landable={})

    concrete = _node(kind="facet", subject="app/foo.py :: x", operator="test",
                     operator_chain=["test"],
                     source_facts=["facet: the function the red test calls"])
    eng._score(concrete, RelevanceScorer(""))

    eng._chain_counts = {}
    eng._subject_counts = {}
    casesplit = _node(kind="facet", subject="app/bar.py :: y", operator="test",
                      operator_chain=["test"],
                      source_facts=["facet: some generic case split"])
    eng._score(casesplit, RelevanceScorer(""))

    assert concrete.value == pytest.approx(casesplit.value)
