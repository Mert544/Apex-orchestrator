"""A MAP-Elites archive of verified transform compositions — the organism's
learned playbook.

The composition memory (``idea_memory.by_sequence``) learns which *pairs* of
operators land. This goes one level up: it records, per kind of campaign, the
best whole COMPOSITION the Objective-Compiler has ever verified — a persistent,
inspectable library of "for this objective and this mix of operators, the
strongest run did N verified moves for a fitness gain of D."

It is a MAP-Elites archive (Mouret & Clune, 2015): a dict keyed by a behaviour
descriptor, each cell holding the single best-performing "elite" mapped to it.
The descriptor is ``objective | operator-signature`` (the sorted set of move
operators used); the quality is the fitness improvement (lower is better, so
improvement = start − end). A new campaign replaces a cell only when it improves
more — or ties and is shorter (the same gain for fewer moves is the better
recipe). Across runs and projects this illuminates *what compositions resolve
what objectives*, deterministically, with zero model.

Persisted to ``.apex/composition-archive.json``; stdlib-only.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

ARCHIVE_REL = ".apex/composition-archive.json"

__all__ = [
    "ArchiveEntry", "CompositionArchive", "record_campaign",
    "render_playbook_markdown",
]


@dataclass
class ArchiveEntry:
    objective: str
    operators: list[str]      # the move operators, in applied order
    moves: int                # how many verified moves the campaign composed
    fitness_delta: float      # improvement = fitness_start − fitness_end
    modules: int              # distinct modules the campaign touched
    date: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _descriptor(objective: str, operators: list[str]) -> str:
    """The behaviour cell a campaign maps to: its objective and the *set* of
    operator kinds it used (order-independent), e.g. ``modernize|fix_collection+
    fix_fstring+modernize``. Same shape of work → same cell → they compete."""
    sig = "+".join(sorted(set(operators))) if operators else "none"
    return f"{objective}|{sig}"


@dataclass
class CompositionArchive:
    """Per-cell elites — the best verified composition for each behaviour cell."""

    cells: dict[str, ArchiveEntry] = field(default_factory=dict)

    @classmethod
    def load(cls, project_root: str | Path, path: str | Path | None = None) -> CompositionArchive:
        p = Path(path) if path else Path(project_root) / ARCHIVE_REL
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        cells: dict[str, ArchiveEntry] = {}
        for key, v in (data.get("cells") or {}).items():
            if isinstance(v, dict):
                try:
                    cells[key] = ArchiveEntry(**v)
                except TypeError:
                    continue
        return cls(cells=cells)

    def save(self, project_root: str | Path, path: str | Path | None = None) -> Path:
        p = Path(path) if path else Path(project_root) / ARCHIVE_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return p

    def to_dict(self) -> dict[str, Any]:
        return {"cells": {k: v.to_dict() for k, v in sorted(self.cells.items())}}

    def consider(self, entry: ArchiveEntry) -> bool:
        """Per-cell elitism: keep ``entry`` only if its cell is empty, it
        improves the fitness more than the incumbent, or it ties on improvement
        with fewer moves (the same gain for a shorter recipe is better).
        Returns True when the archive changed."""
        key = _descriptor(entry.objective, entry.operators)
        cur = self.cells.get(key)
        if cur is None:
            self.cells[key] = entry
            return True
        if (entry.fitness_delta > cur.fitness_delta
                or (entry.fitness_delta == cur.fitness_delta and entry.moves < cur.moves)):
            self.cells[key] = entry
            return True
        return False

    def entries(self) -> list[ArchiveEntry]:
        """The elites, strongest improvement first (then fewer moves, stable)."""
        return sorted(self.cells.values(),
                      key=lambda e: (-e.fitness_delta, e.moves, e.objective))


def record_campaign(project_root: str | Path, objective: str, operators: list[str],
                    fitness_start: float, fitness_end: float, modules: int) -> bool:
    """Load → consider this campaign as a candidate elite → save. No-op (and
    never raises into the caller) when the campaign did nothing or worsened
    fitness. Returns whether the archive changed."""
    if not operators or fitness_end >= fitness_start:
        return False
    archive = CompositionArchive.load(project_root)
    entry = ArchiveEntry(
        objective=objective, operators=list(operators), moves=len(operators),
        fitness_delta=round(fitness_start - fitness_end, 4), modules=modules,
        date=date.today().isoformat())
    changed = archive.consider(entry)
    if changed:
        archive.save(project_root)
    return changed


def render_playbook_markdown(archive: CompositionArchive) -> str:
    """Render the learned playbook — what compositions resolve what objectives."""
    entries = archive.entries()
    if not entries:
        return ("# Composition playbook\n\n_Empty — run `apex develop --apply` to "
                "teach the organism which compositions resolve which objectives._\n")
    lines = [f"# Composition playbook — {len(entries)} learned recipe(s)", "",
             "_The best verified composition the organism has seen for each kind "
             "of objective._", "",
             "| Objective | Recipe (operators) | Moves | Fitness gain | Modules |",
             "|---|---|---:|---:|---:|"]
    for e in entries:
        recipe = " → ".join(e.operators) if e.operators else "—"
        lines.append(f"| {e.objective} | {recipe} | {e.moves} | "
                     f"{e.fitness_delta:g} | {e.modules} |")
    lines.append("")
    return "\n".join(lines)
