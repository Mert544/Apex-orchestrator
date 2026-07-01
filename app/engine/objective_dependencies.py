"""Objective Dependency Graph — PROVEN cross-objective ordering.

The composition grammar (:mod:`app.engine.idea_composition`) records which
objective a step's success *unlocks*, but those edges are value-compounding
HEURISTICS: some are genuine hard preconditions (``dataclassify`` must land a
``@dataclass`` before ``freeze-dataclass`` has anything to freeze), while others
are mere good-taste suggestions (``modernize`` then ``sort-imports`` — but a
module's imports are sortable whether or not it was modernized). A chain that
treats every heuristic as a hard order wastes slots and, worse, can dishonestly
claim a branch is unreachable when it is not.

This module supplies the DELTA the chain/goal orchestrators consume: a
deterministically-PROVEN dependency graph. It asserts an edge ``B depends on A``
only when a two-part causal probe holds:

  1. **Zero-moves under absence.** In a synthetic project state where ``A`` has
     landed NOTHING, objective ``B`` yields ZERO moves (its precondition is
     genuinely unmet).
  2. **Non-zero under presence (the SECONDARY causal probe).** In the SAME
     project after ``A``'s kind of change is present, ``B`` DOES yield a move.

Both together are what upgrade "``B`` happens to be empty" into "``B`` is empty
*because* ``A`` has not landed" — real causality, not correlation. The move
oracle is :func:`app.engine.objective_compiler.compile_objective` run as a dry
run (``apply=False``: it lists the moves it WOULD make, no writes, no suite), so
the proof reuses the exact engine a real campaign uses.

**Conservative by construction.** A false edge only wastes one ordering slot, so
over-approximation is acceptable; a false *independence* claim would let a chain
skip a truly-required predecessor, so it is forbidden. Therefore an edge is
asserted ONLY when its probe proves BOTH halves — if causality can't be shown
(``B`` yields a move even under ``A``'s absence, or stays empty even under ``A``'s
presence), the edge is NOT asserted (honest silence, never a guessed order).

The queryable graph (:func:`depends_on` / :func:`topological_sort` /
:func:`disclose`) reads a FROZEN, pre-proven edge set — pure, deterministic,
offline, zero-token, no clock/random. Every asserted edge additionally carries
the executable :class:`Probe` that proves it, so :func:`reprove_edges` re-runs the
causal proof on demand (the tests use it as a drift guard: if an engine change
ever breaks a proof, the graph is caught lying). Adding a newly-provable edge is
one appended candidate — never a hand-tuned order.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import tempfile

__all__ = [
    "Edge",
    "Probe",
    "PROVEN_EDGES",
    "depends_on",
    "dependency_edges",
    "topological_sort",
    "find_cycle",
    "disclose",
    "prove_edge",
    "reprove_edges",
    "unproven_candidates",
]


# --- the proven graph --------------------------------------------------------

@dataclass(frozen=True)
class Edge:
    """One PROVEN dependency: ``dependent`` cannot make progress until
    ``prerequisite`` has landed its kind of change.

    ``rationale`` is the human disclosure ("a @dataclass must exist to freeze");
    ``probe`` is the executable causal proof (:class:`Probe`) — every asserted
    edge is re-runnable, so the graph can never silently drift from its proof."""
    dependent: str
    prerequisite: str
    rationale: str
    probe: "Probe"


@dataclass(frozen=True)
class Probe:
    """A deterministic causal probe for a candidate edge ``dependent →
    prerequisite``.

    ``absent_files`` returns the ``{rel: source}`` of a synthetic project where
    the prerequisite has landed NOTHING; ``present_files`` returns the same
    project after the prerequisite's kind of change IS present. The edge is
    proven iff ``dependent`` yields ZERO moves on ``absent_files`` and a NON-ZERO
    number on ``present_files`` (see :func:`prove_edge`). Both builders are pure
    (no clock/random), so the proof is reproducible."""
    dependent: str
    prerequisite: str
    absent_files: Callable[[], dict[str, str]]
    present_files: Callable[[], dict[str, str]]


# A synthetic package with a plain, NON-PUBLIC boilerplate-``__init__`` class:
# ``dataclassify`` has an obvious move here (convert it to ``@dataclass``), while
# ``freeze-dataclass`` has nothing to freeze — no ``@dataclass`` exists yet.
_PLAIN_DATACLASS_ABSENT: dict[str, str] = {
    "pkg/__init__.py": "",
    "pkg/models.py": (
        "class _Point:\n"
        "    def __init__(self, x, y):\n"
        "        self.x = x\n"
        "        self.y = y\n"
    ),
}

# The SAME package after ``dataclassify``'s kind of change has landed: the class
# is now a NON-PUBLIC, never-mutated ``@dataclass`` — exactly the shape
# ``freeze-dataclass`` acts on (it adds ``frozen=True``). Proving the SECONDARY
# half: ``freeze-dataclass`` goes from zero moves to a real move purely because a
# ``@dataclass`` is now present.
_PLAIN_DATACLASS_PRESENT: dict[str, str] = {
    "pkg/__init__.py": "",
    "pkg/models.py": (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\n"
        "class _Point:\n"
        "    x: int\n"
        "    y: int\n"
    ),
}


_FREEZE_NEEDS_DATACLASS = Probe(
    dependent="freeze-dataclass",
    prerequisite="dataclassify",
    absent_files=lambda: dict(_PLAIN_DATACLASS_ABSENT),
    present_files=lambda: dict(_PLAIN_DATACLASS_PRESENT),
)


# The frozen, insertion-ordered set of PROVEN dependency edges. Each is backed by
# ``.probe`` (re-run by :func:`reprove_edges`), so this is not a hand-tuned order:
# it is exactly the set whose causality the probe machinery confirms. APPEND-ONLY
# in spirit — a newly-provable dependency is one more entry.
PROVEN_EDGES: tuple[Edge, ...] = (
    Edge(
        dependent="freeze-dataclass",
        prerequisite="dataclassify",
        rationale="a @dataclass must exist before frozen=True can be added",
        probe=_FREEZE_NEEDS_DATACLASS,
    ),
)


# Candidate probes that are NOT asserted as edges — kept so a test can confirm the
# CONSERVATIVE discipline: their probe must REFUSE (the dependent yields a move
# even under the prerequisite's absence), so asserting the edge would be a false
# dependency. ``modernize → sort-imports`` is the canonical case: the composition
# grammar suggests it for value, but a module's imports are sortable whether or
# not it was modernized, so it is honestly NOT a hard dependency.
_SORT_IMPORTS_ABSENT: dict[str, str] = {
    "pkg/__init__.py": "",
    # An unsorted import block with NO modernize-able debt (no ``== None``, no
    # dead f-string, no ``dict()`` literal): ``sort-imports`` still has a move,
    # ``modernize`` has none — so sort-imports does not depend on modernize.
    "pkg/util.py": (
        "import sys\n"
        "import os\n\n\n"
        "def use(x):\n"
        "    return os.getpid() + sys.maxsize + x\n"
    ),
}

_SORT_NOT_AFTER_MODERNIZE = Probe(
    dependent="sort-imports",
    prerequisite="modernize",
    absent_files=lambda: dict(_SORT_IMPORTS_ABSENT),
    present_files=lambda: dict(_SORT_IMPORTS_ABSENT),
)


# The candidate edges the graph deliberately does NOT assert (independence the
# probe REFUTES a dependency for). Exposed so the conservative-correctness test
# can prove each one really is independent.
_REFUTED_CANDIDATES: tuple[Probe, ...] = (
    _SORT_NOT_AFTER_MODERNIZE,
)


def unproven_candidates() -> tuple[Probe, ...]:
    """The candidate probes the graph deliberately leaves UNASSERTED — each is a
    dependency the causal probe refutes (the dependent still moves under the
    prerequisite's absence). Exposed for the conservative-correctness test."""
    return _REFUTED_CANDIDATES


# --- causal proof engine -----------------------------------------------------

def _moves_count(objective: str, files: dict[str, str]) -> int:
    """How many moves ``objective`` yields on a throwaway project laid out from
    ``files`` — the dry-run move oracle.

    Reuses :func:`app.engine.objective_compiler.compile_objective` with
    ``apply=False`` (it lists the moves it WOULD make: no writes, no suite run),
    so the proof exercises the SAME candidate-generation the real campaign uses.
    The project is materialized in a fresh temp dir (with a minimal
    ``pyproject.toml`` so it reads as a real package) and torn down after — the
    only IO the proof performs, and it never touches the caller's tree."""
    from app.engine.objective_compiler import compile_objective

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "pyproject.toml").write_text(
            "[project]\nname='probe'\nversion='0'\n", encoding="utf-8")
        for rel, source in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        result = compile_objective(str(root), objective=objective,
                                   apply=False, verify=False)
        return len(result.steps)


