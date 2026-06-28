"""Piece A — the VALUE-AWARE GRADUATE GATE.

Today a confluence graduates only at ``confidence >= PROMOTE_CONFIDENCE`` (0.80).
On a real project confluences confirm at ~0.60 and NEVER graduate, so the curated
``dream --land`` scope is permanently empty. The value-aware gate adds a SECOND
streak-gated promote path: a confluence BELOW 0.80 graduates IF its module carries
a VERIFIED-LANDABLE move (the same real-lander synthesis probes the seeder uses),
so the dream graduates a discovery only when it can PROVE a concrete landing
exists on it. Design-level confluences (no landable move) keep the 0.80 bar.

These tests pin: (1) a below-0.80 confluence WITH a fillable stub graduates after
the streak; (2) the SAME below-0.80 confluence WITHOUT any landable move does NOT
graduate; (3) the value-aware path is still streak-gated (one short → nothing);
(4) the helper is honest (a real-lander probe), deterministic, and ``.py``-only.
"""

from __future__ import annotations

import json

from app.engine.dream import (
    PROMOTE_CONFIDENCE,
    PROMOTE_STREAK,
    _module_landable_objective,
)
from app.tools.project_profile import ProjectProfile, ProjectProfiler


def _below_gate_confluence_profile() -> ProjectProfile:
    """``app/big.py`` carries THREE signals (churn + single-author + hub) while two
    leaves carry one each: breadth 3 > typical 1 ⇒ confidence 3/(1+3) = 0.75 —
    a confluence that sits BELOW the 0.80 design-level gate."""
    return ProjectProfile(
        root=".",
        churn_hotspots=[{"module": "app/big.py", "commits": 9},
                        {"module": "app/small.py", "commits": 5},
                        {"module": "app/tiny.py", "commits": 4}],
        knowledge_risks=[{"module": "app/big.py", "share": 100, "commits": 9}],
        dependency_hubs=["app/big.py"],
    )


def _confluence_confidence_is_below_gate() -> None:
    from app.engine.dream_discovery import discover_structured

    confs = [d for d in discover_structured(_below_gate_confluence_profile())
             if d.kind == "confluence"]
    assert confs and confs[0].confidence < PROMOTE_CONFIDENCE


def _landable_project(tmp_path):
    """A confluence module carrying a genuinely FILLABLE stub (pinned by two
    witnesses) — a move ``apex develop``'s implement-stub objective can land."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "big.py").write_text(
        "def total(xs) -> int:\n    ...\n", encoding="utf-8")
    (tmp_path / "tests" / "test_big.py").write_text(
        "from app.big import total\n\n\ndef test_total():\n"
        "    assert total([1, 2, 3]) == 6\n    assert total([10, 20]) == 30\n",
        encoding="utf-8")
    (tmp_path / "app" / "small.py").write_text(
        "def leaf():\n    return 2\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")


def _design_only_project(tmp_path):
    """The SAME confluence module, but DESIGN-LEVEL: already implemented AND
    tested, not a package — so no landable signal (no stub, no cover-gap, no
    wire-exports) honestly holds."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "big.py").write_text(
        "def hub(x):\n    return x + 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_big.py").write_text(
        "from app.big import hub\n\n\ndef test_hub():\n    assert hub(1) == 2\n",
        encoding="utf-8")
    (tmp_path / "app" / "small.py").write_text(
        "def leaf():\n    return 2\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")


def _dream_n(tmp_path, monkeypatch, n: int):
    import app.engine.dream as dm

    monkeypatch.setattr(ProjectProfiler, "profile",
                        lambda self: _below_gate_confluence_profile())
    report = None
    for _ in range(n):
        report = dm.dream(str(tmp_path), write_digest=False, curate=True)
    return report


# --- (1) below-0.80 WITH a landable move graduates ---------------------------

