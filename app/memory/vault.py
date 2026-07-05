"""The Apex vault — ONE deterministic view over the project's persistent memory.

Apex's cross-run memory grew organically into sibling stores under ``.apex/``:
``idea-memory.json`` (per-operator outcome memory), ``dream-journal.json``
(append-only dream/landing journal), ``proof-of-fix.json`` (tamper-evident fix
evidence; the track record is DERIVED from it), and ``dream-digest.md`` (the
one-page dream narrative). Every consumer that wants "what does Apex remember
about this project" has to know all four paths and their shapes.

The vault is the single roll-up: ``load_vault_view`` composes the stores into
one schema-versioned view through their EXISTING readers (raw passthrough for
the JSON/text stores, :func:`app.engine.proof_history.load_proof_history` for
proof evidence, ``summarise_fix_track_record`` for the derived track record,
plus a lane-count summary of the ``agenda.json`` ARTIFACT — read as bytes,
never through ``app.engine.agenda``, which itself imports this module — with
no new analysis, no reinterpretation), and ``write_vault`` dumps that view
byte-deterministically to ``.apex/vault/vault.json``.

Contracts (V1 of the living-assistant program, ``docs/rnd/
apex-vizyon-yasayan-asistan.md``):

* **Single writer** — only :func:`write_vault` writes the vault file; every
  source store keeps its ONE existing writer. The vault is a mirror, never a
  second author.
* **Lossless & additive** — source stores are read-only inputs and remain the
  canonical truth; deleting the vault loses nothing (it is fully rebuildable).
* **Honest empties** — an absent store appears as ``{"present": False}``; the
  vault never fabricates memory for a project Apex has not worked on.
* **Deterministic** — same stores → byte-identical vault (sorted keys, no
  clocks, no randomness), so a vault diff is a REAL memory change.
* **Timeline (vault-timeline addition)** — ``apex vault --save`` snapshots
  this view under ``.apex/vault/snapshots/<index>.json`` (own writer domain,
  index-keyed rather than time-keyed — no clock in the content, same rule as
  above) and ``apex vault --diff`` renders an honest, deterministic delta
  between a saved snapshot and the live view — the owner's "what changed
  while I was away?" surface. See :mod:`app.memory.vault_history`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.engine.idea_memory import MEMORY_REL
from app.engine.proof_history import load_proof_history, summarise_fix_track_record

SCHEMA_VERSION = 1
VAULT_REL = ".apex/vault/vault.json"
_DREAM_JOURNAL_REL = ".apex/dream-journal.json"
_DREAM_DIGEST_REL = ".apex/dream-digest.md"
_PROOF_REL = ".apex/proof-of-fix.json"
_AGENDA_REL = ".apex/agenda.json"
_EPISTEMIC_REL = ".epistemic/memory.json"


def _absent(source: str) -> dict[str, Any]:
    return {"present": False, "source": source}


def _json_section(root: Path, rel: str) -> dict[str, Any]:
    """A raw-passthrough section for one JSON store (lossless mirror)."""
    path = root / rel
    if not path.exists():
        return _absent(rel)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # An unreadable store is surfaced as such — never silently dropped and
        # never "repaired" here (the store's own writer owns its format).
        return {"present": True, "source": rel, "readable": False}
    return {"present": True, "source": rel, "readable": True, "data": data}


def _text_section(root: Path, rel: str) -> dict[str, Any]:
    path = root / rel
    if not path.exists():
        return _absent(rel)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"present": True, "source": rel, "readable": False}
    return {"present": True, "source": rel, "readable": True, "text": text}


def _agenda_section(root: Path) -> dict[str, Any]:
    """The agenda ARTIFACT (``.apex/agenda.json``) as a summarised vault section.

    Reads the artifact FILE directly (``json.loads``) instead of importing
    ``app.engine.agenda``: the agenda module already imports the vault
    (``read_user_notes``), so importing back would be circular — and the vault
    must stay a leaf reader of ``.apex/`` artifacts. Reading bytes also keeps
    the single-writer contract intact on BOTH sides: the agenda module remains
    the agenda file's only author, the vault module the vault file's.

    Contract (mirrors the sibling sections): absent → ``{"present": False,
    "source": ...}``; unparseable or non-dict → ``{"present": True,
    "readable": False, ...}``; readable → the four lane LENGTHS plus the
    ``retired`` operators (V4 learned caution) with their notes, so the vault
    shows Apex's current judgement without duplicating the full artifact."""
    path = root / _AGENDA_REL
    if not path.exists():
        return _absent(_AGENDA_REL)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        # Corrupt bytes or a non-object payload: surfaced honestly, never
        # "repaired" here (the agenda module owns the artifact's format).
        return {"present": True, "source": _AGENDA_REL, "readable": False}
    lanes = data.get("lanes")
    if not isinstance(lanes, dict):
        lanes = {}

    def _lane(name: str) -> list[Any]:
        lane = lanes.get(name)
        return lane if isinstance(lane, list) else []

    retired = [{"operator": entry.get("operator", ""),
                "note": entry.get("note", "")}
               for entry in _lane("watched")
               if isinstance(entry, dict) and entry.get("retired") is True]
    return {
        "present": True,
        "source": _AGENDA_REL,
        "readable": True,
        "landable": len(_lane("landable")),
        "human": len(_lane("human")),
        "watched": len(_lane("watched")),
        "user": len(_lane("user")),
        "retired": retired,
    }


