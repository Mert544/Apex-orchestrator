"""Render a self-contained, flat-style SVG badge offline (no shields.io round-trip).

A repo can embed ``apex-grade.svg`` directly in its README and have it render
without any network request. This module produces the badge markup itself: a
two-segment "flat" badge with a gray label segment and a colored message segment,
sized to its text.

Everything here is deterministic and stdlib-only (``html`` only): each function is
a pure function of its inputs, widths come from a fixed character-count heuristic,
colors resolve through a small fixed name->hex map, and label/message are
HTML-escaped. No LLM, no network, no clock, no randomness.
"""

from __future__ import annotations

import html

# Named colors -> hex. Mirrors the shields.io flat palette so callers can pass the
# same names used by ``badge_export``. Unknown names fall back to the "blue" hex.
_COLORS = {
    "brightgreen": "#4c1",
    "green": "#97ca00",
    "yellow": "#dfb317",
    "orange": "#fe7d37",
    "red": "#e05d44",
    "blue": "#007ec6",
    "lightgrey": "#9f9f9f",
}
_DEFAULT_COLOR = _COLORS["blue"]
_LABEL_BG = "#555"  # gray label segment, fixed for every badge

# Width heuristic: monospace-ish estimate. Each character is ~7px wide and each
# segment gets 10px of horizontal padding (5px on each side). This intentionally
# avoids real font metrics so output stays deterministic and dependency-free; the
# segment is slightly generous for wide glyphs, which keeps text from clipping.
_CHAR_PX = 7
_PAD_PX = 10


def _segment_width(text: str) -> int:
    """Estimate a segment's pixel width: ``len(text) * 7 + 10`` (chars * 7px + padding)."""
    return len(text) * _CHAR_PX + _PAD_PX


def _resolve_color(color: str) -> str:
    """Resolve a named color to hex, or pass through a literal ``#hex``.

    Unknown names fall back to the default blue so the message segment is never
    left without a fill.
    """
    if color and color.startswith("#"):
        return color
    return _COLORS.get(color, _DEFAULT_COLOR)


def render_badge_svg(label: str, message: str, color: str = "blue") -> str:
    """Render a flat two-segment badge SVG: gray ``label`` then colored ``message``.

    Width is estimated from character count (~7px/char + 10px padding per segment),
    so a longer label or message yields a wider badge. ``label`` and ``message`` are
    coerced to ``str`` and HTML-escaped so embedded ``<``, ``&``, ``"`` can't break
    the markup. ``color`` is a named color (see the module map) or a literal
    ``#hex``; unknown names fall back to blue.

    Returns a self-contained string starting ``<svg`` and ending ``</svg>``.
    """
    label = str(label)
    message = str(message)
    label_w = _segment_width(label)
    message_w = _segment_width(message)
    total_w = label_w + message_w
    fill = _resolve_color(color)

    esc_label = html.escape(label)
    esc_message = html.escape(message)

    # Text is centered within each segment.
    label_cx = label_w / 2
    message_cx = label_w + message_w / 2

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{total_w}" height="20" role="img" '
        f'aria-label="{esc_label}: {esc_message}">'
        f'<title>{esc_label}: {esc_message}</title>'
        f'<rect width="{total_w}" height="20" fill="{_LABEL_BG}"/>'
        f'<rect x="{label_w}" width="{message_w}" height="20" fill="{fill}"/>'
        f'<g fill="#fff" text-anchor="middle" '
        f'font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">'
        f'<text x="{label_cx}" y="14">{esc_label}</text>'
        f'<text x="{message_cx}" y="14">{esc_message}</text>'
        f'</g>'
        f'</svg>'
    )


def _grade_color(letter: str) -> str:
    """Map a health-grade letter (A/B/C/D/F...) to a named color, keying on the first letter."""
    band = letter.strip()[:1].upper() if letter else ""
    return {
        "A": "brightgreen",
        "B": "green",
        "C": "yellow",
        "D": "orange",
    }.get(band, "red")


def _clamp(value: int, low: int, high: int) -> int:
    """Clamp ``value`` into ``[low, high]``, coercing via ``int`` first."""
    out = int(value)
    if out < low:
        out = low
    if out > high:
        out = high
    return out


def grade_badge_svg(letter: str, score: int) -> str:
    """Build a grade badge SVG: ``apex grade | <letter> (<score>)``.

    Color bands: A* brightgreen, B* green, C* yellow, D* orange, else red.
    ``score`` is clamped to 0-100; ``letter`` shows as-is, or ``"?"`` when empty.
    """
    safe_score = _clamp(score, 0, 100)
    shown = letter.strip() if letter and letter.strip() else "?"
    return render_badge_svg("apex grade", f"{shown} ({safe_score})", _grade_color(letter))


def coverage_badge_svg(pct: int) -> str:
    """Build a coverage badge SVG: ``coverage | <pct>%``.

    Color thresholds on the clamped 0-100 percentage: >=90 brightgreen, >=75
    green, >=50 yellow, else red.
    """
    safe_pct = _clamp(pct, 0, 100)
    if safe_pct >= 90:
        color = "brightgreen"
    elif safe_pct >= 75:
        color = "green"
    elif safe_pct >= 50:
        color = "yellow"
    else:
        color = "red"
    return render_badge_svg("coverage", f"{safe_pct}%", color)
