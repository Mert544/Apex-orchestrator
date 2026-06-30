"""`apex owner-report` — the plain-language owner trust summary (Layer-1 VIEW).

These tests pin the four properties that make ``owner-report`` a TRUSTWORTHY view
and NOT a new analysis engine:

1. It COMPOSES the REAL deterministic audits on Apex's OWN tree — the same verdicts
   ``apex self-audit --north-star`` / ``--soundness`` / ``apex grade`` produce
   (trustworthy True, North Star PASS, soundness 65/65, grade A+99 today).
2. The render is PLAIN, non-technical English and CLOCK-FREE: no ISO-date, no "UTC",
   no time-of-day substring; byte-stable across two renders of the same dict.
3. The CLI ``--json`` flag emits the composed dict; the markdown path renders the
   YES headline.
4. An HONEST NOT-trustworthy path: a crafted dict with North Star FAIL or drift True
   renders a clear NO and NAMES the reason — the view never paints a failing audit
   green.

Plus determinism: ``owner_report`` is a pure function of repo state.
"""

from __future__ import annotations

import argparse
import copy
import functools
import json

import pytest

from app.engine.soundness_audit import repo_root
from app.reporting.owner_report import owner_report, render_owner_report_markdown

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
    # North Star: the real PASS verdict, no drift, the live 44/89 concrete split.
    ns = report["north_star"]
    assert ns["verdict"] == "PASS"
    assert ns["drift"] is False
    assert ns["total_objectives"] == 90
    assert ns["concrete_count"] == 45
    assert 0.0 <= ns["ratio"] <= 1.0
    # Soundness: PASS with all 89 objectives declaring a proof-strategy, plus the
    # single-gated-writer and scope_verify allow-list booleans.
    sound = report["soundness"]
    assert sound["verdict"] == "PASS"
    assert sound["strategies"] == "90/90"
    assert sound["single_writer"] is True
    assert sound["scope_verify_ok"] is True
    # Grade: the real letter + score.
    assert report["grade"] == {"letter": "A+", "score": 99}


def test_owner_report_capabilities_summary():
    cap = _apex_report()["capabilities"]
    assert cap["concrete_count"] == 45
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
        "trustworthy", "north_star", "soundness", "grade", "capabilities"}
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
    assert "honest-verification check did not pass" in md
    # The honesty line itself reflects the failure rather than a green claim.
    assert "[FAIL, 66/66]" in md


def test_crafted_trustworthy_true_renders_yes():
    """Control: the crafted-dict helper with all checks green renders the YES page —
    so the NO assertions above are about the verdict, not the helper."""
    md = render_owner_report_markdown(
        _crafted_report(drift=False, ns_verdict="PASS", sound_verdict="PASS"))
    assert "trustworthy?  ->  YES" in md
    assert "NO" not in md.splitlines()[0]


# --- (5) Determinism + edge/empty rendering ----------------------------------

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