def prove_edge(probe: Probe) -> bool:
    """Deterministically PROVE the candidate edge the probe describes.

    Returns ``True`` iff BOTH causal halves hold: the ``dependent`` yields ZERO
    moves under the prerequisite's ABSENCE (its precondition is genuinely unmet)
    AND a NON-ZERO number under the prerequisite's PRESENCE (the secondary probe:
    the dependent moves purely BECAUSE the prerequisite's change is now present).

    Conservative: a dependent that moves even under absence (no zero-floor) means
    the dependency is NOT real, so ``False`` — the edge is never asserted on a
    correlation. Likewise a dependent that stays empty even under presence proves
    no causal link. Same fixtures in ⇒ same verdict out (deterministic)."""
    absent = _moves_count(probe.dependent, probe.absent_files())
    if absent != 0:
        return False  # dependent already moves without the prerequisite — no edge
    present = _moves_count(probe.dependent, probe.present_files())
    return present > 0


def reprove_edges(edges: tuple[Edge, ...] = PROVEN_EDGES) -> dict[str, bool]:
    """Re-run the causal proof for every asserted edge, keyed
    ``"dependent<-prerequisite"``.

    The graph's drift guard: an asserted edge whose probe no longer holds (an
    engine change silently removed the causality) maps to ``False`` here, so the
    tests catch a graph that has started lying. Deterministic; edges are proven in
    their frozen insertion order."""
    return {
        f"{edge.dependent}<-{edge.prerequisite}": prove_edge(edge.probe)
        for edge in edges
    }