def _epistemic_section(root: Path) -> dict[str, Any]:
    """The epistemic-memory ARTIFACT (``.epistemic/memory.json``) as a summarised
    vault section — what Apex has learned across ``apex scan``/``apex run`` (the
    ``PersistentMemoryStore`` path).

    Read as BYTES (``json.loads``), never by importing ``PersistentMemoryStore``,
    so the vault stays a leaf reader and the store keeps its single-writer
    contract — the same discipline :func:`_agenda_section` applies to ``.apex/``.

    Contract (mirrors the sibling sections): absent → ``{"present": False,
    "source": ...}``; unparseable or non-dict → ``{"present": True,
    "readable": False, ...}``; readable → COUNT summaries only (known claims /
    questions / runs + the last run's id), never the raw ``last_report``/
    ``last_full_report`` blobs (report dumps would bloat the vault and its diffs)."""
    path = root / _EPISTEMIC_REL
    if not path.exists():
        return _absent(_EPISTEMIC_REL)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        return {"present": True, "source": _EPISTEMIC_REL, "readable": False}

    def _count(key: str) -> int:
        value = data.get(key)
        return len(value) if isinstance(value, list) else 0

    runs = data.get("runs")
    runs = runs if isinstance(runs, list) else []
    last_run_id = ""
    if runs and isinstance(runs[-1], dict):
        last_run_id = runs[-1].get("run_id", "") or ""
    return {
        "present": True,
        "source": _EPISTEMIC_REL,
        "readable": True,
        "known_claims": _count("known_claims"),
        "known_questions": _count("known_questions"),
        "runs": len(runs),
        "last_run_id": last_run_id,
    }


def load_vault_view(project_root: str | Path) -> dict[str, Any]:
    """Compose the vault view from the live stores (pure read, no writes)."""
    root = Path(project_root)
    proofs = load_proof_history(root)
    proof_section: dict[str, Any] = (
        {"present": True, "source": _PROOF_REL, "readable": True, "data": proofs}
        if proofs else _absent(_PROOF_REL)
    )
    track_record: dict[str, Any] = {
        # Derived, not stored: recomputed from proof evidence on every load so
        # it can never drift from its source (mirrors `apex trackrecord`).
        "derived_from": _PROOF_REL,
        "present": bool(proofs),
    }
    if proofs:
        track_record["summary"] = summarise_fix_track_record(proofs)
    return {
        "schema_version": SCHEMA_VERSION,
        "sections": {
            "idea_memory": _json_section(root, MEMORY_REL),
            "dream_journal": _json_section(root, _DREAM_JOURNAL_REL),
            "dream_digest": _text_section(root, _DREAM_DIGEST_REL),
            "proof_of_fix": proof_section,
            "track_record": track_record,
            # Sixth section (living-assistant polish): the agenda artifact,
            # summarised lane-by-lane — read as BYTES, never via the agenda
            # engine (see _agenda_section for the circular-import/single-writer
            # rationale).
            "agenda": _agenda_section(root),
            # Seventh section: the epistemic memory Apex builds across
            # `apex scan`/`apex run` (.epistemic/memory.json), summarised as
            # counts only — read as BYTES, never via PersistentMemoryStore.
            "epistemic_memory": _epistemic_section(root),
        },
    }


