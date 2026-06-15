"""Render Apex's code findings as a single, self-contained HTML report.

A shareable artifact for teams and auditors: this module turns a list of
findings (the same shape the diff reviewer and detectors emit — ``file``,
``line``, ``severity``, ``category``, ``message``) into one standalone HTML
document. All CSS is inlined, every value is HTML-escaped, and the page carries
no remote URL, script, or font and no per-run timestamp — so it opens
identically offline and the same findings yield a byte-identical page.

The public entry point is :func:`findings_to_html`. It mirrors the
self-contained style of :mod:`app.reporting.idea_html`: a summary header with
counts by severity, then a table of findings grouped and sorted deterministically
by severity (high, then medium, then low, then anything else), then path, then
line. An empty findings list yields a valid "no findings" page.

Everything is deterministic and stdlib-only (``html``). No LLM, no network, no
time, no randomness. Read-only: it touches no project files.
"""

from __future__ import annotations

import html
from typing import Any

# Severity ordering for both the summary header and the table: high first.
# Anything unrecognised sorts last (rank ``len(_SEVERITY_ORDER)``) under a
# stable "other" bucket, so a malformed/unknown severity never breaks ordering.
_SEVERITY_ORDER = ("high", "medium", "low")
_SEVERITY_RANK = {sev: i for i, sev in enumerate(_SEVERITY_ORDER)}

