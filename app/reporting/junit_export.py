"""JUnit XML export for Apex findings — findings as "test results" in any CI.

Jenkins, GitLab, GitHub Actions, and CircleCI all natively render JUnit XML in
their test-report UI. Emitting Apex's deterministic findings as a JUnit suite
turns a code-quality scan into a familiar pass/fail report: each finding becomes
a failing ``<testcase>``, a clean file becomes a passing suite. Drop the XML at
the path your CI scans for test reports and Apex shows up alongside the rest.

Pure, deterministic, stdlib-only (``xml.sax.saxutils``). Same findings in →
byte-identical XML out: no clock, no timestamp attribute, no randomness, no
network. Every attribute and text value is XML-escaped, so a finding message
carrying ``<``, ``&``, ``>`` or ``"`` can never break the document.

A "finding" is duck-typed: any object exposing ``file`` / ``line`` /
``category`` / ``severity`` / ``message`` / ``fix_kind`` attributes (e.g.
:class:`app.engine.diff_review.ReviewFinding`) works, as does a plain ``dict``
with those keys. Missing fields fall back to safe defaults, so a line-level
:class:`app.engine.detectors.Issue` (no ``file``) exports fine too.
"""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape, quoteattr

# Where a finding has no file of its own (e.g. a line-level Issue), group it here
# so every testcase still carries a classname CI can render.
_NO_FILE = "<unknown>"


def _field(finding: Any, name: str, default: str = "") -> str:
    """Read ``name`` off a finding (attribute or dict key) as a string.

    Duck-typed so a :class:`ReviewFinding`, a detector :class:`Issue`, or a plain
    ``dict`` all work. A missing/``None`` value yields ``default``.
    """
    if isinstance(finding, dict):
        value = finding.get(name, default)
    else:
        value = getattr(finding, name, default)
    if value is None:
        return default
    return str(value)


def _classname(finding: Any) -> str:
    """The CI "classname" for a finding — its file, or a stable placeholder."""
    return _field(finding, "file", _NO_FILE) or _NO_FILE


def _testcase_name(finding: Any) -> str:
    """A stable, human-readable testcase name: ``<rule-or-category>:<line>``.

    Uses the detector routing key (``fix_kind``) when present — it names the
    specific rule — and falls back to the broader ``category``. The line number
    is appended so two findings of the same rule in one file get distinct
    testcase names (CI keys testcases by classname+name).
    """
    rule = _field(finding, "fix_kind") or _field(finding, "category") or "finding"
    line = _field(finding, "line")
    return f"{rule}:{line}" if line else rule


def _failure_message(finding: Any) -> str:
    """The short failure summary (the finding's message), never empty."""
    return _field(finding, "message") or "finding"


def _failure_type(finding: Any) -> str:
    """The JUnit failure ``type`` — the finding's severity (high/medium/low)."""
    return _field(finding, "severity") or "finding"


def _failure_detail(finding: Any) -> str:
    """The verbose failure body shown when a testcase is expanded in CI.

    Echoes the structured fields (severity, category, location, rule) plus the
    message, so the report is self-describing even without the original finding.
    """
    severity = _field(finding, "severity") or "unknown"
    category = _field(finding, "category") or "finding"
    location = _classname(finding)
    line = _field(finding, "line")
    if line:
        location = f"{location}:{line}"
    rule = _field(finding, "fix_kind")
    lines = [
        f"severity: {severity}",
        f"category: {category}",
        f"location: {location}",
    ]
    if rule:
        lines.append(f"rule: {rule}")
    lines.append("")
    lines.append(_failure_message(finding))
    return "\n".join(lines)


def _sort_key(finding: Any) -> tuple:
    """Deterministic ordering: by file, line, rule/category, then message.

    Line is sorted numerically when it parses as an int (so 2 precedes 10), with
    a stable string fallback for non-numeric values.
    """
    raw_line = _field(finding, "line", "0")
    try:
        line = (0, int(raw_line))
    except ValueError:
        line = (1, 0)
    return (
        _classname(finding),
        line,
        raw_line,
        _field(finding, "fix_kind") or _field(finding, "category"),
        _failure_message(finding),
    )


def to_junit_xml(findings: Any, *, suite_name: str = "apex") -> str:
    """Render Apex ``findings`` as a JUnit XML document (a single suite).

    Each finding becomes a ``<testcase>`` carrying a ``<failure>`` with the
    finding's message and severity; ``tests`` and ``failures`` on the
    ``<testsuite>`` count the findings exactly. An empty ``findings`` iterable
    yields a valid, passing suite (``tests="0" failures="0"`` with no
    testcases). Output is deterministic: findings are sorted by a stable key and
    no timestamp/clock/random value is emitted.

    All attribute and text values are XML-escaped, so a message containing
    ``<``, ``&``, ``>`` or ``"`` produces a well-formed document.
    """
    ordered = sorted(findings, key=_sort_key)
    count = len(ordered)

    suite_attr = quoteattr(suite_name)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append(f'<testsuites name={suite_attr} tests="{count}" failures="{count}">')
    lines.append(
        f"  <testsuite name={suite_attr} "
        f'tests="{count}" failures="{count}" errors="0" skipped="0">'
    )
    for finding in ordered:
        classname = quoteattr(_classname(finding))
        name = quoteattr(_testcase_name(finding))
        message = quoteattr(_failure_message(finding))
        ftype = quoteattr(_failure_type(finding))
        detail = escape(_failure_detail(finding))
        lines.append(f"    <testcase classname={classname} name={name}>")
        lines.append(f"      <failure message={message} type={ftype}>{detail}</failure>")
        lines.append("    </testcase>")
    lines.append("  </testsuite>")
    lines.append("</testsuites>")
    return "\n".join(lines) + "\n"
