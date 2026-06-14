"""Defensive branch edges of the dashboard track-record surfaces.

Closes the last uncovered branches in ``_proof_applied_count`` and
``_trackrecord_section``: a malformed ``totals.applied`` value (non-numeric /
wrong type) must collapse to 0 rather than raise, and a non-dict row inside the
learned most/least-reliable lists must be skipped rather than crash the panel.

Pattern-matched on tests/test_dashboard_trackrecord.py — pure render helpers
driven directly with tmp ``.apex`` ledgers and explicit dict inputs. No scan,
no network, no time/random/order assertions.
"""

import json

from app.reporting import dashboard as D


def _write_proof_raw(tmp_path, totals):
    apex = tmp_path / ".apex"
    apex.mkdir(exist_ok=True)
    (apex / "proof-of-fix.json").write_text(
        json.dumps({"totals": totals, "fixes": []}), encoding="utf-8")


# --- _proof_applied_count: malformed totals.applied -> 0 --------------------

def test_proof_applied_count_non_numeric_string_is_zero(tmp_path):
    # totals.applied is a string that int() cannot parse -> ValueError path.
    _write_proof_raw(tmp_path, {"applied": "lots"})
    assert D._proof_applied_count(tmp_path.__fspath__()) == 0


def test_proof_applied_count_wrong_type_is_zero(tmp_path):
    # totals.applied is a list -> int(list) raises TypeError -> 0.
    _write_proof_raw(tmp_path, {"applied": [1, 2, 3]})
    assert D._proof_applied_count(str(tmp_path)) == 0


def test_proof_applied_count_numeric_string_parses(tmp_path):
    # A numeric string is still honored (int("9") == 9), not discarded.
    _write_proof_raw(tmp_path, {"applied": "9"})
    assert D._proof_applied_count(str(tmp_path)) == 9


def test_proof_applied_count_totals_not_a_dict_is_zero(tmp_path):
    # totals is a list, not a dict -> (proof.get("totals") or {}) keeps it,
    # then .get raises AttributeError? No: `or {}` only fires on falsy; a
    # non-empty list stays. Guard that a benign empty list collapses to 0.
    _write_proof_raw(tmp_path, [])
    assert D._proof_applied_count(str(tmp_path)) == 0


# --- _trackrecord_section: non-dict rows in learned lists are skipped --------

def test_trackrecord_skips_non_dict_rows_in_learned(tmp_path):
    # Most/least lists carry junk (a string, an int, None) alongside one valid
    # row. The junk is skipped; the valid row still renders, proving the
    # isinstance(row, dict) guard (line 776) is exercised.
    learned = {
        "most_reliable": ["not-a-dict", 42, None,
                          {"key": "harden", "success_rate": 0.8, "samples": 5}],
        "least_reliable": [{"key": "modernize", "success_rate": 0.2, "samples": 5}],
    }
    # A landed-fix count keeps the panel ungated regardless of rates.
    _write_proof_raw(tmp_path, {"applied": 3})
    html_doc = D._trackrecord_section(learned, str(tmp_path))
    assert "Track record" in html_doc
    assert "harden" in html_doc and "80%" in html_doc
    assert "modernize" in html_doc and "20%" in html_doc
    # Two valid rate rows + the table header row; the junk entries add nothing.
    assert html_doc.count("<tr>") == 3


def test_trackrecord_all_non_dict_rows_with_proof_renders_count_only(tmp_path):
    # Every learned row is junk -> no rate rows, but landed fixes keep the panel.
    learned = {"most_reliable": ["x", 1], "least_reliable": [None]}
    _write_proof_raw(tmp_path, {"applied": 4})
    html_doc = D._trackrecord_section(learned, str(tmp_path))
    assert "Track record" in html_doc
    assert ">4<" in html_doc
    assert "<table>" not in html_doc  # no rate table without valid rows


def test_trackrecord_all_non_dict_rows_no_proof_is_gated(tmp_path):
    # Junk rows AND no landed fixes -> the section is gated to "".
    learned = {"most_reliable": ["x"], "least_reliable": [None]}
    assert D._trackrecord_section(learned, str(tmp_path)) == ""


def test_trackrecord_row_with_blank_key_is_skipped(tmp_path):
    # A dict row whose key is empty/whitespace is dropped (the `not key` guard),
    # leaving only the real operator.
    learned = {
        "most_reliable": [{"key": "  ", "success_rate": 0.9, "samples": 2},
                          {"key": "harden", "success_rate": 0.7, "samples": 4}],
        "least_reliable": [],
    }
    _write_proof_raw(tmp_path, {"applied": 1})
    html_doc = D._trackrecord_section(learned, str(tmp_path))
    # One valid rate row + the table header row (the blank-key row is dropped).
    assert html_doc.count("<tr>") == 2
    assert "harden" in html_doc


def test_trackrecord_branches_are_deterministic(tmp_path):
    learned = {
        "most_reliable": ["junk", {"key": "a", "success_rate": 0.5, "samples": 2}],
        "least_reliable": [{"key": "b", "success_rate": 0.5, "samples": 2}],
    }
    _write_proof_raw(tmp_path, {"applied": 2})
    first = D._trackrecord_section(learned, str(tmp_path))
    second = D._trackrecord_section(learned, str(tmp_path))
    assert first == second
    # a and b tie at 50%; key ascending breaks the tie deterministically.
    assert first.index("<code>a</code>") < first.index("<code>b</code>")
