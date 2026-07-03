"""The owner report's agenda line (living-assistant polish).

``_agenda_for`` reads the TARGET project's ``.apex/agenda.json`` artifact —
directly as bytes, never through ``app.engine.agenda`` and never by re-running
the readiness analysis — and ``_agenda_line`` renders it as ONE owner-readable
sentence placed immediately BEFORE the closing promise line. Pinned here:

* absent / corrupt / degenerate artifacts → the honest, byte-stable
  "no agenda artifact yet" fallback (never a fabricated next move);
* a readable artifact → the landable count and the rank-1 move by name;
* ``--target`` semantics: the agenda (like the track record, and unlike the
  soundness self-audit) is about the buyer's OWN project — pinned through a
  STUBBED-audit composition so no test pays for the slow full-tree audits;
* reading never mutates the artifact (the agenda module stays its one writer).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.reporting.owner_report import (
    _agenda_for,
    _agenda_line,
    _GENERIC_PROMISE,
    _NO_AGENDA_LINE,
    owner_report,
    render_owner_report_markdown,
)

_AGENDA_REL = ".apex/agenda.json"


def _seed_agenda(tmp: Path, payload=None) -> str:
    """Write a realistic agenda artifact; return its exact text."""
    if payload is None:
        payload = {
            "schema_version": 1,
            "readiness_score": 0.5,
            "total_findings": 3,
            "lanes": {
                "landable": [
                    {"fix_kind": "implement-stub", "file": "app/a.py",
                     "line": 3, "category": "todo", "value": 0.8, "rank": 1},
                    {"fix_kind": "infer-type-hints", "file": "app/b.py",
                     "line": 9, "category": "types", "value": 0.5, "rank": 2},
                ],
                "human": [], "watched": [], "user": [],
            },
        }
    (tmp / ".apex").mkdir(exist_ok=True)
    text = json.dumps(payload, sort_keys=True, indent=1,
                      ensure_ascii=False) + "\n"
    (tmp / _AGENDA_REL).write_text(text, encoding="utf-8")
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
# _agenda_for: the artifact read (absent / corrupt / readable / degenerate)
# --------------------------------------------------------------------------- #


def test_agenda_for_absent_artifact_is_honest_default(tmp_path: Path):
    assert _agenda_for(tmp_path) == {
        "present": False, "readable": False, "landable": 0, "rank1": None}


def test_agenda_for_corrupt_artifact_is_present_unreadable(tmp_path: Path):
    (tmp_path / ".apex").mkdir()
    (tmp_path / _AGENDA_REL).write_text("{not valid json", encoding="utf-8")
    assert _agenda_for(tmp_path) == {
        "present": True, "readable": False, "landable": 0, "rank1": None}


def test_agenda_for_non_dict_payload_is_unreadable(tmp_path: Path):
    """Parseable but non-object bytes are NOT the agenda schema — honest
    unreadable, never guessed at."""
    (tmp_path / ".apex").mkdir()
    (tmp_path / _AGENDA_REL).write_text("[1, 2]\n", encoding="utf-8")
    assert _agenda_for(tmp_path) == {
        "present": True, "readable": False, "landable": 0, "rank1": None}


def test_agenda_for_readable_artifact_names_the_rank_one_move(tmp_path: Path):
    _seed_agenda(tmp_path)
    assert _agenda_for(tmp_path) == {
        "present": True, "readable": True, "landable": 2,
        "rank1": {"fix_kind": "implement-stub", "file": "app/a.py"}}


def test_agenda_for_empty_landable_lane_has_no_rank_one(tmp_path: Path):
    _seed_agenda(tmp_path, {"schema_version": 1,
                            "lanes": {"landable": [], "human": [],
                                      "watched": [], "user": []}})
    assert _agenda_for(tmp_path) == {
        "present": True, "readable": True, "landable": 0, "rank1": None}


def test_agenda_for_degenerate_lanes_tolerated_never_raises(tmp_path: Path):
    """A dict artifact with lanes missing, lanes non-dict, or a landable lane
    that carries no rank-1 entry — all read defensively (this module is a
    leaf reader; the agenda engine owns the format)."""
    _seed_agenda(tmp_path, {"schema_version": 1})  # no lanes key
    assert _agenda_for(tmp_path) == {
        "present": True, "readable": True, "landable": 0, "rank1": None}
    _seed_agenda(tmp_path, {"schema_version": 1, "lanes": "??"})
    assert _agenda_for(tmp_path)["landable"] == 0
    _seed_agenda(tmp_path, {"schema_version": 1, "lanes": {"landable": [
        {"fix_kind": "x", "file": "a.py", "rank": 7}]}})
    got = _agenda_for(tmp_path)
    assert got["landable"] == 1 and got["rank1"] is None


def test_agenda_for_leaves_artifact_bytes_untouched(tmp_path: Path):
    original = _seed_agenda(tmp_path)
    _agenda_for(tmp_path)
    assert (tmp_path / _AGENDA_REL).read_text(encoding="utf-8") == original


# --------------------------------------------------------------------------- #
# _agenda_line: one sentence, honest fallback
# --------------------------------------------------------------------------- #


def test_agenda_line_missing_key_renders_fallback():
    """An older/hand-built report dict with no "agenda" key at all renders the
    fallback — defensive against pre-feature dicts, like the promise line."""
    assert _agenda_line({}) == _NO_AGENDA_LINE


def test_agenda_line_absent_and_unreadable_render_fallback():
    absent = {"present": False, "readable": False, "landable": 0, "rank1": None}
    corrupt = {"present": True, "readable": False, "landable": 0, "rank1": None}
    assert _agenda_line({"agenda": absent}) == _NO_AGENDA_LINE
    assert _agenda_line({"agenda": corrupt}) == _NO_AGENDA_LINE
    # The fallback is the exact honest sentence, byte-stable.
    assert _NO_AGENDA_LINE == ("- Next up (agenda): no agenda artifact yet "
                               "(run apex agenda or the daemon).")


def test_agenda_line_readable_names_count_and_rank_one():
    report = {"agenda": {"present": True, "readable": True, "landable": 2,
                         "rank1": {"fix_kind": "implement-stub",
                                   "file": "app/a.py"}}}
    assert _agenda_line(report) == (
        "- Next up (agenda): 2 landable move(s); "
        "rank-1: implement-stub in app/a.py.")


def test_agenda_line_zero_landable_has_no_dangling_rank_segment():
    report = {"agenda": {"present": True, "readable": True, "landable": 0,
                         "rank1": None}}
    line = _agenda_line(report)
    assert line == "- Next up (agenda): 0 landable move(s)."
    assert "rank-1" not in line


def test_agenda_line_landable_without_rank_one_stays_count_only():
    """Degenerate readable shape (entries but no rank-1): the count is still
    stated; no half-empty "rank-1: in " fragment ever renders."""
    report = {"agenda": {"present": True, "readable": True, "landable": 3,
                         "rank1": None}}
    assert _agenda_line(report) == "- Next up (agenda): 3 landable move(s)."


# --------------------------------------------------------------------------- #
# Render placement: immediately BEFORE the promise line
# --------------------------------------------------------------------------- #


def _line_indices(md: str) -> tuple[int, int]:
    lines = md.splitlines()
    agenda_idx = next(i for i, ln in enumerate(lines)
                      if ln.startswith("- Next up (agenda):"))
    promise_idx = next(i for i, ln in enumerate(lines)
                       if ln.startswith("- The promise"))
    return agenda_idx, promise_idx


def test_render_places_agenda_line_immediately_before_promise():
    report = _crafted_report(agenda={
        "present": True, "readable": True, "landable": 2,
        "rank1": {"fix_kind": "implement-stub", "file": "app/a.py"}})
    md = render_owner_report_markdown(report)
    assert "rank-1: implement-stub in app/a.py." in md
    agenda_idx, promise_idx = _line_indices(md)
    # ÇAĞ2-W4: promise_idx moved from agenda_idx + 1 to + 2 — the new vault
    # line (see tests/test_owner_report_vault_line_eyml.py) now sits between
    # the agenda line and the promise line.
    assert promise_idx == agenda_idx + 2


def test_render_without_agenda_key_places_fallback_before_promise():
    md = render_owner_report_markdown(_crafted_report())
    assert _NO_AGENDA_LINE in md
    assert _GENERIC_PROMISE in md  # the pre-feature dict keeps its old promise
    agenda_idx, promise_idx = _line_indices(md)
    # ÇAĞ2-W4: promise_idx moved from agenda_idx + 1 to + 2 (vault line joined
    # in between — a report dict predating the vault feature still renders
    # its own honest _NO_VAULT_LINE fallback there).
    assert promise_idx == agenda_idx + 2


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


def test_stubbed_owner_report_reads_targets_own_agenda(tmp_path: Path,
                                                       stub_audits):
    """--TARGET SEMANTICS PIN: the agenda (like the grade, the North Star read
    and the track record) is resolved against the buyer's OWN project root —
    only the soundness self-audit stays on Apex's tree."""
    _seed_agenda(tmp_path)
    report = owner_report(str(tmp_path))
    assert report["agenda"] == {
        "present": True, "readable": True, "landable": 2,
        "rank1": {"fix_kind": "implement-stub", "file": "app/a.py"}}
    # The per-target audits all received the target root...
    assert stub_audits["north_star_root"] == str(tmp_path)
    assert stub_audits["grade_root"] == str(tmp_path)
    # ...while soundness audited Apex's own tree (the one exception).
    assert stub_audits["soundness_root"] != str(tmp_path)


