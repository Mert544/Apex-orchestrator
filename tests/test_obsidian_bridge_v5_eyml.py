"""V5 Obsidian-bridge contracts: user notes enter the agenda honestly.

A ``*.md`` under ``.apex/vault/notes/`` with a ``#apex-hedef <request>`` line
becomes an agenda candidate in the user's own words; a tagged note with no
request is REJECTED with a reason (never guessed at); untagged files are none
of Apex's business; the reader is read-only and deterministic; and the
assist hand-off (``--from-notes``) drives the normal pipeline preview-first.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.memory.vault import NOTES_DIR_REL, read_user_notes


def _pyproject(tmp: Path) -> None:
    (tmp / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")


def _note(tmp: Path, name: str, body: str) -> Path:
    notes = tmp / NOTES_DIR_REL
    notes.mkdir(parents=True, exist_ok=True)
    path = notes / name
    path.write_text(body, encoding="utf-8")
    return path


def test_valid_note_yields_request(tmp_path: Path):
    _pyproject(tmp_path)
    _note(tmp_path, "hedef.md",
          "# Planlarım\n\n#apex-hedef auth modülüne type hint ekle\n")
    notes = read_user_notes(tmp_path)
    assert notes == [{"file": f"{NOTES_DIR_REL}/hedef.md", "valid": True,
                      "request": "auth modülüne type hint ekle"}]


def test_tagged_but_empty_request_is_rejected_with_reason(tmp_path: Path):
    _pyproject(tmp_path)
    _note(tmp_path, "bos.md", "notlar\n#apex-hedef   \n")
    notes = read_user_notes(tmp_path)
    assert notes[0]["valid"] is False
    assert "empty request" in notes[0]["reason"]


def test_untagged_files_are_not_apexs_business(tmp_path: Path):
    _pyproject(tmp_path)
    _note(tmp_path, "gunluk.md", "bugün hava güzeldi\n")
    assert read_user_notes(tmp_path) == []


def test_extra_tag_lines_are_counted_not_dropped(tmp_path: Path):
    _pyproject(tmp_path)
    _note(tmp_path, "cok.md",
          "#apex-hedef ilk istek\n#apex-hedef ikinci istek\n")
    notes = read_user_notes(tmp_path)
    assert notes[0]["request"] == "ilk istek"
    assert notes[0]["extra_tags"] == 1


def test_reader_is_readonly_and_deterministic(tmp_path: Path):
    _pyproject(tmp_path)
    path = _note(tmp_path, "a.md", "#apex-hedef bir\n")
    _note(tmp_path, "b.md", "#apex-hedef iki\n")
    before = path.read_bytes()
    first = read_user_notes(tmp_path)
    second = read_user_notes(tmp_path)
    assert first == second
    assert [n["file"].rsplit("/", 1)[1] for n in first] == ["a.md", "b.md"]
    assert path.read_bytes() == before  # untouched source


def test_agenda_carries_the_user_lane(tmp_path: Path, monkeypatch):
    import app.engine.agenda as agenda_mod

    _pyproject(tmp_path)
    _note(tmp_path, "hedef.md", "#apex-hedef readme'yi tazele\n")
    monkeypatch.setattr(agenda_mod, "develop_readiness",
                        lambda root, weight_by_reliability: {
                            "score": 0.0, "total": 0,
                            "buckets": {"fixable_now": [], "flag_only": [],
                                        "unknown": []}})
    agenda = agenda_mod.build_agenda(tmp_path)
    assert agenda["lanes"]["user"][0]["request"] == "readme'yi tazele"
    md = agenda_mod.render_agenda_markdown(agenda)
    assert "User notes (#apex-hedef)" in md
    assert "readme'yi tazele" in md


def _assist_ns(**overrides):
    ns = argparse.Namespace(request="", target="", apply=False, commit=False,
                            json=False, from_agenda=False, from_notes=True)
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


def test_from_notes_hands_first_valid_note_to_assist(tmp_path: Path, monkeypatch,
                                                     capsys):
    from app import cli as cli_mod

    _pyproject(tmp_path)
    _note(tmp_path, "bos.md", "#apex-hedef \n")
    _note(tmp_path, "hedef.md", "#apex-hedef util modülünü belgele\n")

    seen: dict[str, str] = {}

    class _Result:
        narrative = "ok"

        def to_dict(self):
            return {}

    import app.agent.assist as assist_mod
    monkeypatch.setattr(assist_mod, "assist",
                        lambda request, target="", apply=False, commit=False:
                        (seen.__setitem__("request", request), _Result())[1])
    rc = cli_mod.cmd_assist(_assist_ns(target=str(tmp_path)))
    assert rc == 0
    assert seen["request"] == "util modülünü belgele"
    assert "notes→assist" in capsys.readouterr().out


def test_from_notes_with_no_valid_notes_is_honest(tmp_path: Path, capsys):
    from app import cli as cli_mod

    _pyproject(tmp_path)
    _note(tmp_path, "bos.md", "#apex-hedef \n")
    rc = cli_mod.cmd_assist(_assist_ns(target=str(tmp_path)))
    assert rc == 0
    out = capsys.readouterr().out
    assert "REJECTED" in out and "empty request" in out
    assert "No valid #apex-hedef notes" in out
