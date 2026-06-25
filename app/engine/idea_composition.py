"""Composition grammar for GROUNDED IDEA CHAINS — the pure, frozen foundation.

The idea tree (``idea_permutation``) today emits a FLAT LIST of one-shot develop
moves. The generational leap (`CLAUDE.md` North Star: land more working code) is
to emit GROUNDED, PRECONDITION-LINKED, VALUE-COMPOUNDING *campaigns* — an ordered
sequence of develop objectives where each step's success UNLOCKS the next (e.g.
``cover-gaps`` THEN ``strengthen-tests``: ``strengthen-tests`` refuses a module
with no linked test, so ``cover-gaps`` is genuinely its precondition).

This module is the load-bearing first beachhead for that leap, and it is purely
ADDITIVE: it is imported by NOTHING in the running engine (only its test), so the
existing engine code paths are literally unchanged — byte-identical by
construction, the strongest possible off-by-default form (there is no flag to
toggle because there is no runtime caller). Subsequent (deferred) increments wire
it in behind a ``chain_synthesis=False`` flag with a reserved budget slice.

It exports exactly three things, the same determinism class as
``facet_develop`` / ``move_value`` (stdlib + the one frozen ``move_value`` table;
no engine import, no profile, no AST, no IO, no network, no clock, no
randomness):

  - :data:`_COMPOSITION_EDGES` — a frozen, insertion-ordered grammar mapping a
    develop objective to the ordered ``(successor, precondition_rationale)``
    pairs its success unlocks. Like ``FACET_OBJECTIVE_MAP``, it is DRIFT-TESTED:
    every key AND every successor must resolve via
    :func:`app.engine.move_value.objective_value` to a real ``OPERATOR_VALUE``
    row, so a renamed/removed objective can never silently dangle.
  - :func:`compose_chains` — a pure, deterministic, bounded, acyclic DFS over the
    grammar returning every compositional (length >= 2) ordered trail rooted at a
    start objective.
  - :func:`chain_value` — the COMPOUNDED buyer value of a trail, reusing
    ``move_value.objective_value`` with a ``0.85**i`` geometric decay (mirroring
    the permutation feasibility decay) so a long tail of low-value tidies can
    never dominate a short high-value chain.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.engine.move_value import objective_value

__all__ = [
    "compose_chains",
    "chain_value",
]


# develop objective -> the ordered ((successor, precondition_rationale), ...) its
# success UNLOCKS. INSERTION-ORDERED (deterministic enumeration) and APPEND-ONLY
# in spirit. Every key AND every successor is a REAL develop objective whose name
# resolves via move_value.objective_value to an OPERATOR_VALUE row (drift-tested):
#   implement-stub 1.0, cover-gaps 0.90, infer-type-hints 0.72, tdd-implement 1.0,
#   document-signature 0.68, strengthen-tests 0.88, dataclassify 0.50,
#   freeze-dataclass 0.45, wire-exports 0.90, generate-usage-doc 0.66,
#   modernize 0.25, sort-imports 0.18.
# Each precondition rationale is structurally sound against the named lander's own
# gate (idea_synthesis_signals): a filled body is characterization-testable and
# return-inferable; a first test can then be strengthened with a mutant-killer; a
# fresh @dataclass can be proven never-mutated and frozen; a wired surface has an
# API to document; a modernized module's imports can be tidied.
_COMPOSITION_EDGES: dict[str, tuple[tuple[str, str], ...]] = {
    "implement-stub": (
        ("cover-gaps", "a filled body is now characterization-testable"),
        ("infer-type-hints", "a filled body now has provable returns"),
    ),
    "tdd-implement": (
        ("infer-type-hints", "the written fn now has inferable return types"),
        ("document-signature", "the new public fn now has a doc-able signature"),
    ),
    "cover-gaps": (
        ("strengthen-tests", "a first test now exists to strengthen with a mutant-killer"),
    ),
    "dataclassify": (
        ("freeze-dataclass", "a @dataclass now exists to prove never-mutated and freeze"),
    ),
    "wire-exports": (
        ("generate-usage-doc", "a wired public surface now has an API to document"),
    ),
    "modernize": (
        ("sort-imports", "a modernized module's imports can now be tidied"),
    ),
}


def _walk(
    objective: str,
    why: str,
    visited: frozenset[str],
    trail: tuple[tuple[str, str], ...],
    max_len: int,
    out: list[tuple[tuple[str, str], ...]],
) -> None:
    """One small recursive DFS step over the frozen grammar (cc well under 12).

    Appends ``(objective, why)`` to ``trail``; records the trail when it is a
    genuine composition (length >= 2 — the length-1 self-trail is excluded so the
    product is always compositional); then visits each successor in INSERTION
    order, recursing only when the successor is unvisited (acyclicity) and the
    depth cap leaves room. ``visited`` is passed BY VALUE (a fresh frozenset per
    recursion) so a branch can never corrupt a sibling — the source of both
    determinism and acyclicity."""
    trail = (*trail, (objective, why))
    if len(trail) >= 2:
        out.append(trail)
    if len(trail) >= max_len:
        return
    for successor, succ_why in _COMPOSITION_EDGES.get(objective, ()):
        if successor not in visited:
            _walk(successor, succ_why, visited | {successor}, trail, max_len, out)


def compose_chains(start_objective: str, max_len: int) -> list[tuple[tuple[str, str], ...]]:
    """Every compositional (length >= 2) ordered trail rooted at ``start_objective``.

    A pure, deterministic, bounded, acyclic DFS over :data:`_COMPOSITION_EDGES`:
    successors are visited in insertion order, no objective repeats within a chain
    (an acyclic ``visited`` frozenset passed by value), and depth is capped by
    ``max_len``. Each trail is an ordered tuple of ``(objective, why)`` pairs; the
    length-1 self-trail is EXCLUDED so the result is genuinely compositional. A
    start with no outgoing edge (or ``max_len < 2``) yields ``[]``. No IO, no
    clock, no randomness — same repo state yields identical bytes."""
    out: list[tuple[tuple[str, str], ...]] = []
    _walk(start_objective, "", frozenset({start_objective}), (), max_len, out)
    return out


def chain_value(objectives: Sequence[str]) -> float:
    """The COMPOUNDED buyer value of an objective sequence, in [0, 1].

    Folds :func:`app.engine.move_value.objective_value` over the names with a
    ``0.85**i`` geometric decay (mirroring the permutation feasibility decay), so
    a long tail of low-value tidies can never dominate a short high-value chain.
    Clamped to ``1.0`` and rounded to 4 places with the project's standard
    discipline — pure, deterministic, zero-cost."""
    return round(
        min(1.0, sum((objective_value(name) * (0.85**i) for i, name in enumerate(objectives)), 0.0)),
        4,
    )
