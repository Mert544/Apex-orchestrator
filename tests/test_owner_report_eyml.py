"""`apex owner-report` — the plain-language owner trust summary (Layer-1 VIEW).

These tests pin the properties that make ``owner-report`` a TRUSTWORTHY view and
NOT a new analysis engine:

1. It COMPOSES the REAL deterministic audits on Apex's OWN tree — the same verdicts
   ``apex self-audit --north-star`` / ``--soundness`` / ``apex grade`` produce
   (trustworthy True, North Star PASS, soundness 95/95, grade A+100 today).
2. The render is PLAIN, non-technical English and CLOCK-FREE: no ISO-date, no "UTC",
   no time-of-day substring; byte-stable across two renders of the same dict.
3. The CLI ``--json`` flag emits the composed dict; the markdown path renders the
   YES headline.
4. An HONEST NOT-trustworthy path: a crafted dict with North Star FAIL or drift True
   renders a clear NO and NAMES the reason — the view never paints a failing audit
   green.
5. TARGET-CONFUSION FIX: the soundness/"honesty" line is unambiguously labelled
   "Apex tool soundness (self-audit)" so it can never be misread as a claim about
   the owner's OWN project (it structurally cannot be — the underlying check audits
   Apex's ``app/`` package layout).
6. EVIDENCE-DERIVED PROMISE FIX: the closing "promise" sentence is derived from this
   project's OWN ``.apex/`` proof-of-fix history (via ``load_proof_history`` +
   ``summarise_fix_track_record``) when one exists, and falls back to the original,
   BYTE-IDENTICAL generic sentence when it does not (a fresh project).

Plus determinism: ``owner_report`` is a pure function of repo state.
"""

from __future__ import annotations

import argparse
import copy
import functools
import json
from pathlib import Path

import pytest

from app.engine.proof_of_fix import SCHEMA
from app.engine.soundness_audit import repo_root
from app.reporting.owner_report import (
    _GENERIC_PROMISE,
    _promise_line,
    _track_record_for,
    owner_report,
    render_owner_report_markdown,
)

# Substrings that would betray a wall-clock / timestamp leak. The render must
# contain NONE of them (it composes only clock-free audits, by invariant).
_CLOCK_MARKERS = ("UTC", "GMT", "T00:", "T12:", ":00:", "AM", "PM", "Z\n")


@functools.lru_cache(maxsize=1)
def _composed_apex_report() -> dict:
    """The composed owner report for Apex's OWN tree, computed ONCE and shared.

    ``owner_report`` re-runs the real north-star / soundness / grade audits over the
    whole repo (~60-75s each); the read-only tests below all assert against the SAME
    composition, so it is computed a single time per process rather than once per
    test. (Computing it per-test made this file re-audit the tree ~8x and tipped the
    determinism PAIR over the 120s per-test timeout as the repo grew.) The
    determinism test still does its OWN independent recomputation, so sharing this
    one cannot mask a non-deterministic report."""
    return owner_report(str(repo_root()))


def _apex_report() -> dict:
    """A private COPY of the shared composition (so no read-only test can mutate the
    cache the others — and the determinism check — depend on)."""
    return copy.deepcopy(_composed_apex_report())


# --- (1) Composition of the REAL audit verdicts ------------------------------

def test_owner_report_composes_real_apex_verdicts():
    report = _apex_report()
    # Headline: every underlying audit passes on Apex today, so the owner sees YES.
    assert report["trustworthy"] is True
    # North Star: the real PASS verdict, no drift, the live 50/95 concrete split.
    ns = report["north_star"]
    assert ns["verdict"] == "PASS"
    assert ns["drift"] is False
    assert ns["total_objectives"] == 96  # 95 -> 96: dedup-guarded-return
    assert ns["concrete_count"] == 50
    assert 0.0 <= ns["ratio"] <= 1.0
    # Soundness: PASS with all 96 objectives declaring a proof-strategy, plus the
    # single-gated-writer and scope_verify allow-list booleans.
    sound = report["soundness"]
    assert sound["verdict"] == "PASS"
    assert sound["strategies"] == "96/96"  # 95 -> 96: dedup-guarded-return
    assert sound["single_writer"] is True
    assert sound["scope_verify_ok"] is True
    # Grade: the real letter + score.
    assert report["grade"] == {"letter": "A+", "score": 100}
    # Track record: THIS worktree's own .apex/ carries no proof-of-fix history yet
    # (a fresh checkout), so the evidence-free/neutral shape composes here.
    tr = report["track_record"]
    assert tr["has_history"] is False
    assert tr["runs"] == 0
    assert tr["applied"] == tr["rolled_back"] == tr["blocked"] == 0


