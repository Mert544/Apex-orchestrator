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
    tiles: list[str] = []

    # Grade: pairs an escaped letter (may be empty) with a coerced score. The
    # letter is the prominent number-slot; the score grounds the label.
    grade = (grade_letter or "").strip()
    score = _coerce_int(grade_score)
    if grade or score is not None:
        num = html.escape(grade) if grade else (str(score) if score is not None else "")
        label = f"Grade {score}/100" if score is not None else "Grade"
        # _tile escapes again; pre-escaping `grade` would double-encode, so build
        # the grade tile inline to keep a single escape pass over the letter.
        tiles.append(
            "<div class='vital'>"
            f"<span class='vital-num'>{num}</span>"
            f"<span class='vital-label'>{html.escape(label)}</span>"
            "</div>"
        )

    coverage = _coerce_int(coverage_pct)
    if coverage is not None and coverage >= 0:
        tiles.append(_tile(f"{coverage}%", "Coverage"))

    findings = _coerce_int(security_findings)
    if findings is not None and findings >= 0:
        noun = "security finding" if findings == 1 else "security findings"
        tiles.append(_tile(str(findings), noun))

    scope = _coerce_int(scope_pct)
    if scope is not None and scope >= 0:
        tiles.append(_tile(f"{scope}%", "in scope"))

    ideas = _coerce_int(idea_count)
    if ideas is not None and ideas >= 0:
        noun = "idea" if ideas == 1 else "ideas"
        tiles.append(_tile(str(ideas), noun))

    runnable = _coerce_int(runnable_actions)
    if runnable is not None and runnable >= 0:
        tiles.append(_tile(str(runnable), "runnable now"))

    parts = [f"<div class='vitals'>{''.join(tiles)}</div>"]

    move = (top_move or "").strip()
    if move:
        parts.append(
            f"<p class='vital-top-move'>{html.escape(move)}</p>"
        )

    return "".join(parts)
