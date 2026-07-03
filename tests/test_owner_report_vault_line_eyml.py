"""The owner report's vault line (living-assistant polish, ÇAĞ2-W4).

``_vault_for`` reads the TARGET project's ``.apex/vault/vault.json`` artifact —
directly as bytes, never through ``app.memory.vault`` and never by re-running the
underlying store reads — mirroring ``_agenda_for``'s cyclic-import discipline
exactly. ``_vault_line`` renders it as ONE owner-readable sentence placed
immediately AFTER the agenda line (and before the closing promise line). Pinned
here:

* absent / corrupt / degenerate artifacts -> the honest, byte-stable "no vault
  artifact yet" fallback (never a fabricated memory count);
* a readable artifact -> "remembered/total" memory-store count, plus the buyer's
  own queued ``#apex-hedef`` note count when non-zero;
* ``--target`` semantics: the vault (like the agenda and the track record, and
  unlike the soundness self-audit) is about the buyer's OWN project — pinned
  through a STUBBED-audit composition so no test pays for the slow full-tree
  audits;
* reading never mutates the artifact (the vault module stays its one writer).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.reporting.owner_report import (
    _NO_VAULT_LINE,
    _vault_for,
    _vault_line,
    owner_report,
    render_owner_report_markdown,
)

_VAULT_REL = ".apex/vault/vault.json"


def _seed_vault(tmp: Path, payload=None) -> str:
    """Write a realistic vault artifact (the shape ``write_vault`` produces);
    return its exact text. Default: 4/6 sections present, 2 queued user notes —
    the concrete scenario the dispatch brief names."""
    if payload is None:
        payload = {
            "schema_version": 1,
            "sections": {
                "idea_memory": {"present": True, "source": ".apex/idea-memory.json",
                                "readable": True, "data": {"by_operator": {}}},
                "dream_journal": {"present": True,
                                  "source": ".apex/dream-journal.json",
                                  "readable": True, "data": []},
                "dream_digest": {"present": True, "source": ".apex/dream-digest.md",
                                 "readable": True, "text": "# digest\n"},
                "proof_of_fix": {"present": False,
                                 "source": ".apex/proof-of-fix.json"},
                "track_record": {"present": False,
                                 "derived_from": ".apex/proof-of-fix.json"},
                "agenda": {"present": True, "source": ".apex/agenda.json",
                          "readable": True, "landable": 3, "human": 1,
                          "watched": 0, "user": 2, "retired": []},
            },
        }
    (tmp / ".apex" / "vault").mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, sort_keys=True, indent=1,
                      ensure_ascii=False) + "\n"
    (tmp / _VAULT_REL).write_text(text, encoding="utf-8")
    return text


def _crafted_report(**overrides) -> dict:
    """A hand-built report dict (no audits run) for pure render tests."""
    report = {
        "trustworthy": True,
        "north_star": {"verdict": "PASS", "drift": False,
                       "concrete_count": 24, "total_objectives": 66,
                       "ratio": 0.35},
        "soundness": {"verdict": "PASS", "strategies": "66/66",
                      "single_writer": True, "scope_verify_ok": True},
        "grade": {"letter": "A+", "score": 99},
        "capabilities": {"concrete_count": 24, "languages": ["Python"],
                         "abilities": ["filling in unfinished functions"]},
    }
    report.update(overrides)
    return report


# --------------------------------------------------------------------------- #
# _vault_for: the artifact read (absent / corrupt / readable / degenerate)
# --------------------------------------------------------------------------- #


def test_vault_for_absent_artifact_is_honest_default(tmp_path: Path):
    assert _vault_for(tmp_path) == {
        "present": False, "readable": False, "remembered": 0,
        "total": 0, "user_notes": 0}


def test_vault_for_corrupt_artifact_is_present_unreadable(tmp_path: Path):
    (tmp_path / ".apex" / "vault").mkdir(parents=True)
    (tmp_path / _VAULT_REL).write_text("{not valid json", encoding="utf-8")
    assert _vault_for(tmp_path) == {
        "present": True, "readable": False, "remembered": 0,
        "total": 0, "user_notes": 0}


def test_vault_for_non_dict_payload_is_unreadable(tmp_path: Path):
    """Parseable but non-object bytes are NOT the vault schema — honest
    unreadable, never guessed at."""
    (tmp_path / ".apex" / "vault").mkdir(parents=True)
    (tmp_path / _VAULT_REL).write_text("[1, 2]\n", encoding="utf-8")
    assert _vault_for(tmp_path) == {
        "present": True, "readable": False, "remembered": 0,
        "total": 0, "user_notes": 0}


def test_vault_for_readable_artifact_counts_remembered_and_user_notes(
        tmp_path: Path):
    _seed_vault(tmp_path)
    assert _vault_for(tmp_path) == {
        "present": True, "readable": True,
        "remembered": 4, "total": 6, "user_notes": 2}


def test_vault_for_all_absent_sections_has_zero_counts(tmp_path: Path):
    """Edge/empty path: a fresh vault (every section absent) reads as honest
    zeroes — readable, not absent, and the total still reflects the real
    section count."""
    payload = {
        "schema_version": 1,
        "sections": {
            "idea_memory": {"present": False, "source": ".apex/idea-memory.json"},
            "dream_journal": {"present": False,
                              "source": ".apex/dream-journal.json"},
            "dream_digest": {"present": False, "source": ".apex/dream-digest.md"},
            "proof_of_fix": {"present": False, "source": ".apex/proof-of-fix.json"},
            "track_record": {"present": False,
                             "derived_from": ".apex/proof-of-fix.json"},
            "agenda": {"present": False, "source": ".apex/agenda.json"},
        },
    }
    _seed_vault(tmp_path, payload)
    assert _vault_for(tmp_path) == {
        "present": True, "readable": True,
        "remembered": 0, "total": 6, "user_notes": 0}


def test_vault_for_degenerate_shape_is_tolerated_never_raises(tmp_path: Path):
    """A dict artifact whose ``sections`` is missing (or non-dict), or whose
    ``agenda`` sub-section carries no ``user`` key, still reads: the vault
    reader is a leaf and never validates the vault module's format on its
    behalf."""
    _seed_vault(tmp_path, {"schema_version": 1, "sections": "??"})
    assert _vault_for(tmp_path) == {
        "present": True, "readable": True,
        "remembered": 0, "total": 0, "user_notes": 0}
    _seed_vault(tmp_path, {"schema_version": 1})  # no sections key at all
    assert _vault_for(tmp_path) == {
        "present": True, "readable": True,
        "remembered": 0, "total": 0, "user_notes": 0}
    _seed_vault(tmp_path, {"schema_version": 1, "sections": {
        "idea_memory": {"present": True},
        "agenda": {"present": True},  # no "user" key
    }})
    got = _vault_for(tmp_path)
    assert got == {"present": True, "readable": True,
                   "remembered": 2, "total": 2, "user_notes": 0}


def test_vault_for_leaves_artifact_bytes_untouched(tmp_path: Path):
    original = _seed_vault(tmp_path)
    _vault_for(tmp_path)
    assert (tmp_path / _VAULT_REL).read_text(encoding="utf-8") == original


# --------------------------------------------------------------------------- #
# _vault_line: one sentence, honest fallback
# --------------------------------------------------------------------------- #


def test_vault_line_missing_key_renders_fallback():
    """An older/hand-built report dict with no "vault" key at all renders the
    fallback — defensive against pre-feature dicts, like the agenda line."""
    assert _vault_line({}) == _NO_VAULT_LINE


def test_vault_line_absent_and_unreadable_render_fallback():
    absent = {"present": False, "readable": False, "remembered": 0,
             "total": 0, "user_notes": 0}
    corrupt = {"present": True, "readable": False, "remembered": 0,
              "total": 0, "user_notes": 0}
    assert _vault_line({"vault": absent}) == _NO_VAULT_LINE
    assert _vault_line({"vault": corrupt}) == _NO_VAULT_LINE
    # The fallback is the exact honest sentence, byte-stable.
    assert _NO_VAULT_LINE == (
        "- Memory (vault): no vault artifact yet (run apex vault or the daemon).")


def test_vault_line_readable_names_remembered_and_user_notes():
    report = {"vault": {"present": True, "readable": True,
                        "remembered": 4, "total": 6, "user_notes": 2}}
    assert _vault_line(report) == (
        "- Memory (vault): Apex remembers 4/6 memory store(s) for this "
        "project, 2 of them your own notes — full picture: `apex vault`.")


def test_vault_line_singular_note_wording():
    """One queued note reads "1 ... note", not "1 ... notes" — plain grammar."""
    report = {"vault": {"present": True, "readable": True,
                        "remembered": 1, "total": 6, "user_notes": 1}}
    line = _vault_line(report)
    assert "1 of them your own note —" in line
    assert "notes" not in line


def test_vault_line_zero_user_notes_has_no_dangling_clause():
    """Zero queued notes -> the sentence states remembered/total only, with no
    half-empty ", 0 of them your own note(s)" fragment."""
    report = {"vault": {"present": True, "readable": True,
                        "remembered": 0, "total": 6, "user_notes": 0}}
    line = _vault_line(report)
    assert line == ("- Memory (vault): Apex remembers 0/6 memory store(s) for "
                    "this project — full picture: `apex vault`.")
    assert "your own note" not in line


# --------------------------------------------------------------------------- #
# Render placement: immediately AFTER the agenda line, BEFORE the promise line
# --------------------------------------------------------------------------- #


def _line_indices(md: str) -> tuple[int, int, int]:
    lines = md.splitlines()
    agenda_idx = next(i for i, ln in enumerate(lines)
                      if ln.startswith("- Next up (agenda):"))
    vault_idx = next(i for i, ln in enumerate(lines)
                     if ln.startswith("- Memory (vault):"))
    promise_idx = next(i for i, ln in enumerate(lines)
                       if ln.startswith("- The promise"))
    return agenda_idx, vault_idx, promise_idx


def test_render_places_vault_line_immediately_after_agenda_before_promise():
    report = _crafted_report(
        agenda={"present": True, "readable": True, "landable": 2,
               "rank1": {"fix_kind": "implement-stub", "file": "app/a.py"}},
        vault={"present": True, "readable": True,
              "remembered": 4, "total": 6, "user_notes": 2})
    md = render_owner_report_markdown(report)
    assert ("Apex remembers 4/6 memory store(s) for this project, 2 of them "
            "your own notes") in md
    agenda_idx, vault_idx, promise_idx = _line_indices(md)
    assert vault_idx == agenda_idx + 1
    assert promise_idx == vault_idx + 1


def test_render_without_vault_key_places_fallback_between_agenda_and_promise():
    md = render_owner_report_markdown(_crafted_report())
    assert _NO_VAULT_LINE in md
    agenda_idx, vault_idx, promise_idx = _line_indices(md)
    assert vault_idx == agenda_idx + 1
    assert promise_idx == vault_idx + 1


# --------------------------------------------------------------------------- #
# Composition seam (--target semantics), audits STUBBED for speed
# --------------------------------------------------------------------------- #


@pytest.fixture()
def stub_audits(monkeypatch):
    """Stub the three heavy audits ``owner_report`` composes, recording the
    root each one received — so the composition seam and its --target
    semantics are pinned WITHOUT the ~60s full-tree audits."""
    import app.engine.health_score as health_score
    import app.engine.north_star_audit as north_star_audit
    import app.engine.soundness_audit as soundness_audit

    seen: dict[str, str] = {}

    def fake_north_star(root):
        seen["north_star_root"] = root
        return {"verdict": "PASS", "drift": False,
                "bucket_counts": {"CONCRETE": 1},
                "buckets": {"CONCRETE": ["implement-stub"]},
                "total_objectives": 1, "concrete_ratio": 1.0}

    def fake_soundness(root):
        seen["soundness_root"] = root
        return {"verdict": "PASS", "strategy_table": [{"name": "implement-stub"}],
                "total_objectives": 1, "single_writer_ok": True,
                "scope_verify_ok": True}

    def fake_grade(root):
        seen["grade_root"] = root
        return SimpleNamespace(letter="A+", score=100)

    monkeypatch.setattr(north_star_audit, "north_star_report", fake_north_star)
    monkeypatch.setattr(soundness_audit, "soundness_report", fake_soundness)
    monkeypatch.setattr(health_score, "grade", fake_grade)
    return seen


def test_stubbed_owner_report_reads_targets_own_vault(tmp_path: Path,
                                                       stub_audits):
    """--TARGET SEMANTICS PIN: the vault (like the agenda, the grade, the North
    Star read, and the track record) is resolved against the buyer's OWN
    project root — only the soundness self-audit stays on Apex's tree."""
    _seed_vault(tmp_path)
    report = owner_report(str(tmp_path))
    assert report["vault"] == {
        "present": True, "readable": True,
        "remembered": 4, "total": 6, "user_notes": 2}
    assert stub_audits["north_star_root"] == str(tmp_path)
    assert stub_audits["grade_root"] == str(tmp_path)
    assert stub_audits["soundness_root"] != str(tmp_path)


def test_stubbed_owner_report_fresh_target_renders_fallback_line(
        tmp_path: Path, stub_audits):
    """A fresh target (no ``.apex/vault/vault.json``) composes the honest-absent
    vault dict and renders the fallback sentence end-to-end."""
    report = owner_report(str(tmp_path))
    assert report["vault"] == {
        "present": False, "readable": False, "remembered": 0,
        "total": 0, "user_notes": 0}
    md = render_owner_report_markdown(report)
    assert _NO_VAULT_LINE in md
    agenda_idx, vault_idx, promise_idx = _line_indices(md)
    assert vault_idx == agenda_idx + 1
    assert promise_idx == vault_idx + 1


def test_stubbed_owner_report_renders_remembered_count_end_to_end(
        tmp_path: Path, stub_audits):
    """Composition -> render, whole seam: the target's artifact becomes the one
    owner-facing sentence, byte-stable across two renders (clock-free)."""
    _seed_vault(tmp_path)
    report = owner_report(str(tmp_path))
    md = render_owner_report_markdown(report)
    assert ("- Memory (vault): Apex remembers 4/6 memory store(s) for this "
            "project, 2 of them your own notes — full picture: "
            "`apex vault`.") in md
    assert md == render_owner_report_markdown(report)