def test_stubbed_owner_report_fresh_target_renders_fallback_line(
        tmp_path: Path, stub_audits):
    """A fresh target (no ``.apex/agenda.json``) composes the honest-absent
    agenda dict and renders the fallback sentence end-to-end."""
    report = owner_report(str(tmp_path))
    assert report["agenda"] == {
        "present": False, "readable": False, "landable": 0, "rank1": None}
    md = render_owner_report_markdown(report)
    assert _NO_AGENDA_LINE in md
    agenda_idx, promise_idx = _line_indices(md)
    # ÇAĞ2-W4: promise_idx moved from agenda_idx + 1 to + 2 (the fresh target's
    # own honest-absent vault line now sits in between).
    assert promise_idx == agenda_idx + 2


def test_stubbed_owner_report_renders_rank_one_end_to_end(tmp_path: Path,
                                                          stub_audits):
    """Composition → render, whole seam: the target's artifact becomes the one
    owner-facing sentence, byte-stable across two renders (clock-free)."""
    _seed_agenda(tmp_path)
    report = owner_report(str(tmp_path))
    md = render_owner_report_markdown(report)
    assert ("- Next up (agenda): 2 landable move(s); "
            "rank-1: implement-stub in app/a.py.") in md
    assert md == render_owner_report_markdown(report)
