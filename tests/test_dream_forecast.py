"""Forward-looking "Next to graduate" forecast — the BACKWARD streak read FORWARD.

The dream already counts how many consecutive nights a discovery survived
(``report._streaks``) and graduates it once it clears ``PROMOTE_STREAK`` at
``PROMOTE_CONFIDENCE``. ``_forecast`` reads the SAME streak the other way: a
discovery already strong enough but still one (or a few) dream(s) short of the
gate is announced as "almost there", so the temporal-learning differentiator is
anticipatory and legible instead of only retrospective.

Invariants under test:
  * a near-miss (high confidence, ``2 <= streak < PROMOTE_STREAK``) APPEARS;
  * an exactly-at-streak discovery does NOT (it is already "Graduated" — never
    double-reported);
  * a below-confidence discovery does NOT (the forecast can't over-promise);
  * an EMPTY near-miss band leaves the digest byte-identical (additive section);
  * the render is deterministic (same report → same body).
"""

from __future__ import annotations

import json

from app.engine.dream import (
    PROMOTE_CONFIDENCE,
    PROMOTE_STREAK,
    DreamReport,
    _forecast,
    dream,
    render_dream_markdown,
)
from app.tools.project_profile import ProjectProfile, ProjectProfiler

_HEADING = "## 🔮 Next to graduate (one more dream away)"


def _disc(key: str, confidence: float, *, kind: str = "confluence") -> dict:
    """A structured-discovery dict shaped exactly like ``Discovery.to_dict``."""
    return {"key": key, "text": f"`{key}` is a confluence — 4 signals at once",
            "kind": kind, "confidence": confidence, "support": 4}


def _report_with(streaks: dict[str, int], *discoveries: dict) -> DreamReport:
    """A report carrying the structured discoveries and the journal-derived streaks."""
    report = DreamReport()
    report.discovery_objs = list(discoveries)
    report._streaks = streaks
    return report


# --- the near-miss band (unit-precise control over confidence × streak) ------

def test_near_miss_high_confidence_under_streak_appears():
    # confidence 0.85 (>= 0.80) AND streak 2 (2 <= 2 < 3) -> the forecast band.
    d = _disc("confluence:app/x.py", 0.85)
    report = _report_with({d["key"]: 2}, d)
    _forecast(report)
    assert report.forecast, "a 2/3 high-confidence discovery should be forecast"
    line = report.forecast[0]
    assert "confirmed 2/3 dreams" in line
    assert "one more dream graduates it into a work order" in line
    assert "app/x.py" in line
    md = render_dream_markdown(report)
    assert _HEADING in md
    assert "app/x.py" in md.split(_HEADING, 1)[1]


def test_exactly_at_streak_is_not_forecast_no_double_report():
    # streak == PROMOTE_STREAK is GRADUATED (handled by _promote); the forecast
    # must NOT also list it, or a discovery would be double-reported.
    d = _disc("confluence:app/y.py", 0.90)
    report = _report_with({d["key"]: PROMOTE_STREAK}, d)
    _forecast(report)
    assert report.forecast == []
    assert _HEADING not in render_dream_markdown(report)


def test_over_streak_is_not_forecast_either():
    # A long-standing graduated discovery (streak well past the gate) stays out
    # of the forecast — only the near-miss band qualifies.
    d = _disc("confluence:app/z.py", 0.95)
    report = _report_with({d["key"]: PROMOTE_STREAK + 4}, d)
    _forecast(report)
    assert report.forecast == []


def test_below_confidence_is_not_forecast():
    # streak 2 is in band, but 0.5 < PROMOTE_CONFIDENCE -> never forecast: the
    # section can only promise what the SAME gate would actually graduate.
    d = _disc("confluence:app/w.py", 0.50)
    report = _report_with({d["key"]: 2}, d)
    _forecast(report)
    assert report.forecast == []
    assert _HEADING not in render_dream_markdown(report)


def test_streak_one_is_not_forecast():
    # A first-night discovery (streak 1, below the 2 floor) is too green to
    # forecast even at high confidence — one confirmation isn't "almost there".
    d = _disc("confluence:app/a.py", 0.99)
    report = _report_with({d["key"]: 1}, d)
    _forecast(report)
    assert report.forecast == []


