"""Standalone, deterministic, stdlib-only SVG chart helpers for the dashboard.

Every function is pure: it takes plain values and returns a self-contained inline
``<svg>...</svg>`` string. No external libraries, no JavaScript, no network access,
no web fonts, and no clock/randomness — so the dashboard stays 100% self-contained
and the same input always yields byte-identical output.

Only caller-supplied *text* (grade letters, bar labels) is HTML-escaped via
``html.escape``; pure geometry is computed and needs no escaping.
"""

from __future__ import annotations

import html
import math

# --- shared palette / helpers ----------------------------------------------

_GREEN = "#2e9e5b"
_AMBER = "#d9a300"
_RED = "#d24b3e"
_TRACK = "#e6e6e6"
_TEXT = "#222222"
_MUTED = "#777777"
_BLUE = "#2f6fdb"


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp ``value`` into the inclusive ``[lo, hi]`` range."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _num(value: float) -> str:
    """Format a number deterministically: trim trailing zeros, no locale."""
    rounded = round(float(value), 3)
    if rounded == int(rounded):
        return str(int(rounded))
    text = f"{rounded:.3f}".rstrip("0").rstrip(".")
    return text


def _band_color(score: float) -> str:
    """Pick a traffic-light color by score band (0-100)."""
    if score >= 80:
        return _GREEN
    if score >= 50:
        return _AMBER
    return _RED


# --- public chart functions -------------------------------------------------

def grade_gauge(score: int, letter: str) -> str:
    """Donut/arc gauge for a 0-100 ``score`` with the ``letter`` grade centered.

    The arc fill is proportional to the score and colored by band. ``letter`` is
    display text and is HTML-escaped.
    """
    s = int(_clamp(score, 0, 100))
    safe_letter = html.escape(str(letter))
    color = _band_color(s)

    size = 120
    cx = cy = size / 2
    radius = 48
    stroke = 12
    circumference = 2 * math.pi * radius
    # Fraction of the ring filled; rotate so the arc starts at 12 o'clock.
    filled = circumference * (s / 100.0)
    dash = f"{_num(filled)} {_num(circumference)}"

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" role="img" aria-label="Grade {safe_letter}, '
        f'score {s} of 100">'
        f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="{radius}" fill="none" '
        f'stroke="{_TRACK}" stroke-width="{stroke}"/>'
        f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="{radius}" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-dasharray="{dash}" '
        f'transform="rotate(-90 {_num(cx)} {_num(cy)})"/>'
        f'<text x="{_num(cx)}" y="{_num(cy - 4)}" text-anchor="middle" '
        f'dominant-baseline="middle" font-family="sans-serif" font-size="34" '
        f'font-weight="bold" fill="{_TEXT}">{safe_letter}</text>'
        f'<text x="{_num(cx)}" y="{_num(cy + 22)}" text-anchor="middle" '
        f'dominant-baseline="middle" font-family="sans-serif" font-size="13" '
        f'fill="{_MUTED}">{s}/100</text>'
        f'</svg>'
    )


def scope_bar(analyzed_pct: int) -> str:
    """Horizontal proportional bar of analysed (Python) vs out-of-scope remainder."""
    pct = int(_clamp(analyzed_pct, 0, 100))

    width = 320
    height = 46
    bar_y = 6
    bar_h = 18
    bar_w = width - 4
    x0 = 2
    fill_w = bar_w * (pct / 100.0)

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{pct}% analysed (Python)">'
        f'<rect x="{x0}" y="{bar_y}" width="{_num(bar_w)}" height="{bar_h}" rx="4" '
        f'fill="{_TRACK}"/>'
        f'<rect x="{x0}" y="{bar_y}" width="{_num(fill_w)}" height="{bar_h}" rx="4" '
        f'fill="{_BLUE}"/>'
        f'<text x="{x0}" y="{_num(bar_y + bar_h + 16)}" font-family="sans-serif" '
        f'font-size="12" fill="{_TEXT}">{pct}% analysed (Python)</text>'
        f'</svg>'
    )


