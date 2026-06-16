"""Render a bundle of analyzer results as one self-contained code-quality report.

Apex's quality analyzers (type-hint coverage, complexity profile, function
length, dead-code scan, API ergonomics, todo/debt, …) each expose a ``.to_dict()``
view: a headline metric or two plus a capped list of named offenders. This module
is a **pure renderer** — the caller runs the analyzers and hands in a mapping of
``analyzer name -> result.to_dict()``; we never invoke an analyzer ourselves, so
the report stays a presentation layer with no project access.

The public entry points are :func:`quality_report_html` (a complete, shareable
``<!doctype html>`` document) and :func:`quality_report_markdown` (a plaintext
equivalent for terminals and PR comments). Both render a summary header followed
by one section/card per analyzer: its headline metric (read defensively from
``overall_ratio`` / ``total`` / ``over_threshold`` and friends) and a small table
of its top offenders (the first ``*offenders*`` / ``*list*`` / ``worst*`` /
``hotspots`` / ``candidates`` / ``items`` list of dicts found on the result).

Because analyzer dicts vary in shape, every key is read defensively with a
fallback rather than assumed — an unfamiliar or partial result still renders.
Each value is HTML-escaped (in the HTML path), all CSS is inlined, and the page
carries no remote URL, script, or font and no per-run timestamp: the same
``results`` mapping yields a byte-identical document. Empty ``results`` yields a
valid "no data" page.

Everything is deterministic and stdlib-only (``html``). No LLM, no network, no
time, no randomness. Read-only: it touches no project files.
"""

from __future__ import annotations

import html
from typing import Any

# Candidate keys, in priority order, under which an analyzer's offender list may
# live. We pick the first key whose value is a non-empty list of dicts. Listing
# the common Apex shapes explicitly (rather than scanning for any list) keeps the
# choice stable when a result carries several list-shaped fields.
_OFFENDER_KEYS = (
    "offenders",
    "worst_modules",
    "worst",
    "hotspots",
    "candidates",
    "items",
    "list",
)

# Candidate keys for a single headline metric, in priority order. The first one
# present is shown prominently in the card header; the rest (that are present)
# become small "stat" chips. ``overall_ratio`` is special-cased as a percentage.
_HEADLINE_KEYS = (
    "overall_ratio",
    "over_threshold",
    "total",
    "max",
    "count",
)

# Secondary count keys surfaced as chips beneath the headline (when present and
# not already used as the headline). Kept explicit and ordered for determinism.
_STAT_KEYS = (
    "total",
    "over_threshold",
    "annotated_functions",
    "total_functions",
    "reported_count",
    "mean",
    "median",
    "max",
    "count",
)

# How many offender rows to render per analyzer. The analyzers already cap their
# own lists; this is a second, render-side guard so a large input stays bounded.
_OFFENDER_CAP = 10

_CSS = """\
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica,
    Arial, sans-serif;
  margin: 0; padding: 2rem; line-height: 1.45; color: #1b1b1f;
  background: #fafafa;
}
h1 { font-size: 1.4rem; margin: 0 0 0.25rem; }
h2 { font-size: 1.05rem; margin: 0 0 0.5rem; }
.meta { color: #666; font-size: 0.85rem; margin: 0 0 1.5rem; }
main { max-width: 70rem; }
.summary {
  display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0 0 1.5rem;
  padding: 0; list-style: none;
}
.summary li {
  font-size: 0.82rem; color: #444; background: #ebedf2;
  border: 1px solid #e3e3e8; border-radius: 999px; padding: 0.2rem 0.6rem;
}
.summary strong { color: #1b1b1f; }
.card {
  background: #fff; border: 1px solid #e3e3e8; border-radius: 8px;
  padding: 1rem 1.2rem; margin: 0 0 1.2rem;
}
.card-head {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.6rem;
  margin: 0 0 0.6rem;
}
.headline { font-size: 1.1rem; font-weight: 700; color: #1d4ed8; }
.stats {
  display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0 0 0.7rem;
  padding: 0; list-style: none;
}
.stats li {
  font-size: 0.76rem; color: #555; background: #f1f1f5;
  border-radius: 999px; padding: 0.12rem 0.5rem;
}
.stats strong { color: #1b1b1f; }
table {
  width: 100%; border-collapse: collapse; font-size: 0.86rem;
}
thead th {
  text-align: left; padding: 0.4rem 0.55rem; background: #f6f6f9;
  border-bottom: 1px solid #e3e3e8; font-size: 0.74rem;
  text-transform: uppercase; letter-spacing: 0.04em; color: #555;
}
tbody td { padding: 0.35rem 0.55rem; border-bottom: 1px solid #eee;
  vertical-align: top; }
tbody tr:last-child td { border-bottom: none; }
.k { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: #333; }
.empty { color: #666; font-style: italic; }
"""


def _esc(text: object) -> str:
    """Escape arbitrary text for safe HTML embedding (quotes included)."""
    return html.escape(str(text), quote=True)