def test_below_confidence_confluence_with_landable_move_graduates(
        tmp_path, monkeypatch):
    _confluence_confidence_is_below_gate()
    _landable_project(tmp_path)
    report = _dream_n(tmp_path, monkeypatch, PROMOTE_STREAK)

    promo = json.loads(
        (tmp_path / ".apex" / "dream-promotions.json").read_text())
    keys = [p["key"] for p in promo]
    assert "confluence:app/big.py" in keys, (
        "a streak-confirmed confluence with a verified-landable move must "
        "graduate even below the 0.80 confidence gate")
    graduated = next(p for p in promo if p["key"] == "confluence:app/big.py")
    assert graduated["confidence"] < PROMOTE_CONFIDENCE  # the value-aware path fired
    # The report headlines the graduation (the curate-mode "promoted" list carries
    # the discovery's human text), and the curate trail names the below-gate key.
    assert any("app/big.py" in t and "confluence" in t for t in report.promoted)
    assert any("confluence:app/big.py" in c for c in report.curated)


# --- (2) the SAME below-0.80 confluence WITHOUT a landable move does NOT ------

def test_below_confidence_confluence_without_landable_move_stays_gated(
        tmp_path, monkeypatch):
    _confluence_confidence_is_below_gate()
    _design_only_project(tmp_path)
    _dream_n(tmp_path, monkeypatch, PROMOTE_STREAK)

    promo = json.loads(
        (tmp_path / ".apex" / "dream-promotions.json").read_text())
    assert promo == [], (
        "a below-0.80 confluence with NO landable move must keep the design-level "
        "gate — graduating it would be an over-promise the lander can't honor")


# --- (3) the value-aware path is STILL streak-gated (never a one-off) ---------

def test_value_aware_path_is_still_streak_gated(tmp_path, monkeypatch):
    _landable_project(tmp_path)
    # One short of the streak: even WITH a landable move, nothing graduates.
    _dream_n(tmp_path, monkeypatch, PROMOTE_STREAK - 1)
    promo = json.loads(
        (tmp_path / ".apex" / "dream-promotions.json").read_text())
    assert promo == [], "value-awareness must not bypass the anti-oscillation streak"


# --- (4) the landable probe is honest, deterministic, .py-only ---------------

def test_module_landable_objective_is_honest_and_deterministic(tmp_path):
    _landable_project(tmp_path)
    obj = _module_landable_objective(tmp_path, "app/big.py")
    assert obj == "implement-stub"  # the highest-value signal the module carries
    # Deterministic: same module → same verdict.
    assert _module_landable_objective(tmp_path, "app/big.py") == obj


def test_module_landable_objective_none_for_design_only(tmp_path):
    _design_only_project(tmp_path)
    assert _module_landable_objective(tmp_path, "app/big.py") is None


def test_module_landable_objective_rejects_non_py_subject(tmp_path):
    # An abstract dream insight (not a .py path) can carry no landable move.
    assert _module_landable_objective(tmp_path, "app/big.py::insight") is None
    assert _module_landable_objective(tmp_path, "some abstract subject") is None


# --- (5) DEFAULT run byte-identical: no .apex state ⇒ streak 1 ⇒ no graduation -

def test_default_dream_with_no_apex_state_graduates_nothing(tmp_path, monkeypatch):
    """The round-21 default-byte-identical invariant: a DEFAULT ``dream`` (no
    ``--curate``) on a fixture with a below-0.80 confluence carrying a landable
    move — but NO prior ``.apex`` journal — sees streak 1 (< PROMOTE_STREAK), so
    NEITHER promote path fires. The value-aware gate can only graduate what the
    streak gate already lets through, so a default run is unchanged."""
    import app.engine.dream as dm

    _landable_project(tmp_path)
    monkeypatch.setattr(ProjectProfiler, "profile",
                        lambda self: _below_gate_confluence_profile())
    report = dm.dream(str(tmp_path), write_digest=False, curate=False)

    # No promotions store written (default only proposes); nothing graduated; and
    # the value-aware path proposes nothing either (streak 1, the byte-identical
    # case — a single dream can never trip the anti-oscillation guard).
    assert not (tmp_path / ".apex" / "dream-promotions.json").exists()
    assert report.promoted == []
    assert not any("promote to the idea engine" in p for p in report.proposed)
