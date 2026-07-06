"""The vault's V1 contracts (living-assistant program, wave V1).

Single writer, lossless additive mirror, honest empties, byte-determinism —
each asserted end-to-end against a throwaway project, plus the CLI seam.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.memory.vault import (
    VAULT_REL,
    load_vault_view,
    render_vault_markdown,
    write_vault,
)


def _pyproject(tmp: Path) -> None:
    (tmp / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")


def _seed_stores(tmp: Path) -> dict[str, str]:
    """Plant three real stores; return their rel-path -> raw text (for the
    untouched-originals assertion)."""
    apex = tmp / ".apex"
    apex.mkdir()
    idea = {"by_operator": {"implement_stub": {"total": 3, "applied": 2}},
            "schema": 1}
    (apex / "idea-memory.json").write_text(
        json.dumps(idea, indent=2), encoding="utf-8")
    journal = [{"round": 1, "landed": 2}, {"round": 2, "landed": 0}]
    (apex / "dream-journal.json").write_text(
        json.dumps(journal), encoding="utf-8")
    (apex / "dream-digest.md").write_text(
        "# Dream digest\n\nÜtopik değil — kanıtlı.\n", encoding="utf-8")
    return {rel: (tmp / rel).read_text(encoding="utf-8")
            for rel in (".apex/idea-memory.json", ".apex/dream-journal.json",
                        ".apex/dream-digest.md")}


# --------------------------------------------------------------------------- #
# Honest empties
# --------------------------------------------------------------------------- #


def test_bare_project_yields_all_absent_sections(tmp_path: Path):
    _pyproject(tmp_path)
    view = load_vault_view(tmp_path)
    assert view["schema_version"] == 1
    # CONSCIOUS PIN MOVE (living-assistant polish): the section set gains
    # "epistemic_memory" — the seventh section, mirroring the
    # `.epistemic/memory.json` artifact (6 -> 7; see
    # tests/test_vault_epistemic_section_eyml.py for its contract) — and then
    # "manifesto" — the eighth, DERIVED section synthesising the project's learned
    # architectural laws (7 -> 8; see tests/test_vault_manifesto_eyml.py).
    assert set(view["sections"]) == {
        "idea_memory", "dream_journal", "dream_digest",
        "proof_of_fix", "track_record", "agenda", "epistemic_memory",
        "manifesto"}
    assert all(not s["present"] for s in view["sections"].values())
    md = render_vault_markdown(view)
    # CONSCIOUS PIN MOVE: 0/6 -> 0/7 (epistemic) -> 0/8 (manifesto joined).
    assert "0/8 memory store(s) present" in md
    assert "No memory yet" in md


# --------------------------------------------------------------------------- #
# Lossless mirror + untouched originals (single-writer)
# --------------------------------------------------------------------------- #


def test_vault_mirrors_stores_losslessly_and_never_touches_them(tmp_path: Path):
    _pyproject(tmp_path)
    originals = _seed_stores(tmp_path)

    path = write_vault(tmp_path)
    assert path == tmp_path / VAULT_REL

    vault = json.loads(path.read_text(encoding="utf-8"))
    sections = vault["sections"]
    # Raw passthrough: the mirrored payload equals the store's own JSON.
    assert sections["idea_memory"]["data"] == json.loads(
        originals[".apex/idea-memory.json"])
    assert sections["dream_journal"]["data"] == json.loads(
        originals[".apex/dream-journal.json"])
    assert sections["dream_digest"]["text"] == originals[".apex/dream-digest.md"]
    # No proof evidence was planted: absent + track record honestly derived-absent.
    assert sections["proof_of_fix"]["present"] is False
    assert sections["track_record"]["present"] is False

    # Single-writer/additive: every source store is byte-identical afterwards.
    for rel, before in originals.items():
        assert (tmp_path / rel).read_text(encoding="utf-8") == before


def test_vault_is_rebuildable_after_deletion(tmp_path: Path):
    _pyproject(tmp_path)
    _seed_stores(tmp_path)
    first = write_vault(tmp_path).read_text(encoding="utf-8")
    (tmp_path / VAULT_REL).unlink()
    assert write_vault(tmp_path).read_text(encoding="utf-8") == first


# --------------------------------------------------------------------------- #
# Byte-determinism
# --------------------------------------------------------------------------- #


def test_write_twice_is_byte_identical(tmp_path: Path):
    _pyproject(tmp_path)
    _seed_stores(tmp_path)
    a = write_vault(tmp_path).read_bytes()
    b = write_vault(tmp_path).read_bytes()
    assert a == b


def test_unreadable_store_is_surfaced_not_dropped(tmp_path: Path):
    _pyproject(tmp_path)
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "idea-memory.json").write_text(
        "{not valid json", encoding="utf-8")
    section = load_vault_view(tmp_path)["sections"]["idea_memory"]
    assert section["present"] is True
    assert section["readable"] is False
    assert "unreadable" in render_vault_markdown(load_vault_view(tmp_path))


# --------------------------------------------------------------------------- #
# CLI seam
# --------------------------------------------------------------------------- #


def test_cmd_vault_refresh_writes_and_prints_summary(tmp_path: Path, capsys):
    import argparse

    from app.cli_insight import cmd_vault

    _pyproject(tmp_path)
    _seed_stores(tmp_path)
    rc = cmd_vault(argparse.Namespace(
        target=str(tmp_path), json=False, refresh=True))
    assert rc == 0
    out = capsys.readouterr().out
    # CONSCIOUS PIN MOVE: 3/6 -> 3/7 (epistemic) -> 3/8 (manifesto joined the
    # vault; neither a .epistemic artifact nor any proof-of-fix history is seeded
    # here, so the derived manifesto is absent and the present-count stays 3).
    assert "3/8 memory store(s) present" in out
    assert (tmp_path / VAULT_REL).exists()


def test_cmd_vault_json_is_sorted_deterministic(tmp_path: Path, capsys):
    import argparse

    from app.cli_insight import cmd_vault

    _pyproject(tmp_path)
    _seed_stores(tmp_path)
    ns = argparse.Namespace(target=str(tmp_path), json=True, refresh=False)
    assert cmd_vault(ns) == 0
    first = capsys.readouterr().out
    assert cmd_vault(ns) == 0
    assert capsys.readouterr().out == first
    parsed = json.loads(first)
    assert parsed["sections"]["dream_journal"]["data"][0]["round"] == 1
