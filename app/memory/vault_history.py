"""The vault's timeline — deterministic snapshot + diff over ONE roll-up.

``app.memory.vault`` answers "what does Apex remember about this project right
now?". This sibling module answers the owner's follow-up question — "ben
yokken ne değişti?" ("what changed while I was away?") — by letting a snapshot
of that roll-up be saved and later diffed against the live vault. Mirrors the
relationship between ``app.engine.idea_roadmap`` and ``app.engine.
roadmap_history``: the roll-up stays a pure read; the timeline lives beside it.

Design (V1 of the vault-timeline addition):

* **Snapshots are INDEX-keyed, not time-keyed.** The vault's own determinism
  rule (no clocks in artifacts) applies here too: a snapshot's identity is a
  monotonically increasing integer (``.apex/vault/snapshots/<n>.json``, ``n``
  starting at 1), not a timestamp. An index is also the short, human-typeable
  handle ``--diff INDEX`` needs — a content hash would be equally
  clock-free but far less friendly to type at a prompt.
* **Every ``--save`` appends** (no de-duplication against the previous
  snapshot): the timeline is an honest log of *when you looked*, and "I
  checked and nothing had changed" is itself a legitimate entry.
* **Single writer, own domain.** Only :func:`save_snapshot` writes under
  ``.apex/vault/snapshots/`` — the vault's own writer domain (alongside
  ``vault.json``); every source store stays exactly as read-only as it always
  was. Loading a snapshot or diffing never writes anything.
* **Deterministic diff.** :func:`diff_vault` is a pure function of two vault
  VIEWS (the shape :func:`app.memory.vault.load_vault_view` returns) — same
  two views in, byte-identical result out. It walks each of the vault's
  sections generically (dicts recurse key-by-key so nested tables like
  idea-memory's ``by_operator``/``by_label``/... diff at their real leaves;
  lists compare as an order-insensitive multiset of their JSON-canonical
  entries) to produce honest added/removed/changed counts per store, plus a
  narrated "headline" for the two sections with the richest story to tell —
  ``agenda`` (lane-count movement + newly-retired operators) and
  ``track_record`` (reliability/fix-count movement).
* **Honest empties.** No snapshot saved yet, or the requested index does not
  exist, is reported plainly (never fabricated, never an error) — the CLI seam
  always exits 0 for both cases, matching ``apex vault``'s own contract.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

SNAPSHOTS_DIR_REL = ".apex/vault/snapshots"

# The two sections with a stable, meaningful scalar story worth narrating
# beyond generic added/removed/changed counts (see module docstring).
_AGENDA = "agenda"
_TRACK_RECORD = "track_record"


# --------------------------------------------------------------------------- #
# Snapshot storage (the only I/O in this module)
# --------------------------------------------------------------------------- #


def _snapshots_dir(root: Path) -> Path:
    return root / SNAPSHOTS_DIR_REL


def _snapshot_path(root: Path, index: int) -> Path:
    return _snapshots_dir(root) / f"{index}.json"


def _snapshot_indices(root: Path) -> list[int]:
    """Existing snapshot indices, ascending (deterministic). A non-numeric
    filename under the directory is simply ignored — inert, never a crash."""
    d = _snapshots_dir(root)
    if not d.is_dir():
        return []
    indices: list[int] = []
    for path in d.glob("*.json"):
        try:
            indices.append(int(path.stem))
        except ValueError:
            continue
    return sorted(indices)


def available_indices(project_root: str | Path) -> list[int]:
    """Public mirror of :func:`_snapshot_indices` for honest "here's what you
    do have" messages when a requested index does not exist."""
    return _snapshot_indices(Path(project_root))


def save_snapshot(project_root: str | Path, view: dict[str, Any],
                   label: str = "") -> dict[str, Any]:
    """Append ``view`` as the next monotonic-index snapshot.

    No wall clock anywhere in the content — the index alone orders the
    timeline, so two saves of an unchanged vault differ only by index, never
    by a fabricated time. Returns ``{"index": n, "label": ..., "path": ...}``.
    """
    root = Path(project_root)
    indices = _snapshot_indices(root)
    index = indices[-1] + 1 if indices else 1
    payload = {"index": index, "label": label, "view": view}
    path = _snapshot_path(root, index)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {"index": index, "label": label, "path": path}


