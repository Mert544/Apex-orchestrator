"""Tests for the Objective Dependency Graph — PROVEN cross-objective ordering.

``app/engine/objective_dependencies.py`` asserts an edge ``B depends on A`` ONLY
when a two-part causal probe holds: ``B`` yields ZERO moves while ``A`` has landed
nothing, and a NON-ZERO number once ``A``'s kind of change is present. These tests
pin:

  * the causal PROOF — the real ``freeze-dataclass ← dataclassify`` edge is proven
    by the zero-moves-then-nonzero probe (and the two halves each checked alone),
    reusing the ``compile_objective`` dry-run move oracle;
  * DRIFT protection — every asserted edge re-proves, and every endpoint is a real
    ``available_objectives()`` name (a renamed objective can't silently dangle);
  * ``depends_on`` / ``dependency_edges`` reading the frozen proven graph;
  * ``topological_sort`` producing a valid, STABLE, deterministic order (a
    prerequisite precedes its dependent; independent peers keep input order);
  * CYCLE honesty — a synthetic cyclic graph is REPORTED (``find_cycle``) and the
    sort degrades without crashing rather than looping forever;
  * CONSERVATIVE correctness — no asserted independence a probe refutes: the
    deliberately-unasserted ``sort-imports ← modernize`` candidate is confirmed
    independent (its dependent still moves under the prerequisite's absence);
  * determinism — the same inputs yield an identical graph / order / proof.
"""

from __future__ import annotations

from app.engine.objective_compiler import available_objectives
from app.engine.objective_dependencies import (
    PROVEN_EDGES,
    Edge,
    Probe,
    dependency_edges,
    depends_on,
    disclose,
    find_cycle,
    prove_edge,
    reprove_edges,
    topological_sort,
    unproven_candidates,
)


# --- 1. the causal PROOF (the load-bearing soundness) ------------------------

def test_the_real_edge_is_proven_zero_then_nonzero() -> None:
    """``freeze-dataclass ← dataclassify`` proves via the two-part causal probe:
    ``freeze-dataclass`` yields ZERO moves while no ``@dataclass`` exists, and a
    move once dataclassify's change is present."""
    edge = _edge("freeze-dataclass", "dataclassify")
    assert prove_edge(edge.probe) is True


def test_each_half_of_the_proof_holds_independently() -> None:
    """The proof's two halves, checked directly on the move oracle: the dependent
    is EMPTY under the prerequisite's absence and NON-EMPTY under its presence.
    This is what upgrades "empty" into "empty BECAUSE the prerequisite is absent"
    — the confirmed causality, not a correlation."""
    from app.engine.objective_dependencies import _moves_count

    probe = _edge("freeze-dataclass", "dataclassify").probe
    assert _moves_count(probe.dependent, probe.absent_files()) == 0
    assert _moves_count(probe.dependent, probe.present_files()) > 0


def test_prerequisite_itself_has_a_move_in_the_absent_state() -> None:
    """Sanity on the fixture: in the ABSENT state the PREREQUISITE (``dataclassify``)
    genuinely has work to do — so the state really is "before A landed", not an
    empty project where nobody can move."""
    from app.engine.objective_dependencies import _moves_count

    probe = _edge("freeze-dataclass", "dataclassify").probe
    assert _moves_count(probe.prerequisite, probe.absent_files()) > 0


# --- 2. DRIFT protection -----------------------------------------------------

def test_every_asserted_edge_reproves() -> None:
    """The drift guard: every edge in the frozen graph re-proves via its probe.
    An engine change that silently broke the causality would flip one of these to
    ``False`` and fail here — the graph is caught the moment it starts lying."""
    verdicts = reprove_edges()
    assert verdicts, "expected at least one proven edge"
    assert all(verdicts.values()), verdicts


def test_every_edge_endpoint_is_a_real_objective() -> None:
    """Every dependent AND prerequisite resolves to a real objective name (the
    same drift discipline the composition grammar carries) — a renamed/removed
    objective can never dangle in the graph."""
    known = set(available_objectives())
    for edge in PROVEN_EDGES:
        assert edge.dependent in known, edge.dependent
        assert edge.prerequisite in known, edge.prerequisite


def test_edges_carry_a_nonempty_human_rationale() -> None:
    """Every edge carries a human disclosure and a matching probe whose endpoints
    line up with the edge — the shape ``disclose`` / ``reprove_edges`` rely on."""
    for edge in PROVEN_EDGES:
        assert isinstance(edge, Edge)
        assert edge.rationale.strip()
        assert isinstance(edge.probe, Probe)
        assert edge.probe.dependent == edge.dependent
        assert edge.probe.prerequisite == edge.prerequisite


