"""Export Apex signals as shields.io "endpoint" badge JSON for a repo's README.

shields.io serves a dynamic badge from any URL that returns the endpoint schema
``{"schemaVersion": 1, "label": str, "message": str, "color": str}``. Emitting
Apex's health grade, coverage, and findings count in that schema lets a project
publish a live Apex badge — a visible, competitive quality signal — without any
extra service.

Everything here is deterministic and stdlib-only: each builder is a pure function
of its inputs, colors are chosen by fixed bands/thresholds, and inputs are clamped
and escaped so the same input always yields byte-identical JSON. No LLM, no
network, no clock, no randomness.
"""

from __future__ import annotations

import json

# shields.io named colors used per band — its endpoint schema accepts these.
_BRIGHTGREEN = "brightgreen"
_GREEN = "green"
_YELLOW = "yellow"
_ORANGE = "orange"
_RED = "red"


def _endpoint(label: str, message: str, color: str) -> str:
    """Serialize a shields.io endpoint badge deterministically.

    Keys are sorted and ``ensure_ascii`` keeps the output byte-stable across
    locales, so identical inputs always serialize to identical JSON. ``label`` and
    ``message`` are coerced to ``str`` and JSON-escaping is handled by ``json.dumps``,
    so embedded quotes/newlines can't break the document.
    """
    payload = {
        "schemaVersion": 1,
        "label": str(label),
        "message": str(message),
        "color": color,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=True)


def _grade_color(letter: str) -> str:
    """Map a health-grade letter (A+, A-, B, C-, D, F, ...) to a shields color.

    Banding keys on the first letter only, so every '+'/'-' variant of a band
    shares its color. An empty or unrecognized letter falls through to red — the
    safe, attention-drawing default.
    """
    band = letter.strip()[:1].upper() if letter else ""
    return {
        "A": _BRIGHTGREEN,
        "B": _GREEN,
        "C": _YELLOW,
        "D": _ORANGE,
    }.get(band, _RED)


def grade_badge(letter: str, score: int) -> str:
    """Build an Apex grade badge: ``apex grade | <letter> (<score>)`` JSON.

    Color bands: A* brightgreen, B* green, C* yellow, D* orange, else (F / empty
    / unknown) red. ``score`` is clamped to 0-100 so an out-of-range value can't
    leak into the badge; ``letter`` is shown as-is (escaped on serialize), or
    ``"?"`` when empty so the message is never blank.
    """
    safe_score = _clamp(score, 0, 100)
    shown = letter.strip() if letter and letter.strip() else "?"
    message = f"{shown} ({safe_score})"
    return _endpoint("apex grade", message, _grade_color(letter))


def coverage_badge(pct: int) -> str:
    """Build a coverage badge: ``coverage | <pct>%`` JSON.

    Color thresholds on the clamped 0-100 percentage: >=90 brightgreen, >=75
    green, >=50 yellow, else red.
    """
    safe_pct = _clamp(pct, 0, 100)
    if safe_pct >= 90:
        color = _BRIGHTGREEN
    elif safe_pct >= 75:
        color = _GREEN
    elif safe_pct >= 50:
        color = _YELLOW
    else:
        color = _RED
    return _endpoint("coverage", f"{safe_pct}%", color)


def findings_badge(count: int) -> str:
    """Build a findings badge: ``apex findings | <count>`` JSON.

    Color: 0 findings is brightgreen (clean), 1-9 orange (some debt), and 10 or
    more red (loud). ``count`` is clamped to be non-negative so a stray negative
    can't render as a clean badge.
    """
    safe_count = _clamp(count, 0, None)
    if safe_count == 0:
        color = _BRIGHTGREEN
    elif safe_count < 10:
        color = _ORANGE
    else:
        color = _RED
    return _endpoint("apex findings", str(safe_count), color)


def _clamp(value: int, low: int, high: int | None) -> int:
    """Clamp ``value`` into ``[low, high]`` (no upper bound when ``high`` is None).

    Coerces via ``int`` so a bool or float-shaped input is normalized to a plain
    integer before serialization.
    """
    out = int(value)
    if out < low:
        out = low
    if high is not None and out > high:
        out = high
    return out