def load_snapshot(project_root: str | Path, index: int | None = None) -> dict[str, Any] | None:
    """Load a snapshot by ``index``, or the LATEST (highest index) when
    ``index`` is ``None``. Returns ``None`` honestly when there is no
    snapshot at all, the requested index does not exist, or the file is
    corrupt/foreign-shaped — never raises."""
    root = Path(project_root)
    indices = _snapshot_indices(root)
    if not indices:
        return None
    chosen = index if index is not None else indices[-1]
    if chosen not in indices:
        return None
    try:
        data = json.loads(_snapshot_path(root, chosen).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "view" not in data:
        return None
    return data


# --------------------------------------------------------------------------- #
# Pure diff: generic per-store added/removed/changed + two narrated headlines
# --------------------------------------------------------------------------- #


def _leaf_count(value: Any) -> int:
    """How many independent leaves ``value`` contributes when an entire
    subtree appears or disappears (an empty container is honestly 0 leaves;
    a populated one counts every entry, recursing through nested dicts)."""
    if isinstance(value, dict):
        return sum(_leaf_count(v) for v in value.values())
    if isinstance(value, list):
        return len(value)
    return 1


def _list_delta(prev: list, curr: list) -> tuple[int, int]:
    """Order-insensitive added/removed counts between two JSON-value lists (a
    multiset diff by canonical JSON text). The sources are already
    deterministically ordered on disk, so what matters for "what changed" is
    WHICH entries exist, not their position."""
    prev_counts = Counter(json.dumps(v, sort_keys=True) for v in prev)
    curr_counts = Counter(json.dumps(v, sort_keys=True) for v in curr)
    added = sum((curr_counts - prev_counts).values())
    removed = sum((prev_counts - curr_counts).values())
    return added, removed


def _leaf_delta(prev: Any, curr: Any) -> tuple[int, int, int]:
    """(added, removed, changed) leaf counts between two JSON-ish values.

    Dicts recurse key-by-key (unbounded depth) so nested stat tables diff at
    their real leaves rather than as one opaque blob. Lists compare as an
    order-insensitive multiset — added/removed only, since a changed list
    entry has no stable identity to key a "changed" count on; it honestly
    counts as one remove + one add. Anything else (scalars, or a dict/list
    compared against a different shape) is a single leaf.
    """
    if prev == curr:
        return 0, 0, 0
    if isinstance(prev, dict) and isinstance(curr, dict):
        added = removed = changed = 0
        for key in curr.keys() - prev.keys():
            added += _leaf_count(curr[key])
        for key in prev.keys() - curr.keys():
            removed += _leaf_count(prev[key])
        for key in prev.keys() & curr.keys():
            a, r, c = _leaf_delta(prev[key], curr[key])
            added += a
            removed += r
            changed += c
        return added, removed, changed
    if isinstance(prev, list) and isinstance(curr, list):
        added, removed = _list_delta(prev, curr)
        return added, removed, 0
    return 0, 0, 1


def _agenda_headline(prev: dict[str, Any], curr: dict[str, Any]) -> str:
    """Lane-count movement + newly-retired operators, or "" when neither side
    is a readable, present agenda section (the generic counts already cover
    presence/readability transitions honestly)."""
    if not (prev.get("present") and curr.get("present")):
        return ""
    if not (prev.get("readable", True) and curr.get("readable", True)):
        return ""
    parts = [
        f"{lane} {prev.get(lane, 0)}→{curr.get(lane, 0)}"
        for lane in ("landable", "human", "watched", "user")
        if prev.get(lane, 0) != curr.get(lane, 0)
    ]
    prev_retired = {r.get("operator", "") for r in prev.get("retired", [])}
    curr_retired = {r.get("operator", "") for r in curr.get("retired", [])}
    newly = sorted(curr_retired - prev_retired)
    if newly:
        parts.append("newly retired: " + ", ".join(newly))
    return "; ".join(parts)


def _track_record_headline(prev: dict[str, Any], curr: dict[str, Any]) -> str:
    """Reliability/fix-count movement, or "" when either side has no track
    record yet (mirrors :func:`_agenda_headline`'s presence guard)."""
    if not (prev.get("present") and curr.get("present")):
        return ""
    prev_totals = (prev.get("summary") or {}).get("totals", {})
    curr_totals = (curr.get("summary") or {}).get("totals", {})
    parts = [
        f"{name} {prev_totals.get(name, 0)}→{curr_totals.get(name, 0)}"
        for name in ("total", "applied", "rolled_back", "blocked", "reliability")
        if prev_totals.get(name, 0) != curr_totals.get(name, 0)
    ]
    return "; ".join(parts)


@dataclass
class SectionDelta:
    name: str
    added: int = 0
    removed: int = 0
    changed: int = 0
    headline: str = ""

    @property
    def stable(self) -> bool:
        return self.added == 0 and self.removed == 0 and self.changed == 0

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"added": self.added, "removed": self.removed,
                                "changed": self.changed}
        if self.headline:
            out["headline"] = self.headline
        return out


