"""Render the dashboard's "vital signs" hero banner as a self-contained HTML fragment.

This module provides the at-a-glance banner that sits at the top of Apex's
dashboard: a row of "vital-sign" stat tiles (grade, coverage, security findings,
in-scope ratio, idea count, runnable actions) plus an optional one-line "top next
move". It is a pure presentation helper — it neither scans the project nor does
any I/O. The caller supplies already-computed metrics; this module turns them
into structured, class-tagged markup that the dashboard's CSS styles.

The public entry point is :func:`render_vitals`. It is deterministic and
stdlib-only: every caller-supplied string is escaped via :func:`html.escape`,
numbers are coerced defensively with ``int(...)``, tiles whose metric is "not
applicable" (a ``None`` or negative value) are omitted, and the function carries
no timestamp (the page stamps once elsewhere). The same inputs always yield a
byte-identical fragment — no time, no randomness, no network.

No colors or inline styles are emitted: only semantic class names
(``vital``, ``vital-num``, ``vital-label``, ``vitals``, ``vital-top-move``) so
the design lead's stylesheet owns all visual presentation.
"""

from __future__ import annotations

import html


def _coerce_int(value: object) -> int | None:
    """Return ``int(value)`` defensively, or ``None`` if it cannot be coerced.

    A ``None`` value (an explicitly "not applicable" metric) yields ``None``, as
    does anything that does not convert cleanly to an integer. Callers treat a
    ``None`` result as "omit this tile".
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _tile(num: str, label: str) -> str:
    """Render a single vital-sign tile: a big number plus a label.

    Both ``num`` and ``label`` are escaped here so every code path that builds a
    tile is safe regardless of how the values were assembled upstream.
    """
    return (
        "<div class='vital'>"
        f"<span class='vital-num'>{html.escape(num)}</span>"
        f"<span class='vital-label'>{html.escape(label)}</span>"
        "</div>"
    )


def _tile_raw(num: str, label: str) -> str:
    """Render a tile whose ``num`` is already escaped (label is escaped here).

    The grade tile needs a single escape pass over its letter; pre-escaping then
    re-escaping via :func:`_tile` would double-encode. This sibling escapes only
    the label so the caller controls the number slot.
    """
    return (
        "<div class='vital'>"
        f"<span class='vital-num'>{num}</span>"
        f"<span class='vital-label'>{html.escape(label)}</span>"
        "</div>"
    )


def _plural(count: int, singular: str, plural: str) -> str:
    """Return ``singular`` when ``count == 1`` else ``plural``."""
    return singular if count == 1 else plural


def _grade_tile(grade_letter: str, grade_score: int) -> str | None:
    """Render the grade tile, or ``None`` when no grade signal is present.

    Pairs an escaped letter (may be empty) with a coerced score. The letter is
    the prominent number-slot; the score grounds the label.
    """
    grade = (grade_letter or "").strip()
    score = _coerce_int(grade_score)
    if not (grade or score is not None):
        return None
    num = html.escape(grade) if grade else (str(score) if score is not None else "")
    label = f"Grade {score}/100" if score is not None else "Grade"
    return _tile_raw(num, label)


def _count_tile(value: object, singular: str, plural: str) -> str | None:
    """Render a tile whose number is a non-negative count with a pluralised noun.

    Returns ``None`` when the metric is "not applicable" (non-coercible or
    negative), so the caller omits the tile.
    """
    count = _coerce_int(value)
    if count is None or count < 0:
        return None
    return _tile(str(count), _plural(count, singular, plural))


def _percent_tile(value: object, label: str) -> str | None:
    """Render a ``N%`` tile, or ``None`` for a not-applicable metric.

    Returns ``None`` when the metric is non-coercible or negative, so the caller
    omits the tile.
    """
    pct = _coerce_int(value)
    if pct is None or pct < 0:
        return None
    return _tile(f"{pct}%", label)


def _top_move_markup(top_move: str) -> str:
    """Render the optional one-line "top next move", or ``""`` when blank."""
    move = (top_move or "").strip()
    if not move:
        return ""
    return f"<p class='vital-top-move'>{html.escape(move)}</p>"


def render_vitals(
    *,
    grade_letter: str,
    grade_score: int,
    coverage_pct: int,
    security_findings: int,
    scope_pct: int,
    idea_count: int,
    runnable_actions: int,
    top_move: str = "",
) -> str:
    """Render the project's vital signs as an HTML hero fragment.

    Returns a row of vital-sign stat tiles wrapped in ``<div class='vitals'>``,
    optionally followed by a one-line "top next move". Each tile carries a big
    number and a label (e.g. "Grade B-", "Coverage 88%", "0 security findings").

    Every caller-supplied string (``grade_letter``, ``top_move``) is HTML-escaped;
    numeric arguments are coerced via :func:`int` defensively. A tile whose metric
    is "not applicable" — a ``None`` or negative value — is omitted gracefully.
    Empty or degenerate inputs return a minimal valid fragment and never crash.

    The output is deterministic and stdlib-only: no time, no randomness, no I/O.
    """
    candidates = (
        _grade_tile(grade_letter, grade_score),
        _percent_tile(coverage_pct, "Coverage"),
        _count_tile(security_findings, "security finding", "security findings"),
        _percent_tile(scope_pct, "in scope"),
        _count_tile(idea_count, "idea", "ideas"),
        _count_tile(runnable_actions, "runnable now", "runnable now"),
    )
    tiles = "".join(tile for tile in candidates if tile is not None)
    return f"<div class='vitals'>{tiles}</div>{_top_move_markup(top_move)}"