def metric_bars(rows: list[tuple[str, float]]) -> str:
    """A stack of labelled horizontal bars; each row is ``(label, fraction_0_to_1)``.

    Labels are HTML-escaped. Empty input returns a minimal valid SVG.
    """
    rows = list(rows or [])
    width = 320
    row_h = 24
    pad = 6
    label_w = 120
    track_x = label_w
    track_w = width - label_w - pad

    if not rows:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{row_h}" '
            f'viewBox="0 0 {width} {row_h}" role="img" aria-label="no metrics"></svg>'
        )

    height = row_h * len(rows) + pad
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="metric bars">'
    ]
    for i, (label, fraction) in enumerate(rows):
        frac = _clamp(float(fraction), 0.0, 1.0)
        safe_label = html.escape(str(label))
        y = i * row_h + pad
        bar_y = y + 4
        bar_h = 12
        fill_w = track_w * frac
        pct = int(round(frac * 100))
        color = _band_color(pct)
        parts.append(
            f'<text x="0" y="{_num(bar_y + bar_h - 2)}" font-family="sans-serif" '
            f'font-size="11" fill="{_TEXT}">{safe_label}</text>'
            f'<rect x="{track_x}" y="{bar_y}" width="{_num(track_w)}" '
            f'height="{bar_h}" rx="3" fill="{_TRACK}"/>'
            f'<rect x="{track_x}" y="{bar_y}" width="{_num(fill_w)}" '
            f'height="{bar_h}" rx="3" fill="{color}"/>'
        )
    parts.append('</svg>')
    return "".join(parts)


_SEGMENT_PALETTE = (_BLUE, _GREEN, _AMBER, _RED, _MUTED)


def stacked_bar(segments: list[tuple[str, float]]) -> str:
    """Horizontal stacked composition bar of proportional parts.

    Each segment is ``(label, weight)``; weights are clamped to ``>= 0`` and
    normalised against their total so the bar always fills its track exactly.
    Segments are colored by cycling the shared palette, and a small legend of
    escaped ``label pct%`` entries is drawn beneath. Empty input (or an all-zero
    total) returns a minimal valid SVG.
    """
    segments = list(segments or [])
    width = 320
    bar_y = 6
    bar_h = 18
    bar_w = width - 4
    x0 = 2

    weights = [max(0.0, float(w)) for _, w in segments]
    total = sum(weights)

    if not segments or total <= 0.0:
        height = bar_h + bar_y + 4
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="no composition data">'
            f'<rect x="{x0}" y="{bar_y}" width="{_num(bar_w)}" height="{bar_h}" rx="4" '
            f'fill="{_TRACK}"/>'
            f'</svg>'
        )

    legend_h = 16 * len(segments)
    height = bar_y + bar_h + 6 + legend_h
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="composition">',
        f'<rect x="{x0}" y="{bar_y}" width="{_num(bar_w)}" height="{bar_h}" rx="4" '
        f'fill="{_TRACK}"/>',
    ]

    cursor = float(x0)
    legend_y = bar_y + bar_h + 6
    for i, ((label, _weight), weight) in enumerate(zip(segments, weights)):
        frac = weight / total
        seg_w = bar_w * frac
        color = _SEGMENT_PALETTE[i % len(_SEGMENT_PALETTE)]
        safe_label = html.escape(str(label))
        pct = int(round(frac * 100))
        parts.append(
            f'<rect x="{_num(cursor)}" y="{bar_y}" width="{_num(seg_w)}" '
            f'height="{bar_h}" fill="{color}"/>'
        )
        ly = legend_y + i * 16
        parts.append(
            f'<rect x="{x0}" y="{_num(ly + 1)}" width="10" height="10" rx="2" '
            f'fill="{color}"/>'
            f'<text x="{x0 + 14}" y="{_num(ly + 10)}" font-family="sans-serif" '
            f'font-size="11" fill="{_TEXT}">{safe_label} {pct}%</text>'
        )
        cursor += seg_w
    parts.append('</svg>')
    return "".join(parts)


def sparkline(values: list[float]) -> str:
    """Tiny inline trend line for a sequence of values. Empty-safe."""
    values = [float(v) for v in (values or [])]
    width = 120
    height = 28
    pad = 2

    if not values:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="no trend data"></svg>'
        )

    lo = min(values)
    hi = max(values)
    span = hi - lo
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad

    n = len(values)
    if n == 1:
        points = [(pad, height / 2.0)]
    else:
        points = []
        for i, v in enumerate(values):
            x = pad + inner_w * (i / (n - 1))
            # Normalize to [0,1]; flat series sits on the mid-line.
            norm = 0.5 if span == 0 else (v - lo) / span
            y = pad + inner_h * (1.0 - norm)
            points.append((x, y))

    point_str = " ".join(f"{_num(x)},{_num(y)}" for x, y in points)
    last_x, last_y = points[-1]

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="trend">'
        f'<polyline points="{point_str}" fill="none" stroke="{_BLUE}" '
        f'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{_num(last_x)}" cy="{_num(last_y)}" r="2" fill="{_BLUE}"/>'
        f'</svg>'
    )