def write_vault(project_root: str | Path) -> Path:
    """Refresh ``.apex/vault/vault.json`` from the live stores and return its
    path. The vault module is the file's ONLY writer (single-writer contract);
    the dump is byte-deterministic so re-running with unchanged stores is a
    byte-identical no-op."""
    root = Path(project_root)
    view = load_vault_view(root)
    path = root / VAULT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(view, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


NOTES_DIR_REL = ".apex/vault/notes"
_NOTE_TAG = "#apex-hedef"


def read_user_notes(project_root: str | Path) -> list[dict[str, Any]]:
    """The user's hand-written vault notes that opt INTO the agenda (V5).

    A note is any ``*.md`` under ``.apex/vault/notes/`` carrying a line of the
    form ``#apex-hedef <request>``. The request is the text after the tag on
    that line — the user states the goal in their own words and Apex's normal
    understand→plan→act pipeline takes it from there, preview-first. Contract:

    * Files WITHOUT the tag are not Apex's business — skipped entirely (the
      notes directory may hold anything else the user keeps there).
    * A tagged note with an EMPTY request, or an unreadable file, is returned
      with ``valid: False`` and a stated reason — honestly rejected, never
      guessed at.
    * Only the FIRST tag line counts (one note = one candidate); extra tag
      lines are reported in ``extra_tags`` so nothing is silently dropped.
    * Read-only and deterministic: notes sort by relative path; no clocks.
    """
    notes_dir = Path(project_root) / NOTES_DIR_REL
    if not notes_dir.is_dir():
        return []
    notes: list[dict[str, Any]] = []
    for path in sorted(notes_dir.glob("*.md")):
        rel = f"{NOTES_DIR_REL}/{path.name}"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            notes.append({"file": rel, "valid": False,
                          "reason": "unreadable file"})
            continue
        tag_lines = [ln for ln in lines if _NOTE_TAG in ln]
        if not tag_lines:
            continue
        request = tag_lines[0].split(_NOTE_TAG, 1)[1].strip()
        if not request:
            notes.append({"file": rel, "valid": False,
                          "reason": f"empty request after {_NOTE_TAG}"})
            continue
        note: dict[str, Any] = {"file": rel, "valid": True, "request": request}
        if len(tag_lines) > 1:
            note["extra_tags"] = len(tag_lines) - 1
        notes.append(note)
    return notes


def _section_line(name: str, section: dict[str, Any]) -> str:
    if not section.get("present"):
        origin = section.get("source") or section.get("derived_from", "?")
        return f"- **{name}** — absent (`{origin}`)"
    if name == "track_record":
        summary = section.get("summary") or {}
        return f"- **{name}** — derived from proof evidence ({len(summary)} field(s))"
    if not section.get("readable", True):
        return f"- **{name}** — present but unreadable (`{section['source']}`)"
    if name == "agenda":
        return (f"- **{name}** — {section['landable']} landable / "
                f"{section['human']} human / {section['watched']} watched / "
                f"{section['user']} user note(s); "
                f"{len(section['retired'])} retired operator(s) "
                f"(`{section['source']}`)")
    if name == "epistemic_memory":
        return (f"- **{name}** — {section['known_claims']} claim(s) / "
                f"{section['known_questions']} question(s) / "
                f"{section['runs']} run(s) (`{section['source']}`)")
    data = section.get("data")
    if isinstance(data, list):
        size = f"{len(data)} entrie(s)"
    elif isinstance(data, dict):
        size = f"{len(data)} key(s)"
    else:
        size = f"{len(section.get('text', ''))} char(s)"
    return f"- **{name}** — {size} (`{section['source']}`)"


def render_vault_markdown(view: dict[str, Any]) -> str:
    """A one-screen honest summary of what the vault holds (read-only)."""
    lines = [f"# Apex vault (schema v{view['schema_version']})", ""]
    sections = view["sections"]
    present = sum(1 for s in sections.values() if s.get("present"))
    lines.append(
        f"{present}/{len(sections)} memory store(s) present — the vault mirrors "
        f"them losslessly into `{VAULT_REL}` (rebuildable, single-writer).")
    lines.append("")
    for name in sorted(sections):
        lines.append(_section_line(name, sections[name]))
    if not present:
        lines += ["", "_No memory yet — run `apex maintain`, `apex dream` or "
                      "`apex develop --apply` to start building some._"]
    return "\n".join(lines) + "\n"