def _fmt(value: Any) -> str:
    """Format a metric value for display: ratios as percent, ints plainly.

    A float in ``[0, 1]`` is shown as a percentage (the common
    ``overall_ratio``/``ratio`` shape); other floats are shown to two decimals;
    everything else is stringified. Pure and deterministic — no locale, no time.
    """
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if 0.0 <= value <= 1.0:
            return f"{value * 100:.0f}%"
        return f"{value:.2f}"
    return str(value)


def _offender_list(result: dict[str, Any]) -> list[dict[str, Any]]:
    """The first non-empty list-of-dicts found under a known offender key.

    Reads ``result`` defensively: tries each :data:`_OFFENDER_KEYS` in priority
    order and returns the first value that is a list whose entries are dicts,
    capped at :data:`_OFFENDER_CAP`. Returns ``[]`` when nothing matches, so a
    metric-only analyzer (or a malformed result) renders without a table.
    """
    if not isinstance(result, dict):
        return []
    for key in _OFFENDER_KEYS:
        value = result.get(key)
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            return value[:_OFFENDER_CAP]
    return []


def _headline(result: dict[str, Any]) -> str:
    """The card's headline metric string, or ``""`` when none is present.

    Picks the first present key from :data:`_HEADLINE_KEYS`, formatted via
    :func:`_fmt` and labelled. ``overall_ratio`` reads as ``"<pct> covered"``;
    the others read as ``"<n> <key>"``. Defensive: a result lacking all of them
    yields an empty headline rather than raising.
    """
    if not isinstance(result, dict):
        return ""
    for key in _HEADLINE_KEYS:
        if key in result and not isinstance(result[key], (list, dict)):
            value = _fmt(result[key])
            if key == "overall_ratio":
                return f"{value} covered"
            return f"{value} {key.replace('_', ' ')}"
    return ""


def _stats(result: dict[str, Any], *, exclude: str = "") -> list[tuple[str, Any]]:
    """Ordered (label, value) pairs for the secondary stat chips.

    Walks :data:`_STAT_KEYS` in order and keeps those present on ``result`` as
    scalars, skipping ``exclude`` (the key already used as the headline) so a
    value never shows twice. Deterministic ordering independent of dict order.
    """
    if not isinstance(result, dict):
        return []
    pairs: list[tuple[str, Any]] = []
    for key in _STAT_KEYS:
        if key == exclude:
            continue
        if key in result and not isinstance(result[key], (list, dict)):
            pairs.append((key.replace("_", " "), result[key]))
    return pairs


def _headline_key(result: dict[str, Any]) -> str:
    """The key chosen by :func:`_headline` (``""`` if none), for stat exclusion."""
    if not isinstance(result, dict):
        return ""
    for key in _HEADLINE_KEYS:
        if key in result and not isinstance(result[key], (list, dict)):
            return key
    return ""


def _offender_columns(offenders: list[dict[str, Any]]) -> list[str]:
    """Deterministic, union-ordered column list across all offender rows.

    Columns are the union of every offender's keys; order is first-seen across
    rows (rows are already in the analyzer's deterministic order), so two equal
    inputs always produce the same header. Nested list/dict values are excluded
    — only scalar cells are tabulated, keeping the table flat and total.
    """
    columns: list[str] = []
    for row in offenders:
        for key in row:
            if key not in columns and not isinstance(row.get(key), (list, dict)):
                columns.append(key)
    return columns


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def _summary_html(results: dict[str, dict]) -> str:
    """Header chips: analyzer count plus each analyzer's headline (if any)."""
    chips = [
        f'    <li><strong>{len(results)}</strong> '
        f'analyzer{"" if len(results) == 1 else "s"}</li>'
    ]
    for name in results:
        headline = _headline(results.get(name) or {})
        if headline:
            chips.append(
                f'    <li><strong>{_esc(name)}</strong> {_esc(headline)}</li>'
            )
    return '  <ul class="summary">\n' + "\n".join(chips) + "\n  </ul>\n"


def _offender_table_html(offenders: list[dict[str, Any]]) -> str:
    """Render the offenders as an escaped table, or ``""`` when there are none."""
    if not offenders:
        return ""
    columns = _offender_columns(offenders)
    if not columns:
        return ""
    head = "".join(f"        <th>{_esc(c)}</th>\n" for c in columns)
    rows = ""
    for row in offenders:
        cells = "".join(
            f'        <td class="k">{_esc(_fmt(row.get(c, "")))}</td>\n'
            for c in columns
        )
        rows += f"      <tr>\n{cells}      </tr>\n"
    return (
        "  <table>\n"
        f"    <thead>\n      <tr>\n{head}      </tr>\n    </thead>\n"
        f"    <tbody>\n{rows}    </tbody>\n"
        "  </table>\n"
    )