# --- 3. depends_on / dependency_edges (pure reads of the frozen graph) -------

def test_depends_on_returns_direct_prerequisites() -> None:
    assert depends_on("freeze-dataclass") == {"dataclassify"}


def test_depends_on_is_empty_for_a_root_objective() -> None:
    """An objective with no proven predecessor returns an empty set — honest: a
    dependency is never CLAIMED unless it was proven."""
    assert depends_on("dataclassify") == set()
    assert depends_on("modernize") == set()
    assert depends_on("an-unknown-objective") == set()


def test_dependency_edges_matches_the_frozen_graph() -> None:
    """The raw-tuple view lists exactly the proven pairs in insertion order."""
    assert dependency_edges() == tuple(
        (e.dependent, e.prerequisite) for e in PROVEN_EDGES)
    assert ("freeze-dataclass", "dataclassify") in dependency_edges()


# --- 4. topological_sort: valid / stable / deterministic ---------------------

def test_topological_sort_places_prerequisite_before_dependent() -> None:
    """The dependent lands AFTER its prerequisite regardless of input order."""
    for order in (["freeze-dataclass", "dataclassify"],
                  ["dataclassify", "freeze-dataclass"]):
        result = topological_sort(order)
        assert result.index("dataclassify") < result.index("freeze-dataclass")


def test_topological_sort_is_stable_for_independent_objectives() -> None:
    """Objectives with no dependency between them keep their INPUT order (stable
    Kahn) — a fresh, edge-free list is returned unchanged."""
    assert topological_sort(["c", "a", "b"]) == ["c", "a", "b"]
    assert topological_sort(["modernize", "sort-imports"]) == [
        "modernize", "sort-imports"]
    # ...and the reverse input keeps its own order too (no hidden re-sort).
    assert topological_sort(["sort-imports", "modernize"]) == [
        "sort-imports", "modernize"]


def test_topological_sort_preserves_independent_neighbours_around_an_edge() -> None:
    """The dependency reorders ONLY the constrained pair; independent objectives
    keep their relative input order (the stability guarantee end-to-end)."""
    result = topological_sort(
        ["freeze-dataclass", "modernize", "dataclassify", "sort-imports"])
    assert result.index("dataclassify") < result.index("freeze-dataclass")
    # modernize appeared before sort-imports in the input; unconstrained, it stays.
    assert result.index("modernize") < result.index("sort-imports")


def test_topological_sort_deduplicates_to_first_occurrence() -> None:
    """A repeated objective collapses to its first position — a total, clean
    order even on a messy input list."""
    result = topological_sort(
        ["dataclassify", "freeze-dataclass", "dataclassify"])
    assert result == ["dataclassify", "freeze-dataclass"]


def test_topological_sort_is_deterministic() -> None:
    """Same list in ⇒ identical order out (no set/dict-order leakage)."""
    board = ["freeze-dataclass", "dataclassify", "modernize", "sort-imports"]
    assert topological_sort(board) == topological_sort(list(board))


def test_topological_sort_of_empty_and_singleton() -> None:
    """Edge/empty paths: nothing to order, or a single objective, are returned
    as-is (no crash, no spurious dependency)."""
    assert topological_sort([]) == []
    assert topological_sort(["freeze-dataclass"]) == ["freeze-dataclass"]


# --- 5. CYCLE honesty (report, never crash) ----------------------------------

def _cyclic_edges() -> tuple[Edge, ...]:
    """A synthetic 2-cycle over real objective names (``a`` depends on ``b`` AND
    ``b`` depends on ``a``) built WITHOUT running any probe — used only to
    exercise the graph algorithms' cycle handling in isolation."""
    def _never() -> dict[str, str]:
        return {}

    p1 = Probe("dataclassify", "freeze-dataclass", _never, _never)
    p2 = Probe("freeze-dataclass", "dataclassify", _never, _never)
    return (
        Edge("dataclassify", "freeze-dataclass", "synthetic", p1),
        Edge("freeze-dataclass", "dataclassify", "synthetic", p2),
    )


def test_find_cycle_returns_none_on_the_real_acyclic_graph() -> None:
    """The shipped proven graph is acyclic, so ``find_cycle`` reports nothing."""
    assert find_cycle(["freeze-dataclass", "dataclassify"]) is None
    assert find_cycle(["modernize", "sort-imports"]) is None
    assert find_cycle([]) is None


