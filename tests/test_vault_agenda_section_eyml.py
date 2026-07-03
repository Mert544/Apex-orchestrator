"""The vault's SIXTH section: the agenda artifact (living-assistant polish).

``_agenda_section`` mirrors ``.apex/agenda.json`` into the vault by reading the
ARTIFACT BYTES directly — never by importing ``app.engine.agenda`` (which
imports the vault; the reverse import would be circular) and never by running
the readiness analysis again. Contracts pinned here:

* absent artifact → the SAME honest-absent shape as every sibling section;
* corrupt / non-dict artifact → ``present: True, readable: False``;
* readable artifact → the four lane LENGTHS plus the retired-operator notes
  (V4 learned caution surfaces in memory's one roll-up too);
* single-writer both ways: reading leaves the artifact bytes untouched, and
  ``write_vault`` stays byte-idempotent with the section in place;
* the vault source keeps ZERO imports of the agenda engine.
"""

from __future__ import annotations

import json
from pathlib import Path

import app.memory.vault as vault_module
from app.memory.vault import (
    VAULT_REL,
    load_vault_view,
    render_vault_markdown,
    write_vault,
)

_AGENDA_REL = ".apex/agenda.json"


def _pyproject(tmp: Path) -> None:
    (tmp / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")


def _agenda_payload() -> dict:
    """A realistic agenda artifact (the shape ``write_agenda`` produces)."""
    return {
        "schema_version": 1,
        "readiness_score": 0.5,
        "total_findings": 4,
        "lanes": {
            "landable": [
                {"fix_kind": "implement-stub", "file": "app/a.py", "line": 3,
                 "category": "todo", "value": 0.8, "rank": 1},
                {"fix_kind": "infer-type-hints", "file": "app/b.py", "line": 9,
                 "category": "types", "value": 0.5, "rank": 2},
            ],
            "human": [
                {"fix_kind": "", "file": "app/c.py", "line": 1,
                 "category": "security", "rationale": "needs a person"},
            ],
            "watched": [
                {"operator": "risky-op", "retired": True, "entries": 2,
                 "note": "RETIRED from landable (2 entrie(s)): feasibility "
                         "0.90 — rollbacks dominate"},
                {"operator": "meh-op", "feasibility": 0.95, "realization": 1.0,
                 "note": "feasibility 0.95 (rollbacks on this project)"},
            ],
            "user": [
                {"file": ".apex/vault/notes/n.md", "valid": True,
                 "request": "do x"},
            ],
        },
    }


def _seed_agenda(tmp: Path, payload=None) -> str:
    (tmp / ".apex").mkdir(exist_ok=True)
    text = json.dumps(payload if payload is not None else _agenda_payload(),
                      sort_keys=True, indent=1, ensure_ascii=False) + "\n"
    (tmp / _AGENDA_REL).write_text(text, encoding="utf-8")
    return text


# --------------------------------------------------------------------------- #
# Honest empties + shape parity with the sibling sections
# --------------------------------------------------------------------------- #


def test_absent_agenda_matches_the_sibling_absent_shape_exactly(tmp_path: Path):
    _pyproject(tmp_path)
    view = load_vault_view(tmp_path)
    # The sixth section is present in the view even when the artifact is not.
    assert "agenda" in view["sections"]
    # EXACT shape parity with e.g. the absent idea_memory section — the vault
    # never fabricates an agenda for a project that has not written one.
    assert view["sections"]["agenda"] == {"present": False,
                                          "source": _AGENDA_REL}
    md = render_vault_markdown(view)
    assert "- **agenda** — absent (`.apex/agenda.json`)" in md


def test_corrupt_agenda_is_surfaced_not_dropped(tmp_path: Path):
    _pyproject(tmp_path)
    (tmp_path / ".apex").mkdir()
    (tmp_path / _AGENDA_REL).write_text("{not valid json", encoding="utf-8")
    section = load_vault_view(tmp_path)["sections"]["agenda"]
    assert section == {"present": True, "source": _AGENDA_REL,
                       "readable": False}
    md = render_vault_markdown(load_vault_view(tmp_path))
    assert "- **agenda** — present but unreadable (`.apex/agenda.json`)" in md


def test_non_dict_agenda_payload_is_unreadable(tmp_path: Path):
    """A parseable but non-object payload (e.g. a bare list) is NOT the agenda
    schema — surfaced as unreadable, never guessed at."""
    _pyproject(tmp_path)
    _seed_agenda(tmp_path, payload=None)  # ensure .apex exists
    (tmp_path / _AGENDA_REL).write_text("[1, 2, 3]\n", encoding="utf-8")
    section = load_vault_view(tmp_path)["sections"]["agenda"]
    assert section == {"present": True, "source": _AGENDA_REL,
                       "readable": False}


# --------------------------------------------------------------------------- #
# Readable artifact: lane counts + retired surfacing
# --------------------------------------------------------------------------- #


def test_readable_agenda_summarises_lanes_and_retired(tmp_path: Path):
    _pyproject(tmp_path)
    _seed_agenda(tmp_path)
    section = load_vault_view(tmp_path)["sections"]["agenda"]
    assert section == {
        "present": True,
        "source": _AGENDA_REL,
        "readable": True,
        "landable": 2,
        "human": 1,
        "watched": 2,
        "user": 1,
        # Only the retired==True watched entry surfaces, with operator + note
        # (the non-retired "meh-op" caution stays in the artifact, uncopied).
        "retired": [{"operator": "risky-op",
                     "note": "RETIRED from landable (2 entrie(s)): "
                             "feasibility 0.90 — rollbacks dominate"}],
    }
    md = render_vault_markdown(load_vault_view(tmp_path))
    assert ("- **agenda** — 2 landable / 1 human / 2 watched / 1 user "
            "note(s); 1 retired operator(s) (`.apex/agenda.json`)") in md


def test_readable_agenda_with_empty_lanes_has_zero_counts(tmp_path: Path):
    """Edge/empty path: a fresh agenda (all lanes empty) reads as honest
    zeroes with an empty retired list — readable, not absent."""
    _pyproject(tmp_path)
    payload = {"schema_version": 1, "readiness_score": 1.0,
               "total_findings": 0,
               "lanes": {"landable": [], "human": [], "watched": [],
                         "user": []}}
    _seed_agenda(tmp_path, payload)
    section = load_vault_view(tmp_path)["sections"]["agenda"]
    assert section["readable"] is True
    assert (section["landable"], section["human"],
            section["watched"], section["user"]) == (0, 0, 0, 0)
    assert section["retired"] == []


def test_degenerate_lanes_shape_is_tolerated_never_raises(tmp_path: Path):
    """A dict artifact whose ``lanes`` is missing (or lanes are non-lists)
    still reads: counts are 0 and retired empty — the vault reader is a leaf
    and never validates the agenda module's format on its behalf."""
    _pyproject(tmp_path)
    _seed_agenda(tmp_path, {"schema_version": 1, "lanes": {"landable": "??"}})
    section = load_vault_view(tmp_path)["sections"]["agenda"]
    assert section["readable"] is True
    assert section["landable"] == 0 and section["retired"] == []
    _seed_agenda(tmp_path, {"schema_version": 1})  # no lanes key at all
    section = load_vault_view(tmp_path)["sections"]["agenda"]
    assert section["readable"] is True
    assert (section["landable"], section["human"],
            section["watched"], section["user"]) == (0, 0, 0, 0)


# --------------------------------------------------------------------------- #
# Single-writer both ways + byte-determinism
# --------------------------------------------------------------------------- #


def test_agenda_artifact_bytes_are_untouched_by_vault_reads_and_writes(
        tmp_path: Path):
    _pyproject(tmp_path)
    original = _seed_agenda(tmp_path)
    load_vault_view(tmp_path)
    write_vault(tmp_path)
    # The agenda module stays the artifact's ONLY writer: the vault read the
    # bytes and wrote only its own file.
    assert (tmp_path / _AGENDA_REL).read_text(encoding="utf-8") == original


def test_write_vault_with_agenda_is_byte_idempotent_and_rebuildable(
        tmp_path: Path):
    _pyproject(tmp_path)
    _seed_agenda(tmp_path)
    first = write_vault(tmp_path).read_bytes()
    assert write_vault(tmp_path).read_bytes() == first  # byte-idempotent
    (tmp_path / VAULT_REL).unlink()
    assert write_vault(tmp_path).read_bytes() == first  # fully rebuildable
    vault = json.loads(first.decode("utf-8"))
    assert vault["sections"]["agenda"]["landable"] == 2


def test_vault_source_never_imports_the_agenda_engine():
    """LEAF-READER PIN: ``app.engine.agenda`` imports the vault
    (``read_user_notes``), so the vault importing it back would be a circular
    import — and would break the artifact-read design (the vault mirrors the
    already-written judgement; it never recomputes it). The source must read
    the artifact file, not the engine."""
    import ast

    src = Path(vault_module.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any(mod.startswith("app.engine.agenda") for mod in imported), (
        "vault.py must stay a leaf reader of the agenda ARTIFACT, never the "
        "agenda engine (circular import + double-analysis)")
    assert '".apex/agenda.json"' in src  # the artifact path, read directly
