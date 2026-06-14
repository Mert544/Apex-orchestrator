"""More edges of `apex trackrecord` — the proof-of-fix counting fallbacks.

The headline numbers come from ``.apex/proof-of-fix.json``. When the ledger
records explicit ``totals`` Apex trusts them; when it does NOT (older / partial
ledgers that only list ``fixes``), it counts the fixes by outcome itself. These
tests cover that fallback, the per-outcome counting, and the defensive readers
(``_read_proof_of_fix`` on missing / corrupt / non-dict payloads).

Pattern-matched on tests/test_cli_trackrecord.py — argparse.Namespace inputs,
tmp ``.apex`` ledgers, stdout capture. Deterministic, stdlib-only, LLM-free.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

import pytest

from app.cli_insight import (
    _read_proof_of_fix,
    _trackrecord,
    cmd_trackrecord,
    render_trackrecord_markdown,
)


def _run(target: Path, json_out: bool = False) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_trackrecord(argparse.Namespace(target=str(target), json=json_out))
    return rc, buf.getvalue()


def _write_proof(root: Path, payload: dict) -> None:
    apex = root / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / "proof-of-fix.json").write_text(json.dumps(payload), encoding="utf-8")


# --- _read_proof_of_fix: defensive readers ----------------------------------

def test_read_proof_missing_is_empty(tmp_path):
    assert _read_proof_of_fix(tmp_path) == {}


def test_read_proof_corrupt_is_empty(tmp_path):
    _write_proof_raw = tmp_path / ".apex"
    _write_proof_raw.mkdir()
    (_write_proof_raw / "proof-of-fix.json").write_text("}{", encoding="utf-8")
    assert _read_proof_of_fix(tmp_path) == {}


def test_read_proof_non_dict_payload_is_empty(tmp_path):
    # A JSON array (valid JSON, wrong shape) collapses to {}.
    _write_proof(tmp_path, [])  # type: ignore[arg-type]
    assert _read_proof_of_fix(tmp_path) == {}


def test_read_proof_valid_dict_passes_through(tmp_path):
    _write_proof(tmp_path, {"totals": {"applied": 2}, "fixes": []})
    assert _read_proof_of_fix(tmp_path) == {"totals": {"applied": 2}, "fixes": []}


# --- totals ABSENT: count the fixes by outcome ------------------------------

def test_counts_fixes_when_totals_absent(tmp_path):
    # No `totals` key at all -> landed/reverted are counted from the fixes list.
    _write_proof(tmp_path, {
        "fixes": [
            {"outcome": "applied", "finding": {"target": "app/a.py"}},
            {"outcome": "applied", "finding": {"target": "app/b.py"}},
            {"outcome": "rolled_back", "finding": {"target": "app/c.py"}},
        ],
    })
    rec = _trackrecord(tmp_path)
    assert rec["verified_fixes"] == 2
    assert rec["rolled_back"] == 1
    assert rec["has_record"] is True


def test_counting_ignores_non_dict_and_other_outcomes(tmp_path):
    # Non-dict entries and unrelated outcomes (blocked) are not counted as
    # landed or reverted.
    _write_proof(tmp_path, {
        "fixes": [
            {"outcome": "applied"},
            "garbage",
            {"outcome": "blocked"},
            {"outcome": "rolled_back"},
            42,
        ],
    })
    rec = _trackrecord(tmp_path)
    assert rec["verified_fixes"] == 1
    assert rec["rolled_back"] == 1


def test_render_counted_headline(tmp_path):
    _write_proof(tmp_path, {
        "fixes": [{"outcome": "applied"}, {"outcome": "applied"},
                  {"outcome": "rolled_back"}],
    })
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "2 fixes" in out
    assert "rolled back" in out


# --- totals PRESENT but a key missing/None: per-key fallback ----------------

def test_totals_present_missing_rolled_back_falls_back_to_count(tmp_path):
    # totals has `applied` but not `rolled_back`; the rolled_back number falls
    # back to counting the rolled_back fixes (here: 1).
    _write_proof(tmp_path, {
        "totals": {"applied": 5},
        "fixes": [{"outcome": "rolled_back"}],
    })
    rec = _trackrecord(tmp_path)
    assert rec["verified_fixes"] == 5
    assert rec["rolled_back"] == 1


@pytest.mark.xfail(
    reason="REAL QUIRK app/cli_insight.py:380 — `int(totals.get('applied', "
    "verified) or 0)` only falls back to the counted value when the `applied` "
    "KEY is absent; an explicit JSON null collapses to 0 instead of counting "
    "the two applied fixes. A missing key and a null value should behave the "
    "same. Not fixing source per task constraints; documenting the asymmetry.",
    strict=True,
)
def test_totals_present_none_applied_falls_back_to_count(tmp_path):
    # totals.applied is explicitly null -> SHOULD fall back to counting applied
    # fixes (2), but the source treats null as 0.
    _write_proof(tmp_path, {
        "totals": {"applied": None, "rolled_back": 0},
        "fixes": [{"outcome": "applied"}, {"outcome": "applied"}],
    })
    rec = _trackrecord(tmp_path)
    assert rec["verified_fixes"] == 2
    assert rec["rolled_back"] == 0


def test_totals_present_none_applied_currently_yields_zero(tmp_path):
    # Pins the CURRENT (quirky) behavior so the regression is visible: an
    # explicit null `applied` yields 0, not the counted fallback.
    _write_proof(tmp_path, {
        "totals": {"applied": None, "rolled_back": 0},
        "fixes": [{"outcome": "applied"}, {"outcome": "applied"}],
    })
    rec = _trackrecord(tmp_path)
    assert rec["verified_fixes"] == 0


def test_totals_present_zero_applied_is_honored(tmp_path):
    # An explicit 0 applied with no fixes -> no headline record from proof.
    _write_proof(tmp_path, {"totals": {"applied": 0, "rolled_back": 0}, "fixes": []})
    rec = _trackrecord(tmp_path)
    assert rec["verified_fixes"] == 0
    assert rec["has_record"] is False


# --- rolled-back framing in the render --------------------------------------

def test_singular_rolled_back_attempt_wording(tmp_path):
    _write_proof(tmp_path, {"totals": {"applied": 2, "rolled_back": 1}, "fixes": []})
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "1 attempt" in out
    assert "1 attempts" not in out
    assert "safety net" in out


def test_plural_rolled_back_attempts_wording(tmp_path):
    _write_proof(tmp_path, {"totals": {"applied": 2, "rolled_back": 3}, "fixes": []})
    rc, out = _run(tmp_path)
    assert "3 attempts" in out


def test_no_rolled_back_omits_safety_net_line(tmp_path):
    _write_proof(tmp_path, {"totals": {"applied": 2, "rolled_back": 0}, "fixes": []})
    rc, out = _run(tmp_path)
    assert "rolled back" not in out
    assert "safety net" not in out


# --- generated_at passthrough (no timestamp asserted on wall-clock) ---------

def test_generated_at_passed_through_verbatim(tmp_path):
    _write_proof(tmp_path, {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "totals": {"applied": 1, "rolled_back": 0},
        "fixes": [],
    })
    rec = _trackrecord(tmp_path)
    # The value is whatever the ledger stored, not a fresh clock read.
    assert rec["generated_at"] == "2026-01-01T00:00:00+00:00"


# --- render edge: mixed band flag (neither reliable nor risky) --------------

def test_render_mixed_band_flag():
    # success_rate strictly between the risky ceiling and reliable floor -> the
    # "mixed" flag, neither "lead with this" nor "expect blocks/rollbacks".
    rec = {
        "verified_fixes": 1,
        "rolled_back": 0,
        "operators_tracked": 1,
        "by_type": [{"key": "rename", "success_rate": 0.5, "samples": 1}],
        "generated_at": "",
        "has_record": True,
    }
    out = render_trackrecord_markdown(rec)
    assert "mixed" in out
    assert "reliable — lead with this" not in out
    # singular "sample" wording at samples == 1.
    assert "over 1 sample " in out


def test_render_empty_record_when_no_evidence():
    rec = {
        "verified_fixes": 0,
        "rolled_back": 0,
        "operators_tracked": 0,
        "by_type": [],
        "generated_at": "",
        "has_record": False,
    }
    out = render_trackrecord_markdown(rec)
    assert "no track record yet" in out
    assert "apex maintain" in out