def test_confidence_exactly_at_threshold_is_forecast():
    # The gate is ``>=`` PROMOTE_CONFIDENCE; a discovery sitting exactly on it
    # (the real confluence case, 4/5 = 0.80) qualifies, matching _promote.
    d = _disc("confluence:app/edge.py", PROMOTE_CONFIDENCE)
    report = _report_with({d["key"]: 2}, d)
    _forecast(report)
    assert report.forecast, "exactly-at-threshold confidence should forecast"


def test_missing_streak_defaults_to_one_and_is_not_forecast():
    # A discovery the streak map doesn't mention defaults to streak 1 (this very
    # dream, never seen before) -> below the floor -> not forecast.
    d = _disc("confluence:app/new.py", 0.95)
    report = _report_with({}, d)  # empty streak map
    _forecast(report)
    assert report.forecast == []


# --- the additive-section invariant: byte-identical when the band is empty ----

def test_empty_near_miss_band_digest_byte_identical():
    # With NO discovery in the near-miss band the forecast section must emit
    # nothing — the digest is byte-for-byte what it was before this feature.
    graduated = _disc("confluence:app/hot.py", 0.90)
    report = _report_with({graduated["key"]: PROMOTE_STREAK}, graduated)
    _forecast(report)
    assert report.forecast == []
    md = render_dream_markdown(report)
    assert _HEADING not in md
    # Byte-identical to a render of the same report whose forecast we never touch.
    untouched = _report_with({graduated["key"]: PROMOTE_STREAK}, graduated)
    assert render_dream_markdown(untouched) == md


def test_empty_report_has_no_forecast_section():
    report = DreamReport()
    _forecast(report)
    assert report.forecast == []
    assert _HEADING not in render_dream_markdown(report)


# --- determinism --------------------------------------------------------------

def test_forecast_render_is_deterministic():
    def _body(md: str) -> str:  # strip the once-per-render timestamp line
        return "\n".join(ln for ln in md.splitlines() if "Curated" not in ln)

    d = _disc("confluence:app/x.py", 0.85)
    r1 = _report_with({d["key"]: 2}, d)
    r2 = _report_with({d["key"]: 2}, d)
    _forecast(r1)
    _forecast(r2)
    assert r1.forecast == r2.forecast
    assert _body(render_dream_markdown(r1)) == _body(render_dream_markdown(r2))


def test_forecast_orders_with_discovery_objs():
    # Two near-misses are emitted in the order they appear in discovery_objs
    # (which the discovery layer already pre-sorts) — stable, no re-sort.
    d1 = _disc("confluence:app/first.py", 0.88)
    d2 = _disc("confluence:app/second.py", 0.82)
    report = _report_with({d1["key"]: 2, d2["key"]: 2}, d1, d2)
    _forecast(report)
    assert len(report.forecast) == 2
    assert "app/first.py" in report.forecast[0]
    assert "app/second.py" in report.forecast[1]


def test_to_dict_carries_forecast():
    d = _disc("confluence:app/x.py", 0.85)
    report = _report_with({d["key"]: 2}, d)
    _forecast(report)
    payload = report.to_dict()
    assert "forecast" in payload
    assert payload["forecast"] == report.forecast


# --- end-to-end through the real dream() flow ---------------------------------

def _confluence_profile() -> ProjectProfile:
    # app/big.py carries FOUR signals -> a confluence discovery at confidence
    # 4/5 = 0.80 (== PROMOTE_CONFIDENCE), exactly the promotion path's case.
    return ProjectProfile(
        root=".",
        churn_hotspots=[{"module": "app/big.py", "commits": 9},
                        {"module": "app/small.py", "commits": 5},
                        {"module": "app/tiny.py", "commits": 4}],
        knowledge_risks=[{"module": "app/big.py", "share": 100, "commits": 9}],
        dependency_hubs=["app/big.py"],
        symbol_hubs=["app/big.py"],
    )


def _dream_confluence(tmp_path, monkeypatch):
    prof = _confluence_profile()
    monkeypatch.setattr(ProjectProfiler, "profile", lambda self: prof)
    return dream(tmp_path, curate=False, write_digest=False)