def test_owner_report_capabilities_summary():
    cap = _apex_report()["capabilities"]
    assert cap["concrete_count"] == 50
    # Apex lands Python, Java, AND JS/TS concrete objectives, Python listed first,
    # then Java, then JavaScript/TypeScript (the stable display order).
    assert cap["languages"] == ["Python", "Java", "JavaScript/TypeScript"]
    # A few real, plain-language example abilities (never empty on Apex's manifest).
    assert cap["abilities"]
    assert all(isinstance(a, str) and a for a in cap["abilities"])
    assert len(cap["abilities"]) <= 4


# --- (2) Plain-language + CLOCK-FREE render ----------------------------------

def test_render_is_plain_language_and_trustworthy_headline():
    md = render_owner_report_markdown(_apex_report())
    # The owner's one question, answered YES, in plain words — no objective slugs.
    assert "# Is Apex's work trustworthy?  ->  YES" in md
    assert "real development work that lands working code" in md
    assert "never leaves your project worse" in md
    # Plain language: the internal slug vocabulary never reaches the owner page.
    for slug in ("implement-stub", "wire-exports", "scope_verify", "CONCRETE"):
        assert slug not in md


def test_render_soundness_line_labelled_as_apex_tool_self_audit():
    """TARGET-CONFUSION FIX: the soundness line must be unmistakably about Apex the
    TOOL, never readable as a claim about the owner's OWN project. The explicit
    label + "Apex's own abilities" wording is the fix; the old ambiguous "Honest
    verification" phrasing (with no owner/tool qualifier) must be gone."""
    md = render_owner_report_markdown(_apex_report())
    assert "- Apex tool soundness (self-audit): " in md
    assert "Apex's" in md and "own abilities" in md
    # The old, ambiguous label is fully retired — not merely superseded.
    assert "Honest verification:" not in md


def test_render_is_clock_free():
    md = render_owner_report_markdown(_apex_report())
    for marker in _CLOCK_MARKERS:
        assert marker not in md, f"clock/timestamp marker leaked: {marker!r}"
    # No bare 4-digit year-shaped token and no ISO date separator pattern.
    assert "20" + "26-" not in md  # e.g. an ISO date like 2026-06-25
    assert "datetime" not in md


def test_render_is_byte_stable_across_two_renders():
    report = _apex_report()
    first = render_owner_report_markdown(report)
    second = render_owner_report_markdown(report)
    assert first == second
    # Byte-identical even when re-derived from a freshly composed dict (no hidden
    # ordering/clock state in either composition or rendering).
    assert render_owner_report_markdown(_apex_report()) == first


# --- (3) CLI: markdown + --json dispatch -------------------------------------

def test_cli_owner_report_markdown(capsys):
    from app import cli_ops

    args = argparse.Namespace(target=".", json=False)
    assert cli_ops.cmd_owner_report(args) == 0
    out = capsys.readouterr().out
    assert "Is Apex's work trustworthy?" in out
    assert "Quality: grade" in out


def test_cli_owner_report_json_emits_dict(capsys):
    from app import cli_ops

    args = argparse.Namespace(target=".", json=True)
    assert cli_ops.cmd_owner_report(args) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    # The JSON IS the composed dict, with its stable top-level keys.
    assert set(payload) == {
        "trustworthy", "north_star", "soundness", "grade", "capabilities",
        "track_record"}
    assert payload["trustworthy"] is True
    assert payload["grade"]["letter"] == "A+"


# --- (4) HONEST not-trustworthy path -----------------------------------------

def _crafted_report(*, drift: bool, ns_verdict: str, sound_verdict: str) -> dict:
    """A hand-built report dict (no audits run) to exercise the NOT-trustworthy
    render paths deterministically."""
    trustworthy = ns_verdict == "PASS" and sound_verdict == "PASS" and not drift
    return {
        "trustworthy": trustworthy,
        "north_star": {
            "verdict": ns_verdict, "drift": drift,
            "concrete_count": 24, "total_objectives": 66, "ratio": 0.35,
        },
        "soundness": {
            "verdict": sound_verdict, "strategies": "66/66",
            "single_writer": True, "scope_verify_ok": True,
        },
        "grade": {"letter": "A+", "score": 99},
        "capabilities": {
            "concrete_count": 24,
            "languages": ["Python", "JavaScript/TypeScript"],
            "abilities": ["filling in unfinished functions"],
        },
    }


