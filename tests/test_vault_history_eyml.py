"""The vault's timeline — `apex vault --save` / `apex vault --diff` (ÇAĞ2-W12).

The owner's "ben yokken ne değişti?" (what changed while I was away?) surface:
a deterministic snapshot + diff over the EXISTING vault roll-up
(`app.memory.vault`). Mirrors `tests/test_memory_vault_eyml.py`'s style — real
throwaway-project fixtures, no mocks — plus the CLI seam.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli_insight import cmd_vault
from app.memory.vault import load_vault_view, write_vault
from app.memory.vault_history import (
    SNAPSHOTS_DIR_REL,
    available_indices,
    diff_vault,
    load_snapshot,
    render_vault_diff_markdown,
    save_snapshot,
)


def _pyproject(tmp: Path) -> None:
    (tmp / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")


def _write_idea_memory(tmp: Path, by_operator: dict) -> None:
    (tmp / ".apex").mkdir(exist_ok=True)
    (tmp / ".apex" / "idea-memory.json").write_text(
        json.dumps({"by_operator": by_operator, "schema": 1}, indent=2),
        encoding="utf-8")


def _write_journal(tmp: Path, rounds: list[dict]) -> None:
    (tmp / ".apex").mkdir(exist_ok=True)
    (tmp / ".apex" / "dream-journal.json").write_text(
        json.dumps(rounds), encoding="utf-8")


def _agenda_payload(landable=2, human=1, watched=2, user=1, retired=("risky-op",)) -> dict:
    return {
        "schema_version": 1,
        "lanes": {
            "landable": [{"file": f"app/f{i}.py", "line": i} for i in range(landable)],
            "human": [{"file": f"app/h{i}.py", "line": i} for i in range(human)],
            "watched": [{"operator": op, "retired": True, "note": f"retired: {op}"}
                        for op in retired] + [
                {"operator": f"meh{i}", "feasibility": 0.95} for i in range(watched)],
            "user": [{"file": f".apex/vault/notes/n{i}.md", "valid": True,
                      "request": f"do {i}"} for i in range(user)],
        },
    }


def _write_agenda(tmp: Path, payload: dict) -> None:
    (tmp / ".apex").mkdir(exist_ok=True)
    (tmp / ".apex" / "agenda.json").write_text(
        json.dumps(payload, sort_keys=True, indent=1) + "\n", encoding="utf-8")


def _proof_fix(action: str, outcome: str, target: str = "app/x.py") -> dict:
    return {"finding": {"action": action, "target": target}, "outcome": outcome}


def _write_proof(tmp: Path, fixes: list[dict]) -> None:
    (tmp / ".apex").mkdir(exist_ok=True)
    proof = {
        "schema": "apex-proof-of-fix",
        "schema_version": 1,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "objective": "test",
        "mode": "maintain",
        "verify": True,
        "totals": {},
        "fixes": fixes,
    }
    (tmp / ".apex" / "proof-of-fix.json").write_text(
        json.dumps(proof, indent=2), encoding="utf-8")


def _run(target: Path, **kw) -> tuple[int, str]:
    import contextlib
    import io

    ns = argparse.Namespace(target=str(target), json=kw.pop("json", False),
                            refresh=kw.pop("refresh", False),
                            diff=kw.pop("diff", None), save=kw.pop("save", None))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_vault(ns)
    return rc, buf.getvalue()


# --------------------------------------------------------------------------- #
# Honest empties (no snapshot yet)
# --------------------------------------------------------------------------- #


def test_load_snapshot_and_available_indices_are_honest_on_a_bare_project(tmp_path: Path):
    _pyproject(tmp_path)
    assert load_snapshot(tmp_path) is None
    assert load_snapshot(tmp_path, index=1) is None
    assert available_indices(tmp_path) == []


def test_cmd_vault_diff_with_no_snapshot_is_honest_and_exits_zero(tmp_path: Path):
    _pyproject(tmp_path)
    rc, out = _run(tmp_path, diff="")
    assert rc == 0
    assert "No snapshot saved yet" in out
    assert "apex vault --save" in out
    # Honest fallback: the (empty) live vault is still shown, not nothing.
    assert "memory store(s) present" in out


def test_cmd_vault_diff_bad_explicit_index_is_honest_and_exits_zero(tmp_path: Path):
    _pyproject(tmp_path)
    write_vault(tmp_path)
    save_snapshot(tmp_path, load_vault_view(tmp_path))
    rc, out = _run(tmp_path, diff="5")
    assert rc == 0
    assert "No snapshot #5 found" in out
    assert "available: 1" in out


def test_cmd_vault_diff_non_numeric_index_is_honest_and_exits_zero(tmp_path: Path):
    _pyproject(tmp_path)
    rc, out = _run(tmp_path, diff="abc")
    assert rc == 0
    assert "not a valid snapshot index" in out


# --------------------------------------------------------------------------- #
# Save: monotonic index, no wall-clock, own writer domain
# --------------------------------------------------------------------------- #


def test_save_snapshot_starts_at_one_and_increments(tmp_path: Path):
    _pyproject(tmp_path)
    view = load_vault_view(tmp_path)
    first = save_snapshot(tmp_path, view)
    second = save_snapshot(tmp_path, view)
    assert first["index"] == 1
    assert second["index"] == 2
    assert available_indices(tmp_path) == [1, 2]
    assert (tmp_path / SNAPSHOTS_DIR_REL / "1.json").exists()
    assert (tmp_path / SNAPSHOTS_DIR_REL / "2.json").exists()


def test_save_snapshot_content_has_no_timestamp_field(tmp_path: Path):
    _pyproject(tmp_path)
    view = load_vault_view(tmp_path)
    ref = save_snapshot(tmp_path, view, label="before trip")
    raw = ref["path"].read_text(encoding="utf-8")
    assert '"index": 1' in raw
    assert '"label": "before trip"' in raw
    for needle in ("time", "clock", "date", "generated_at"):
        assert needle not in raw
    parsed = json.loads(raw)
    assert parsed == {"index": 1, "label": "before trip", "view": view}


def test_load_snapshot_default_is_latest(tmp_path: Path):
    _pyproject(tmp_path)
    view = load_vault_view(tmp_path)
    save_snapshot(tmp_path, view, label="one")
    save_snapshot(tmp_path, view, label="two")
    latest = load_snapshot(tmp_path)
    assert latest["index"] == 2
    assert latest["label"] == "two"
    assert load_snapshot(tmp_path, index=1)["label"] == "one"
    assert load_snapshot(tmp_path, index=99) is None


def test_save_never_touches_source_stores_or_vault_json(tmp_path: Path):
    _pyproject(tmp_path)
    _write_idea_memory(tmp_path, {"implement_stub": {"total": 3, "applied": 2}})
    write_vault(tmp_path)
    vault_before = (tmp_path / ".apex" / "vault" / "vault.json").read_bytes()
    idea_before = (tmp_path / ".apex" / "idea-memory.json").read_bytes()
    save_snapshot(tmp_path, load_vault_view(tmp_path))
    assert (tmp_path / ".apex" / "vault" / "vault.json").read_bytes() == vault_before
    assert (tmp_path / ".apex" / "idea-memory.json").read_bytes() == idea_before


# --------------------------------------------------------------------------- #
# save -> diff, no change: the honest byte-pinned "nothing changed" line
# --------------------------------------------------------------------------- #


def test_save_then_diff_with_no_change_is_byte_pinned(tmp_path: Path):
    _pyproject(tmp_path)
    _write_idea_memory(tmp_path, {"implement_stub": {"total": 3, "applied": 2}})
    _write_journal(tmp_path, [{"round": 1, "landed": 2}])
    view = load_vault_view(tmp_path)
    save_snapshot(tmp_path, view)

    snapshot = load_snapshot(tmp_path)
    diff = diff_vault(snapshot["view"], load_vault_view(tmp_path))
    assert diff.unchanged is True
    rendered = render_vault_diff_markdown(diff, snapshot["index"], snapshot.get("label", ""))
    assert rendered == (
        "_Nothing changed since snapshot #1 — the live vault is byte-identical._\n"
    )


def test_cmd_vault_save_then_diff_cli_seam_no_change(tmp_path: Path):
    _write_idea_memory(tmp_path, {"implement_stub": {"total": 3, "applied": 2}})
    rc, out = _run(tmp_path, save="")
    assert rc == 0
    assert "[vault] Snapshot #1 saved" in out
    assert "→" in out

    rc, out = _run(tmp_path, diff="")
    assert rc == 0
    assert "Nothing changed since snapshot #1" in out


def test_cmd_vault_save_with_label_is_echoed(tmp_path: Path):
    rc, out = _run(tmp_path, save="before big refactor")
    assert rc == 0
    assert '[vault] Snapshot #1 saved ("before big refactor")' in out


# --------------------------------------------------------------------------- #
# A real change: added/removed/changed counts, per store shape
# --------------------------------------------------------------------------- #


def test_diff_reports_dict_store_growth_as_added_and_changed(tmp_path: Path):
    _pyproject(tmp_path)
    _write_idea_memory(tmp_path, {"implement_stub": {"total": 3, "applied": 2}})
    prev = load_vault_view(tmp_path)

    # A pre-existing operator's stat CHANGES, and a brand new operator APPEARS.
    _write_idea_memory(tmp_path, {
        "implement_stub": {"total": 3, "applied": 3},
        "harden_security": {"total": 1, "applied": 1},
    })
    curr = load_vault_view(tmp_path)

    diff = diff_vault(prev, curr)
    section = {s.name: s for s in diff.sections}["idea_memory"]
    assert section.changed == 1     # implement_stub.applied: 2 -> 3
    assert section.added == 2       # harden_security.{total,applied}: 2 new leaves
    assert section.removed == 0
    assert diff.unchanged is False


def test_diff_reports_list_store_growth_as_order_insensitive_added(tmp_path: Path):
    _pyproject(tmp_path)
    _write_journal(tmp_path, [{"round": 1, "landed": 2}])
    prev = load_vault_view(tmp_path)

    _write_journal(tmp_path, [{"round": 1, "landed": 2}, {"round": 2, "landed": 0}])
    curr = load_vault_view(tmp_path)

    diff = diff_vault(prev, curr)
    section = {s.name: s for s in diff.sections}["dream_journal"]
    assert section.added == 1
    assert section.removed == 0
    assert section.changed == 0  # lists never contribute to "changed"


def test_diff_reports_absent_to_present_transition(tmp_path: Path):
    _pyproject(tmp_path)
    prev = load_vault_view(tmp_path)
    assert prev["sections"]["idea_memory"]["present"] is False

    _write_idea_memory(tmp_path, {"implement_stub": {"total": 1, "applied": 1}})
    curr = load_vault_view(tmp_path)

    diff = diff_vault(prev, curr)
    section = {s.name: s for s in diff.sections}["idea_memory"]
    assert section.changed == 1   # "present": False -> True
    assert section.added > 0      # "readable" + the new data leaves
    assert section.removed == 0


def test_stable_sections_are_not_rendered(tmp_path: Path):
    _pyproject(tmp_path)
    _write_idea_memory(tmp_path, {"implement_stub": {"total": 3, "applied": 2}})
    (tmp_path / ".apex" / "dream-digest.md").write_text(
        "# Dream digest\n\nsteady state\n", encoding="utf-8")
    prev = load_vault_view(tmp_path)

    _write_idea_memory(tmp_path, {"implement_stub": {"total": 3, "applied": 3}})
    curr = load_vault_view(tmp_path)

    diff = diff_vault(prev, curr)
    rendered = render_vault_diff_markdown(diff, 1)
    assert "idea_memory" in rendered
    assert "dream_digest" not in rendered  # untouched store: no line at all


def test_cmd_vault_diff_cli_shows_real_change(tmp_path: Path):
    _write_idea_memory(tmp_path, {"implement_stub": {"total": 3, "applied": 2}})
    rc, out = _run(tmp_path, save="")
    assert rc == 0

    _write_idea_memory(tmp_path, {"implement_stub": {"total": 3, "applied": 3},
                                  "harden_security": {"total": 1, "applied": 1}})
    rc, out = _run(tmp_path, diff="1")
    assert rc == 0
    assert "what changed since snapshot #1" in out
    assert "idea_memory" in out
    assert "added" in out and "changed" in out


# --------------------------------------------------------------------------- #
# agenda / track_record headline movements
# --------------------------------------------------------------------------- #


def test_agenda_headline_reports_lane_movement_and_new_retirements(tmp_path: Path):
    _pyproject(tmp_path)
    _write_agenda(tmp_path, _agenda_payload(landable=2, retired=("risky-op",)))
    prev = load_vault_view(tmp_path)

    _write_agenda(tmp_path, _agenda_payload(landable=5, retired=("risky-op", "meh-op")))
    curr = load_vault_view(tmp_path)

    diff = diff_vault(prev, curr)
    section = {s.name: s for s in diff.sections}["agenda"]
    assert "landable 2→5" in section.headline
    assert "newly retired: meh-op" in section.headline
    # An operator retired in BOTH snapshots is not re-announced.
    assert section.headline.count("risky-op") == 0


def test_agenda_headline_empty_when_agenda_absent_on_either_side(tmp_path: Path):
    _pyproject(tmp_path)
    prev = load_vault_view(tmp_path)  # agenda absent
    _write_agenda(tmp_path, _agenda_payload())
    curr = load_vault_view(tmp_path)
    diff = diff_vault(prev, curr)
    section = {s.name: s for s in diff.sections}["agenda"]
    assert section.headline == ""     # generic counts already tell this story
    assert section.added > 0          # but the section is NOT reported stable


def test_track_record_headline_reports_reliability_and_fix_count_movement(tmp_path: Path):
    _pyproject(tmp_path)
    _write_proof(tmp_path, [_proof_fix("remove_unused", "applied")])
    prev = load_vault_view(tmp_path)

    _write_proof(tmp_path, [
        _proof_fix("remove_unused", "applied"),
        _proof_fix("harden", "applied"),
        _proof_fix("rewrite", "rolled_back"),
    ])
    curr = load_vault_view(tmp_path)

    diff = diff_vault(prev, curr)
    section = {s.name: s for s in diff.sections}["track_record"]
    assert "total 1→3" in section.headline
    assert "applied 1→2" in section.headline
    assert "rolled_back" in section.headline
    assert "reliability" in section.headline


def test_track_record_headline_empty_when_absent_on_either_side(tmp_path: Path):
    _pyproject(tmp_path)
    prev = load_vault_view(tmp_path)
    _write_proof(tmp_path, [_proof_fix("remove_unused", "applied")])
    curr = load_vault_view(tmp_path)
    diff = diff_vault(prev, curr)
    section = {s.name: s for s in diff.sections}["track_record"]
    assert section.headline == ""


# --------------------------------------------------------------------------- #
# --json mirrors the same honest data
# --------------------------------------------------------------------------- #


def test_cmd_vault_diff_json_shape(tmp_path: Path):
    _write_idea_memory(tmp_path, {"implement_stub": {"total": 3, "applied": 2}})
    _run(tmp_path, save="")
    rc, out = _run(tmp_path, diff="", json=True)
    assert rc == 0
    data = json.loads(out)
    assert data["snapshot_index"] == 1
    assert data["unchanged"] is True
    assert "idea_memory" in data["sections"]


def test_cmd_vault_diff_json_no_snapshot_falls_back_to_view_json(tmp_path: Path):
    _pyproject(tmp_path)
    rc, out = _run(tmp_path, diff="", json=True)
    assert rc == 0
    lines = out.strip().splitlines()
    assert lines[0].startswith("_No snapshot saved yet")
    view = json.loads("\n".join(lines[1:]))
    assert view["schema_version"] == 1


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_diff_output_is_byte_identical_across_repeated_runs(tmp_path: Path):
    _write_idea_memory(tmp_path, {"implement_stub": {"total": 3, "applied": 2}})
    _write_agenda(tmp_path, _agenda_payload())
    _write_proof(tmp_path, [_proof_fix("remove_unused", "applied")])
    _run(tmp_path, save="")
    _write_idea_memory(tmp_path, {"implement_stub": {"total": 3, "applied": 3}})

    _, first = _run(tmp_path, diff="1")
    _, second = _run(tmp_path, diff="1")
    assert first == second

    _, first_json = _run(tmp_path, diff="1", json=True)
    _, second_json = _run(tmp_path, diff="1", json=True)
    assert first_json == second_json


def test_diff_vault_is_a_pure_function_of_its_two_views():
    prev = {"schema_version": 1, "sections": {"idea_memory": {"present": False,
                                                               "source": "x"}}}
    curr = {"schema_version": 1, "sections": {"idea_memory": {
        "present": True, "source": "x", "readable": True, "data": {"a": 1}}}}
    d1 = diff_vault(prev, curr)
    d2 = diff_vault(prev, curr)
    assert d1.to_dict() == d2.to_dict()


# --------------------------------------------------------------------------- #
# Backward compatibility: existing Namespaces without save/diff still work
# --------------------------------------------------------------------------- #


def test_cmd_vault_without_save_or_diff_attrs_is_unaffected(tmp_path: Path, capsys):
    # Mirrors the pre-existing Namespace shape from test_memory_vault_eyml.py —
    # no `save`/`diff` attributes at all (an older caller/test).
    rc = cmd_vault(argparse.Namespace(target=str(tmp_path), json=False, refresh=True))
    assert rc == 0
    assert not (tmp_path / SNAPSHOTS_DIR_REL).exists()


# --------------------------------------------------------------------------- #
# CLI surface pin
# --------------------------------------------------------------------------- #


def test_vault_parser_save_and_diff_surface():
    import app.cli_insight as cli_insight

    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    cli_insight.register_parsers(sub)
    vault_parser = sub.choices["vault"]

    bare = vault_parser.parse_args([])
    assert bare.save is None
    assert bare.diff is None

    flag_only = vault_parser.parse_args(["--save"])
    assert flag_only.save == ""

    labeled = vault_parser.parse_args(["--save", "before trip"])
    assert labeled.save == "before trip"

    diff_only = vault_parser.parse_args(["--diff"])
    assert diff_only.diff == ""

    diff_indexed = vault_parser.parse_args(["--diff", "3"])
    assert diff_indexed.diff == "3"

    assert sub.choices["vault"].get_default("func") is cli_insight.cmd_vault