def test_e2e_second_dream_forecasts_then_third_graduates(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()

    # Dream 1: first sighting (streak 1) -> too green, no forecast yet.
    r1 = _dream_confluence(tmp_path, monkeypatch)
    assert not any("app/big.py" in f for f in r1.forecast)

    # Dream 2: streak 2 -> the near-miss band. The digest now FORECASTS it.
    r2 = _dream_confluence(tmp_path, monkeypatch)
    assert any("app/big.py" in f and "confirmed 2/3 dreams" in f
               for f in r2.forecast), "the 2/3 confluence should be forecast"
    md2 = render_dream_markdown(r2)
    assert _HEADING in md2
    assert "app/big.py" in md2.split(_HEADING, 1)[1].split("\n", 1)[0] \
        or "app/big.py" in md2

    # Dream 3: streak 3 -> it GRADUATES (proposed), and must leave the forecast.
    r3 = _dream_confluence(tmp_path, monkeypatch)
    assert any("app/big.py" in p for p in r3.proposed), "now it graduates"
    assert not any("app/big.py" in f for f in r3.forecast), \
        "a graduated discovery must not be double-reported in the forecast"


def test_e2e_forecast_and_promotion_read_the_same_streak(tmp_path, monkeypatch):
    # The crux: forecast and the next night's actual graduation can never
    # disagree, because both read report._streaks. On the night a discovery is
    # forecast at 2/3, the very same report's promotion gate must NOT yet fire;
    # the night it graduates, the forecast must be silent for it.
    (tmp_path / "app").mkdir()
    _dream_confluence(tmp_path, monkeypatch)              # streak 1
    forecast_night = _dream_confluence(tmp_path, monkeypatch)  # streak 2
    assert any("app/big.py" in f for f in forecast_night.forecast)
    assert not any("app/big.py" in p for p in forecast_night.proposed)

    graduate_night = _dream_confluence(tmp_path, monkeypatch)  # streak 3
    assert any("app/big.py" in p for p in graduate_night.proposed)
    assert not any("app/big.py" in f for f in graduate_night.forecast)


def test_e2e_digest_byte_identical_when_no_near_miss(tmp_path, monkeypatch):
    # A project whose only discoveries never reach the near-miss band leaves the
    # forecast section absent from the real digest. Two fresh roots (no shared
    # journal -> streak 1 everywhere) render byte-identical bodies with no
    # "Next to graduate" heading at all.
    def _body(md: str) -> str:
        return "\n".join(ln for ln in md.splitlines() if "Curated" not in ln)

    a, b = tmp_path / "a", tmp_path / "b"
    (a / "app").mkdir(parents=True)
    (b / "app").mkdir(parents=True)
    prof = _confluence_profile()
    monkeypatch.setattr(ProjectProfiler, "profile", lambda self: prof)
    md_a = render_dream_markdown(dream(a, curate=False, write_digest=False))
    md_b = render_dream_markdown(dream(b, curate=False, write_digest=False))
    assert _HEADING not in md_a  # streak 1 on a fresh journal -> nothing forecast
    assert _body(md_a) == _body(md_b)


def test_persist_false_forecast_matches_persisting_run(tmp_path, monkeypatch):
    # Streaks are byte-identical under persist=False; the forecast derived from
    # them must be too. Build a 2-deep journal, then a read-only pass must
    # forecast exactly what a persisting pass would, while writing nothing new.
    (tmp_path / "app").mkdir()
    prof = _confluence_profile()
    monkeypatch.setattr(ProjectProfiler, "profile", lambda self: prof)
    dream(tmp_path, curate=False, write_digest=False)  # streak 1 (persisted)
    journal = tmp_path / ".apex" / "dream-journal.json"
    before = json.loads(journal.read_text())

    read_only = dream(tmp_path, curate=False, write_digest=False, persist=False)
    assert any("app/big.py" in f and "confirmed 2/3 dreams" in f
               for f in read_only.forecast)
    # The read-only pass advanced nothing on disk.
    assert json.loads(journal.read_text()) == before