def _card_html(name: str, result: dict[str, Any]) -> str:
    """Render one analyzer's section: headline, stat chips, offender table."""
    result = result if isinstance(result, dict) else {}
    headline = _headline(result)
    headline_html = (
        f'    <span class="headline">{_esc(headline)}</span>\n' if headline else ""
    )
    stats = _stats(result, exclude=_headline_key(result))
    stats_html = ""
    if stats:
        chips = "".join(
            f'    <li><strong>{_esc(_fmt(v))}</strong> {_esc(label)}</li>\n'
            for label, v in stats
        )
        stats_html = f'  <ul class="stats">\n{chips}  </ul>\n'
    table = _offender_table_html(_offender_list(result))
    body = stats_html + table
    if not body:
        body = '  <p class="empty">No detail to show.</p>\n'
    return (
        '  <section class="card">\n'
        f"    <div class=\"card-head\">\n"
        f"      <h2>{_esc(name)}</h2>\n"
        f"{headline_html}"
        "    </div>\n"
        f"{body}"
        "  </section>\n"
    )


def quality_report_html(
    results: dict[str, dict],
    *,
    title: str = "Apex Code Quality",
    project: str = "",
    generated: str = "",
) -> str:
    """Render analyzer results as a self-contained HTML code-quality report.

    ``results`` maps an analyzer name to that analyzer's ``.to_dict()`` output;
    this function does **not** run the analyzers — it is a pure renderer. The
    result is a complete ``<!doctype html>`` page: a summary header (analyzer
    count plus each analyzer's headline metric) followed by one card per
    analyzer showing its headline, secondary stat chips, and a small table of
    its top offenders (read defensively from ``offenders``/``worst_modules``/
    ``hotspots``/``candidates``/``items`` and similar keys).

    Every value is HTML-escaped, all CSS is inlined, and the page references no
    remote URL, script, or font. ``project`` is an optional subtitle and
    ``generated`` is an injectable build label that defaults to the empty string,
    so two builds of the same ``results`` are byte-identical (no timestamp leaks
    into the output). Empty ``results`` yields a valid "no data" page.
    """
    safe_title = _esc(title)
    meta_bits = []
    if project:
        meta_bits.append(_esc(project))
    if generated:
        meta_bits.append(f"generated {_esc(generated)}")
    meta = (
        f'  <p class="meta">{" · ".join(meta_bits)}</p>\n' if meta_bits else ""
    )

    if not results:
        body = '  <p class="empty">No analyzer results — nothing to report.</p>\n'
    else:
        body = _summary_html(results) + "".join(
            _card_html(name, results.get(name) or {}) for name in results
        )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{safe_title}</title>\n"
        f"  <style>\n{_CSS}  </style>\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>{safe_title}</h1>\n"
        f"{meta}"
        "  <main>\n"
        f"{body}"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _offender_table_md(offenders: list[dict[str, Any]]) -> str:
    """Render the offenders as a GitHub-flavoured Markdown table (or ``""``)."""
    if not offenders:
        return ""
    columns = _offender_columns(offenders)
    if not columns:
        return ""
    header = "| " + " | ".join(columns) + " |\n"
    divider = "| " + " | ".join("---" for _ in columns) + " |\n"
    rows = ""
    for row in offenders:
        cells = " | ".join(_fmt(row.get(c, "")) for c in columns)
        rows += f"| {cells} |\n"
    return header + divider + rows


def quality_report_markdown(
    results: dict[str, dict],
    *,
    title: str = "Apex Code Quality",
    project: str = "",
    generated: str = "",
) -> str:
    """Render analyzer results as a plaintext Markdown code-quality report.

    The Markdown sibling of :func:`quality_report_html`: same pure-renderer
    contract and the same defensive key reading, formatted for terminals and PR
    comments. Produces a top-level title (with optional ``project``/``generated``
    line), then a ``##`` section per analyzer with its headline, a stat line, and
    a Markdown table of its top offenders. Empty ``results`` yields a short "no
    data" note. Deterministic and stdlib-only — same input, same bytes.
    """
    lines = [f"# {title}"]
    meta_bits = []
    if project:
        meta_bits.append(project)
    if generated:
        meta_bits.append(f"generated {generated}")
    if meta_bits:
        lines.append("")
        lines.append(" · ".join(meta_bits))

    if not results:
        lines.append("")
        lines.append("_No analyzer results — nothing to report._")
        return "\n".join(lines) + "\n"

    for name in results:
        result = results.get(name) or {}
        result = result if isinstance(result, dict) else {}
        lines.append("")
        lines.append(f"## {name}")
        headline = _headline(result)
        if headline:
            lines.append("")
            lines.append(f"**{headline}**")
        stats = _stats(result, exclude=_headline_key(result))
        if stats:
            lines.append("")
            lines.append(
                " · ".join(f"{_fmt(v)} {label}" for label, v in stats)
            )
        table = _offender_table_md(_offender_list(result))
        if table:
            lines.append("")
            lines.append(table.rstrip("\n"))
    return "\n".join(lines) + "\n"
