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
proof evidence, ``summarise_fix_track_record`` for the derived track record —
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


def _section_line(name: str, section: dict[str, Any]) -> str:
    if not section.get("present"):
        origin = section.get("source") or section.get("derived_from", "?")
        return f"- **{name}** — absent (`{origin}`)"
    if name == "track_record":
        summary = section.get("summary") or {}
        return f"- **{name}** — derived from proof evidence ({len(summary)} field(s))"
    if not section.get("readable", True):
        return f"- **{name}** — present but unreadable (`{section['source']}`)"
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