# --- queryable graph (pure: no IO / clock / random) --------------------------

def dependency_edges() -> tuple[tuple[str, str], ...]:
    """Every proven ``(dependent, prerequisite)`` pair, in frozen insertion order
    — the graph as plain tuples for a consumer that wants the raw edges."""
    return tuple((edge.dependent, edge.prerequisite) for edge in PROVEN_EDGES)


def depends_on(objective: str) -> set[str]:
    """The set of objectives that must land BEFORE ``objective`` — its direct,
    proven prerequisites.

    A pure read of the frozen proven graph (no probe run, no IO), so it is safe to
    call in a tight ordering loop. An objective with no proven predecessor returns
    an empty set (honest: no dependency is *claimed* unless it was proven)."""
    return {edge.prerequisite for edge in PROVEN_EDGES
            if edge.dependent == objective}


def _relevant_prereqs(objective: str, universe: set[str]) -> set[str]:
    """``objective``'s proven prerequisites, restricted to ``universe`` — the
    edges that constrain ordering WITHIN the set being sorted (a prerequisite not
    in the set imposes no local constraint)."""
    return depends_on(objective) & universe


def find_cycle(objectives: list[str]) -> list[str] | None:
    """Honestly report a dependency CYCLE among ``objectives`` (restricted to the
    proven edges within the set), or ``None`` when the sub-graph is acyclic.

    Returns the objectives left unresolved once every dependency-free node has
    been peeled away (Kahn's residue) — the members caught in a cycle — in stable
    input order. This is the honest disclosure a chain uses instead of crashing:
    the current proven graph is acyclic, so this returns ``None``, but a future
    edge that introduced a cycle would surface here rather than hang a topo sort.
    Deterministic; input order is preserved."""
    universe = set(objectives)
    resolved: set[str] = set()
    remaining = list(objectives)
    progressed = True
    while progressed:
        progressed = False
        for name in list(remaining):
            if _relevant_prereqs(name, universe) <= resolved:
                resolved.add(name)
                remaining.remove(name)
                progressed = True
    return remaining or None


def topological_sort(objectives: list[str]) -> list[str]:
    """A STABLE, deterministic topological order of ``objectives`` under the
    proven dependency graph: every objective appears AFTER each of its proven
    prerequisites that is also in the set.

    Stable Kahn's algorithm: among the nodes whose prerequisites are all already
    emitted, the one earliest in the INPUT order is emitted next — so an objective
    with no dependency keeps its original position relative to its independent
    peers (a fresh, edge-free list is returned unchanged). Duplicates are
    collapsed to their first occurrence.

    NEVER crashes on a cycle (honest degradation): if a set of objectives is
    caught in a dependency cycle, none can be cleanly ordered, so they are
    appended at the END in stable input order and :func:`find_cycle` reports them.
    A caller that needs to react to the cycle asks :func:`find_cycle`
    explicitly. Deterministic: same list in ⇒ same order out."""
    universe = set(objectives)
    ordered: list[str] = []
    emitted: set[str] = set()
    # De-duplicate while preserving first-seen order — the stable input sequence.
    pending: list[str] = []
    for name in objectives:
        if name not in pending:
            pending.append(name)
    while pending:
        ready = [n for n in pending
                 if _relevant_prereqs(n, universe) <= emitted]
        if not ready:
            # A cycle: no node's prerequisites are all satisfied. Emit the
            # remainder in stable input order rather than loop forever (honest).
            ordered.extend(pending)
            break
        nxt = ready[0]  # earliest in the (stable) pending order
        ordered.append(nxt)
        emitted.add(nxt)
        pending.remove(nxt)
    return ordered


def disclose(objective: str, landed: set[str] | None = None) -> list[str]:
    """Honest, human-readable disclosures of ``objective``'s proven dependencies.

    One line per proven prerequisite, e.g. ``"freeze-dataclass depends on
    dataclassify (not yet landed)"``. ``landed`` (the objectives whose change is
    already present) tunes the parenthetical: a prerequisite in ``landed`` reads
    ``(already landed)``, otherwise ``(not yet landed)`` — so a chain can show
    honestly WHY a branch is still blocked. With ``landed=None`` every
    prerequisite reads ``(not yet landed)``. Sorted for a deterministic report;
    an objective with no proven prerequisite yields an empty list."""
    done = landed or set()
    lines: list[str] = []
    for prereq in sorted(depends_on(objective)):
        state = "already landed" if prereq in done else "not yet landed"
        lines.append(f"{objective} depends on {prereq} ({state})")
    return lines