def test_render_not_trustworthy_on_drift_names_reason():
    md = render_owner_report_markdown(
        _crafted_report(drift=True, ns_verdict="PASS", sound_verdict="PASS"))
    assert "trustworthy?  ->  NO" in md
    assert "The reason:" in md
    assert "drifted away from real development work" in md
    # And the on-mission line reflects the drift, not a false green.
    assert "[PASS, drift: YES]" in md


def test_render_not_trustworthy_on_north_star_fail_names_reason():
    md = render_owner_report_markdown(
        _crafted_report(drift=False, ns_verdict="DRIFT", sound_verdict="PASS"))
    assert "trustworthy?  ->  NO" in md
    assert "on-mission check did not pass" in md


def test_render_not_trustworthy_on_soundness_fail_names_reason():
    md = render_owner_report_markdown(
        _crafted_report(drift=False, ns_verdict="PASS", sound_verdict="FAIL"))
    assert "trustworthy?  ->  NO" in md
    # The reason names Apex's OWN tool-soundness self-check — never phrased so it
    # could be misread as a claim about the owner's project (target-confusion fix).
    assert "Apex's own tool-soundness self-check did not pass" in md
    # The honesty line itself reflects the failure rather than a green claim, under
    # the explicit self-audit label.
    assert "- Apex tool soundness (self-audit): " in md
    assert "[FAIL, 66/66]" in md


def test_crafted_trustworthy_true_renders_yes():
    """Control: the crafted-dict helper with all checks green renders the YES page —
    so the NO assertions above are about the verdict, not the helper."""
    md = render_owner_report_markdown(
        _crafted_report(drift=False, ns_verdict="PASS", sound_verdict="PASS"))
    assert "trustworthy?  ->  YES" in md
    assert "NO" not in md.splitlines()[0]


# --- (5) Track record: evidence-derived closing "promise" sentence -----------
#
# ``_track_record_for`` reads THIS project's OWN ``.apex/`` proof-of-fix history
# (never Apex's own tree — the opposite composition rule from the soundness line)
# and ``_promise_line`` renders it. No history -> the original generic sentence,
# byte-identical; a real history -> the real applied/rolled_back/blocked counts.

def _write_proof(apex_dir: Path, name: str, fixes: list[dict],
                  generated_at: str = "2026-01-01T00:00:00+00:00") -> None:
    apex_dir.mkdir(parents=True, exist_ok=True)
    proof = {"schema": SCHEMA, "schema_version": "1.0",
              "generated_at": generated_at, "fixes": fixes}
    (apex_dir / name).write_text(json.dumps(proof, indent=2), encoding="utf-8")


def _fix(outcome: str, action: str = "create_test_stub") -> dict:
    return {
        "finding": {"label": "untested", "action": action,
                    "operator": "test", "target": "app/m.py"},
        "transform_type": action,
        "outcome": outcome,
        "changed_files": ["app/m.py"],
    }


def test_track_record_for_absent_apex_dir_is_no_history(tmp_path: Path):
    """A fresh project with no ``.apex/`` at all -> the neutral, opt-in default."""
    tr = _track_record_for(tmp_path)
    assert tr == {
        "has_history": False, "runs": 0, "applied": 0, "rolled_back": 0, "blocked": 0}


def test_track_record_for_apex_dir_with_no_fixes_is_no_history(tmp_path: Path):
    """A proof file with ZERO recorded fixes (e.g. a run that found nothing to do)
    is treated as no-evidence too — an all-zero "Last 1 runs: 0/0/0" sentence would
    read as a broken claim, not a reassuring one, so it stays on the generic path."""
    _write_proof(tmp_path / ".apex", "proof-of-fix.json", [])
    tr = _track_record_for(tmp_path)
    assert tr["has_history"] is False
    assert tr["runs"] == 1  # the proof record itself was read...
    assert tr["applied"] == tr["rolled_back"] == tr["blocked"] == 0  # ...but carried nothing


def test_track_record_for_aggregates_real_history(tmp_path: Path):
    apex = tmp_path / ".apex"
    _write_proof(apex, "proof-of-fix.json", [
        _fix("applied"), _fix("applied"), _fix("rolled_back"), _fix("blocked"),
    ], generated_at="2026-02-01T00:00:00+00:00")
    _write_proof(apex, "archive-1.json", [_fix("applied")],
                 generated_at="2026-01-01T00:00:00+00:00")
    tr = _track_record_for(tmp_path)
    assert tr == {
        "has_history": True, "runs": 2, "applied": 3, "rolled_back": 1, "blocked": 1}


def test_promise_line_falls_back_to_generic_sentence_with_no_track_record_key():
    """A report dict with NO ``track_record`` key at all (an older/hand-built dict,
    like the test suite's own ``_crafted_report`` helper) renders the ORIGINAL
    generic sentence — the fallback is defensive against a missing key, not just a
    falsy ``has_history``."""
    assert _promise_line({}) == _GENERIC_PROMISE