# Inlined stylesheet: no external <link>, no @import, no url(...) — the page is
# fully self-contained and renders identically offline. Kept compact and static
# so the document stays byte-identical across runs.
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
.sev { font-weight: 600; }
.sev-high { color: #b91c1c; }
.sev-medium { color: #b45309; }
.sev-low { color: #1d4ed8; }
.sev-other { color: #555; }
table {
  width: 100%; border-collapse: collapse; font-size: 0.88rem;
  background: #fff; border: 1px solid #e3e3e8; border-radius: 6px;
  overflow: hidden;
}
thead th {
  text-align: left; padding: 0.45rem 0.6rem; background: #f1f1f5;
  border-bottom: 1px solid #e3e3e8; font-size: 0.78rem;
  text-transform: uppercase; letter-spacing: 0.04em; color: #555;
}
tbody td { padding: 0.4rem 0.6rem; border-bottom: 1px solid #eee;
  vertical-align: top; }
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover { background: #fafafe; }
.loc { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  white-space: nowrap; color: #333; }
.cat { color: #555; }
.badge {
  display: inline-block; font-size: 0.7rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.04em; padding: 0.05rem 0.4rem;
  border-radius: 999px;
}
.badge-high { background: #fee2e2; color: #991b1b; }
.badge-medium { background: #ffedd5; color: #9a3412; }
.badge-low { background: #dbeafe; color: #1e40af; }
.badge-other { background: #ebedf2; color: #444; }
.empty { color: #666; font-style: italic; }
"""


def _esc(text: object) -> str:
    """Escape arbitrary text for safe HTML embedding (quotes included)."""
    return html.escape(str(text), quote=True)


def _field(finding: Any, name: str, default: Any) -> Any:
    """Read ``name`` from a finding, supporting both objects and mappings.

    Findings are normally :class:`~app.engine.diff_review.ReviewFinding`-style
    objects (attribute access), but a plain ``dict`` of the same keys works too
    — so callers can hand in either without an adapter. Missing values fall back
    to ``default`` rather than raising, keeping the renderer total.
    """
    if isinstance(finding, dict):
        return finding.get(name, default)
    return getattr(finding, name, default)


def _severity(finding: Any) -> str:
    """The finding's severity as a lowercased string (``""`` if absent)."""
    return str(_field(finding, "severity", "") or "").lower()


def _severity_rank(severity: str) -> int:
    """Sort rank for a severity: known ones in order, unknown ones last."""
    return _SEVERITY_RANK.get(severity, len(_SEVERITY_ORDER))


def _severity_class(severity: str) -> str:
    """CSS suffix for a severity badge, falling back to ``other``."""
    return severity if severity in _SEVERITY_RANK else "other"


def _line_no(finding: Any) -> int:
    """The finding's line as an int (``0`` when missing or unparsable).

    A non-integer line is coerced rather than raised on, so a malformed finding
    still renders (and sorts) deterministically next to the rest.
    """
    raw = _field(finding, "line", 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _sort_key(finding: Any) -> tuple[int, str, int, str, str]:
    """Deterministic ordering: severity, then path, then line, then message.

    The trailing ``category``/``message`` components make the order total even
    when two findings share the same (severity, path, line) — so the page is
    insensitive to the order findings happen to be emitted in.
    """
    severity = _severity(finding)
    return (
        _severity_rank(severity),
        str(_field(finding, "file", "")),
        _line_no(finding),
        str(_field(finding, "category", "")),
        str(_field(finding, "message", "")),
    )


def _summary_html(findings: list[Any]) -> str:
    """Render the by-severity count chips for the header.

    A chip per known severity that has at least one finding, in severity order,
    plus a total chip and (if any) a single "other" chip for unrecognised
    severities. Deterministic integer counts, no time/random.
    """
    counts: dict[str, int] = {}
    for finding in findings:
        counts[_severity(finding)] = counts.get(_severity(finding), 0) + 1

    chips = [
        f'    <li><strong>{len(findings)}</strong> '
        f'finding{"" if len(findings) == 1 else "s"}</li>'
    ]
    for sev in _SEVERITY_ORDER:
        if counts.get(sev):
            chips.append(
                f'    <li class="sev sev-{sev}"><strong>{counts[sev]}</strong> '
                f"{_esc(sev)}</li>"
            )
    other = sum(n for sev, n in counts.items() if sev not in _SEVERITY_RANK)
    if other:
        chips.append(
            f'    <li class="sev sev-other"><strong>{other}</strong> other</li>'
        )
    return '  <ul class="summary">\n' + "\n".join(chips) + "\n  </ul>\n"


def _row_html(finding: Any) -> str:
    """Render one finding as an escaped table row."""
    severity = _severity(finding)
    sev_class = _severity_class(severity)
    file = _esc(_field(finding, "file", ""))
    line = _line_no(finding)
    loc = f"{file}:{line}" if file else str(line)
    badge_text = _esc(severity) if severity else "—"
    return (
        "      <tr>\n"
        f'        <td class="loc">{loc}</td>\n'
        f'        <td><span class="badge badge-{sev_class}">{badge_text}'
        "</span></td>\n"
        f'        <td class="cat">{_esc(_field(finding, "category", ""))}</td>\n'
        f'        <td>{_esc(_field(finding, "message", ""))}</td>\n'
        "      </tr>\n"
    )


def _table_html(findings: list[Any]) -> str:
    """Render the findings table, rows sorted by the deterministic key."""
    rows = "".join(_row_html(f) for f in sorted(findings, key=_sort_key))
    return (
        "  <table>\n"
        "    <thead>\n"
        "      <tr>\n"
        "        <th>Location</th>\n"
        "        <th>Severity</th>\n"
        "        <th>Category</th>\n"
        "        <th>Message</th>\n"
        "      </tr>\n"
        "    </thead>\n"
        f"    <tbody>\n{rows}    </tbody>\n"
        "  </table>\n"
    )


def findings_to_html(
    findings: list[Any],
    *,
    title: str = "Apex Findings",
    generated_on: str = "",
) -> str:
    """Render a list of findings as a self-contained HTML report.

    ``findings`` is any iterable of finding records — either
    :class:`~app.engine.diff_review.ReviewFinding`-style objects or plain dicts
    carrying ``file``, ``line``, ``severity``, ``category`` and ``message``.
    The result is a complete ``<!doctype html>`` page: a summary header with
    counts by severity, then a table of findings grouped and sorted
    deterministically by severity (high first), then path, then line.

    Every value is HTML-escaped, all CSS is inlined, and the page references no
    remote URL, script, or font. ``generated_on`` is injectable and defaults to
    the empty string, so two builds are byte-identical (no timestamp leaks into
    the output). An empty ``findings`` list yields a valid "no findings" page.
    """
    items = list(findings)
    safe_title = _esc(title)
    meta = (
        f'  <p class="meta">generated on {_esc(generated_on)}</p>\n'
        if generated_on
        else ""
    )

    if not items:
        body = '  <p class="empty">No findings — nothing to report.</p>\n'
    else:
        body = f"{_summary_html(items)}{_table_html(items)}"

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
