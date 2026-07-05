"""The vault's SEVENTH section: the epistemic-memory artifact.

``_epistemic_section`` mirrors ``.epistemic/memory.json`` (what Apex learns
across ``apex scan``/``apex run``, written by ``PersistentMemoryStore``) into the
vault by reading the ARTIFACT BYTES directly — never by importing
``PersistentMemoryStore`` — so the vault stays a leaf reader and the store keeps
its single-writer contract. Contracts pinned here:

* absent artifact → the SAME honest-absent shape as every sibling section;
* corrupt / non-dict artifact → ``present: True, readable: False``;
* readable artifact → COUNT summaries only (claims / questions / runs + last
  run id), never the raw ``last_report`` blobs;
* a schema-mismatched / foreign-shaped payload degrades to zero counts, never
  raises;
* the vault source keeps ZERO imports of ``PersistentMemoryStore``.
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

_EPISTEMIC_REL = ".epistemic/memory.json"


def _pyproject(tmp: Path) -> None:
    (tmp / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")


def _write_epistemic(tmp: Path, payload: dict) -> None:
    path = tmp / _EPISTEMIC_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _payload() -> dict:
    """A realistic .epistemic/memory.json (the shape ``persist_run`` produces),
    including the big report blobs the section must NOT surface."""
    return {
        "schema_version": 1,
        "project_root": "/proj",
        "known_claims": ["a", "b", "c"],
        "known_questions": ["q1", "q2"],
        "last_report": {"huge": "blob" * 500},
        "last_full_report": {"also": "huge" * 500},
        "runs": [
            {"run_id": "run-1", "timestamp": "t1", "objective": "scan"},
            {"run_id": "run-2", "timestamp": "t2", "objective": "scan"},
        ],
    }


def test_absent_is_honest():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _pyproject(tmp)
        sec = load_vault_view(tmp)["sections"]["epistemic_memory"]
        assert sec == {"present": False, "source": _EPISTEMIC_REL}


def test_readable_summarizes_counts_only(tmp_path: Path):
    _pyproject(tmp_path)
    _write_epistemic(tmp_path, _payload())
    sec = load_vault_view(tmp_path)["sections"]["epistemic_memory"]
    assert sec["present"] is True
    assert sec["readable"] is True
    assert sec["known_claims"] == 3
    assert sec["known_questions"] == 2
    assert sec["runs"] == 2
    assert sec["last_run_id"] == "run-2"
    # The big report blobs never leak into the vault.
    assert "last_report" not in sec
    assert "last_full_report" not in sec


def test_corrupt_bytes_are_present_but_unreadable(tmp_path: Path):
    _pyproject(tmp_path)
    path = tmp_path / _EPISTEMIC_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not valid json", encoding="utf-8")
    sec = load_vault_view(tmp_path)["sections"]["epistemic_memory"]
    assert sec == {"present": True, "source": _EPISTEMIC_REL, "readable": False}


def test_non_dict_payload_is_unreadable(tmp_path: Path):
    _pyproject(tmp_path)
    _write_epistemic_raw = tmp_path / _EPISTEMIC_REL
    _write_epistemic_raw.parent.mkdir(parents=True, exist_ok=True)
    _write_epistemic_raw.write_text("[1, 2, 3]", encoding="utf-8")
    sec = load_vault_view(tmp_path)["sections"]["epistemic_memory"]
    assert sec["present"] is True
    assert sec["readable"] is False


def test_foreign_shape_degrades_to_zero_counts(tmp_path: Path):
    _pyproject(tmp_path)
    # Keys present but wrong types / missing — must degrade, never raise.
    _write_epistemic(tmp_path, {"known_claims": "oops", "runs": {"not": "a list"}})
    sec = load_vault_view(tmp_path)["sections"]["epistemic_memory"]
    assert sec["known_claims"] == 0
    assert sec["known_questions"] == 0
    assert sec["runs"] == 0
    assert sec["last_run_id"] == ""


def test_render_line_shows_counts(tmp_path: Path):
    _pyproject(tmp_path)
    _write_epistemic(tmp_path, _payload())
    md = render_vault_markdown(load_vault_view(tmp_path))
    assert "**epistemic_memory** — 3 claim(s) / 2 question(s) / 2 run(s)" in md


def test_vault_source_never_imports_persistent_memory_store():
    """LEAF-READER PIN: the vault reads the ``.epistemic/memory.json`` ARTIFACT
    directly, never importing ``PersistentMemoryStore`` — same discipline it
    applies to the ``.apex/`` stores. Checks actual imports (AST), not mere
    mentions (the module docstring names the class to explain the rule)."""
    import ast

    src = Path(vault_module.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any("persistent_memory" in mod for mod in imported), (
        "vault.py must stay a leaf reader of the .epistemic ARTIFACT, never "
        "import PersistentMemoryStore")
    assert '".epistemic/memory.json"' in src  # the artifact path, read directly


def test_write_vault_is_byte_idempotent_with_section(tmp_path: Path):
    _pyproject(tmp_path)
    _write_epistemic(tmp_path, _payload())
    p1 = write_vault(tmp_path)
    first = p1.read_bytes()
    p2 = write_vault(tmp_path)
    assert p2.read_bytes() == first
    # The artifact itself is left untouched (single-writer both ways).
    assert (tmp_path / VAULT_REL).exists()