def test_promise_line_falls_back_to_generic_sentence_with_no_history():
    report = {"track_record": {
        "has_history": False, "runs": 0, "applied": 0, "rolled_back": 0, "blocked": 0}}
    assert _promise_line(report) == _GENERIC_PROMISE


def test_promise_line_is_evidence_derived_with_real_history():
    report = {"track_record": {
        "has_history": True, "runs": 3, "applied": 5, "rolled_back": 1, "blocked": 2}}
    line = _promise_line(report)
    assert line != _GENERIC_PROMISE
    assert "last 3 proof-carrying runs" in line
    assert "5 applied" in line
    assert "1 auto-rolled-back" in line
    assert "2 declined" in line
    assert "Apex never leaves your project worse." in line


def test_promise_line_singular_run_wording():
    """One run reads "1 proof-carrying run", not "1 ... runs" — plain grammar."""
    report = {"track_record": {
        "has_history": True, "runs": 1, "applied": 1, "rolled_back": 0, "blocked": 0}}
    line = _promise_line(report)
    assert "1 proof-carrying run " in line
    assert "1 proof-carrying runs" not in line


def test_crafted_report_helper_has_no_track_record_key_and_still_renders():
    """The suite's own ``_crafted_report`` dicts (used throughout section 4) omit
    ``track_record`` entirely, exercising the "missing key" fallback end-to-end
    through the full render — a not-trustworthy render must not crash or omit the
    promise line just because it predates this feature."""
    report = _crafted_report(drift=False, ns_verdict="PASS", sound_verdict="PASS")
    assert "track_record" not in report
    md = render_owner_report_markdown(report)
    assert _GENERIC_PROMISE in md


def test_render_promise_line_is_evidence_derived_end_to_end():
    """The full markdown render picks up the evidence-derived line when the report
    dict carries a real ``track_record`` — not just the isolated helper."""
    report = _crafted_report(drift=False, ns_verdict="PASS", sound_verdict="PASS")
    report["track_record"] = {
        "has_history": True, "runs": 12, "applied": 20, "rolled_back": 3, "blocked": 1}
    md = render_owner_report_markdown(report)
    assert "The promise, backed by evidence: last 12 proof-carrying runs" in md
    assert "20 applied, 3 auto-rolled-back, 1 declined" in md
    assert _GENERIC_PROMISE not in md


def test_apex_own_tree_report_renders_generic_promise_today():
    """END-TO-END on Apex's OWN tree: this worktree has no ``.apex/`` proof history
    yet, so the real composed report renders the original generic promise sentence
    byte-identically — the neutral default is truly the default, not just tested
    in isolation."""
    md = render_owner_report_markdown(_apex_report())
    assert _GENERIC_PROMISE in md
    assert "backed by evidence" not in md


# --- (6) Determinism + edge/empty rendering ----------------------------------

@pytest.mark.timeout(300)
def test_owner_report_is_deterministic():
    # Two INDEPENDENT compositions of the real-tree report must be byte-equal:
    # owner_report is a pure function of repo state (sorted outputs; no clock,
    # random, or hash-order). A genuinely FRESH audit here, compared against the
    # suite's shared composition (computed independently) — NOT the cached object
    # compared to itself. The marker gives this heaviest test headroom for up to two
    # real-tree audits, while the read-only tests reuse the single shared one.
    assert owner_report(str(repo_root())) == _composed_apex_report()


def test_render_handles_empty_capabilities():
    """Edge/empty path: a report whose CONCRETE manifest yielded no languages and no
    example abilities still renders one clean, owner-readable capability sentence."""
    report = _crafted_report(drift=False, ns_verdict="PASS", sound_verdict="PASS")
    report["capabilities"] = {"concrete_count": 0, "languages": [], "abilities": []}
    md = render_owner_report_markdown(report)
    # Falls back to "your code" rather than a dangling "across ." and emits no
    # empty parenthetical for the (absent) example abilities.
    assert "across your code." in md
    assert "(, ...)" not in md
    assert "0 kinds of verified working-code contributions" in md


def test_promise_line_handles_empty_track_record_dict():
    """Edge/empty path: ``track_record: {}`` (present but empty, distinct from a
    missing key or an explicit ``has_history: False``) still falls back to the
    generic sentence rather than raising a ``KeyError``."""
    assert _promise_line({"track_record": {}}) == _GENERIC_PROMISE
    assert _promise_line({"track_record": None}) == _GENERIC_PROMISE