def test_find_cycle_reports_a_cycle_honestly(monkeypatch) -> None:
    """With a synthetic 2-cycle patched in, ``find_cycle`` REPORTS the caught
    members (in stable input order) rather than returning ``None`` — the honest
    disclosure a chain uses to short-circuit an unreachable branch."""
    import app.engine.objective_dependencies as od

    monkeypatch.setattr(od, "PROVEN_EDGES", _cyclic_edges())
    caught = od.find_cycle(["dataclassify", "freeze-dataclass"])
    assert caught == ["dataclassify", "freeze-dataclass"]


def test_topological_sort_degrades_without_crashing_on_a_cycle(monkeypatch) -> None:
    """A cyclic graph must not hang or raise: the sort emits the cyclic remainder
    in stable input order (honest degradation) and terminates."""
    import app.engine.objective_dependencies as od

    monkeypatch.setattr(od, "PROVEN_EDGES", _cyclic_edges())
    result = od.topological_sort(["dataclassify", "freeze-dataclass"])
    assert result == ["dataclassify", "freeze-dataclass"]  # both present, no crash


def test_cycle_members_after_an_orderable_prefix(monkeypatch) -> None:
    """An objective OUTSIDE the cycle still orders cleanly and precedes the
    cyclic remainder, which is appended stably — the sort never drops a node."""
    import app.engine.objective_dependencies as od

    monkeypatch.setattr(od, "PROVEN_EDGES", _cyclic_edges())
    board = ["modernize", "dataclassify", "freeze-dataclass"]
    result = od.topological_sort(board)
    assert set(result) == set(board)  # nothing lost
    assert result[0] == "modernize"   # the unconstrained node ordered first
    assert od.find_cycle(board) == ["dataclassify", "freeze-dataclass"]


# --- 6. CONSERVATIVE correctness (no false-negative independence) ------------

def test_unasserted_candidates_are_genuinely_independent() -> None:
    """Every candidate the graph deliberately leaves UNASSERTED must have its
    probe REFUSE (the dependent still moves under the prerequisite's absence), so
    asserting the edge would be a FALSE dependency. This is the conservative
    discipline made testable: independence is only ever LEFT unclaimed, never
    claimed against a probe that would refute it."""
    candidates = unproven_candidates()
    assert candidates, "expected at least one refuted candidate to guard the rule"
    for probe in candidates:
        assert prove_edge(probe) is False, (
            f"{probe.dependent} does NOT depend on {probe.prerequisite}; "
            "the graph must not assert this edge")


def test_sort_imports_does_not_depend_on_modernize() -> None:
    """The canonical over-approximation counter-example: the composition grammar
    SUGGESTS modernize→sort-imports for value, but a module's imports are sortable
    whether or not it was modernized — so the graph asserts NO such dependency."""
    assert depends_on("sort-imports") == set()
    assert ("sort-imports", "modernize") not in dependency_edges()


def test_a_refuted_probe_yields_a_move_under_absence() -> None:
    """Directly on the move oracle: the refuted candidate's dependent
    (``sort-imports``) already has a move in the 'absent' state, which is exactly
    why the dependency is NOT real (no zero-floor to be caused by the prereq)."""
    from app.engine.objective_dependencies import _moves_count

    probe = unproven_candidates()[0]
    assert _moves_count(probe.dependent, probe.absent_files()) > 0


# --- 7. disclose (honest human report) ---------------------------------------

def test_disclose_reports_each_prerequisite() -> None:
    assert disclose("freeze-dataclass") == [
        "freeze-dataclass depends on dataclassify (not yet landed)"]


def test_disclose_marks_landed_prerequisites() -> None:
    """A prerequisite already present reads ``(already landed)`` — so a chain can
    show honestly whether a branch is still blocked."""
    assert disclose("freeze-dataclass", {"dataclassify"}) == [
        "freeze-dataclass depends on dataclassify (already landed)"]


def test_disclose_is_empty_for_a_root_objective() -> None:
    assert disclose("dataclassify") == []
    assert disclose("modernize", {"anything"}) == []


# --- 8. determinism of the graph itself --------------------------------------

def test_graph_is_identical_across_calls() -> None:
    """Same repo state ⇒ identical graph: the edges, the depends_on sets, and the
    re-proof verdicts are byte-stable across calls (no clock/random)."""
    assert dependency_edges() == dependency_edges()
    assert depends_on("freeze-dataclass") == depends_on("freeze-dataclass")
    assert reprove_edges() == reprove_edges()


# --- helpers -----------------------------------------------------------------

def _edge(dependent: str, prerequisite: str) -> Edge:
    """The single proven edge matching ``(dependent, prerequisite)``."""
    for edge in PROVEN_EDGES:
        if edge.dependent == dependent and edge.prerequisite == prerequisite:
            return edge
    raise AssertionError(f"no proven edge {dependent} <- {prerequisite}")