@dataclass
class VaultDiff:
    sections: list[SectionDelta] = field(default_factory=list)
    prev_schema: int = 0
    curr_schema: int = 0

    @property
    def schema_changed(self) -> bool:
        return self.prev_schema != self.curr_schema

    @property
    def unchanged(self) -> bool:
        """Byte-identical in every way that matters: no schema bump and every
        section stable — the honest "nothing changed" state."""
        return not self.schema_changed and all(s.stable for s in self.sections)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_changed": self.schema_changed,
            "prev_schema": self.prev_schema,
            "curr_schema": self.curr_schema,
            "unchanged": self.unchanged,
            "sections": {s.name: s.to_dict() for s in self.sections},
        }


def diff_vault(previous_view: dict[str, Any], current_view: dict[str, Any]) -> VaultDiff:
    """Deterministic delta between a previously-snapshotted vault VIEW and the
    current live view. Pure — never touches disk, never raises."""
    prev_sections = previous_view.get("sections") or {}
    curr_sections = current_view.get("sections") or {}
    deltas: list[SectionDelta] = []
    for name in sorted(set(prev_sections) | set(curr_sections)):
        prev_section = prev_sections.get(name, {})
        curr_section = curr_sections.get(name, {})
        added, removed, changed = _leaf_delta(prev_section, curr_section)
        if name == _AGENDA:
            headline = _agenda_headline(prev_section, curr_section)
        elif name == _TRACK_RECORD:
            headline = _track_record_headline(prev_section, curr_section)
        else:
            headline = ""
        deltas.append(SectionDelta(name, added, removed, changed, headline))
    return VaultDiff(
        sections=deltas,
        prev_schema=previous_view.get("schema_version", 0),
        curr_schema=current_view.get("schema_version", 0),
    )


def _snapshot_ref(index: int, label: str) -> str:
    ref = f"snapshot #{index}"
    return f'{ref} ("{label}")' if label else ref


def render_vault_diff_markdown(diff: VaultDiff, snapshot_index: int,
                               snapshot_label: str = "") -> str:
    """A one-screen honest "what changed while I was away" report."""
    ref = _snapshot_ref(snapshot_index, snapshot_label)
    if diff.unchanged:
        return f"_Nothing changed since {ref} — the live vault is byte-identical._\n"
    lines = [f"# Apex vault — what changed since {ref}", ""]
    if diff.schema_changed:
        lines.append(f"_schema version {diff.prev_schema} → {diff.curr_schema} "
                      "(counts below may include schema-shape changes)_")
        lines.append("")
    for section in diff.sections:
        if section.stable:
            continue
        line = (f"- **{section.name}** — {section.added} added, "
                f"{section.removed} removed, {section.changed} changed")
        if section.headline:
            line += f"  ({section.headline})"
        lines.append(line)
    return "\n".join(lines) + "\n"
