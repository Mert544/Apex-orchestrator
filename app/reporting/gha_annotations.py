"""GitHub Actions annotations export — Apex findings inline on the PR diff.

A SARIF upload lands findings on the "Security" tab; a *workflow-command*
annotation lands them right on the changed lines of the pull request, as the
familiar red/yellow/blue gutter markers, with zero extra GitHub configuration.
A step that simply prints these lines to stdout makes every Apex finding show up
inline on the PR.

Each annotation is one line of the form::

    ::error file={path},line={line},title={title}::{message}

(also ``::warning`` and ``::notice``). We emit only ``file``, ``line`` and
``title`` properties — Apex's detectors report at line granularity and carry no
column, so a ``col`` property would be a fabricated value.

Severity mapping (Apex ``severity`` -> GitHub command):
    high   -> error    (red — blocks the eye, mirrors SARIF ``error``)
    medium -> warning  (yellow)
    low    -> notice   (blue — informational)
    anything else -> notice (safe default for an unknown severity)

Escaping follows GitHub's workflow-command rules exactly:
    * in the MESSAGE:        ``%`` -> ``%25``, ``\\r`` -> ``%0D``, ``\\n`` -> ``%0A``
    * in a property VALUE:   the three above, plus ``:`` -> ``%3A``, ``,`` -> ``%2C``
``%`` is escaped first so the ``%`` in a later replacement is never re-escaped.

Pure function of the findings: same findings in, same string out. No clock,
randomness, or network — stdlib-only and deterministic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:  # pragma: no cover
    from app.engine.diff_review import ReviewFinding

# Apex severity (high | medium | low) -> GitHub Actions workflow command.
_COMMAND = {"high": "error", "medium": "warning", "low": "notice"}
_DEFAULT_COMMAND = "notice"


def _escape_message(text: str) -> str:
    """Escape annotation *message* data per GitHub's rules.

    ``%`` is replaced first so the literal ``%`` introduced by ``%0D``/``%0A``
    (and the property escapes) is never double-escaped.
    """
    return (
        text.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )


def _escape_property(value: str) -> str:
    """Escape an annotation *property value* per GitHub's rules.

    A property value must additionally escape ``:`` and ``,`` (the delimiters of
    the ``key=value`` property list), on top of the message escapes.
    """
    return (
        _escape_message(value)
        .replace(":", "%3A")
        .replace(",", "%2C")
    )


def _title(finding: "ReviewFinding") -> str:
    """Short, stable annotation title: the detector routing key, else category.

    Mirrors the SARIF rule-id convention (``apex/<fix_kind or category>``) so the
    same finding reads consistently across both exporters.
    """
    key = (getattr(finding, "fix_kind", "") or getattr(finding, "category", "")
           or "finding")
    return f"apex/{key}"


def _message(finding: "ReviewFinding") -> str:
    """The annotation body: the finding message, plus a suggested fix when known.

    Matches :func:`app.engine.sarif_export._message` so the inline annotation and
    the Security-tab result carry the same wording.
    """
    text = finding.message
    suggestion = getattr(finding, "suggestion", None)
    if suggestion:
        old, new = suggestion
        text += f" Suggested fix: replace `{old}` with `{new}`."
    elif getattr(finding, "auto_fixable", False):
        text += " Auto-fixable by `apex maintain`."
    return text


def _annotation(finding: "ReviewFinding") -> str:
    """Render one finding as a single GitHub Actions workflow-command line."""
    command = _COMMAND.get(finding.severity, _DEFAULT_COMMAND)
    props = (
        f"file={_escape_property(finding.file)},"
        f"line={_escape_property(str(max(int(finding.line), 1)))},"
        f"title={_escape_property(_title(finding))}"
    )
    return f"::{command} {props}::{_escape_message(_message(finding))}"


def to_gha_annotations_lines(findings: Iterable["ReviewFinding"]) -> list[str]:
    """Each finding rendered as one workflow-command line, in finding order.

    Order is preserved exactly as given (the caller — the diff reviewer — already
    emits findings in a deterministic document order), so the result is a pure,
    stable function of the input.
    """
    return [_annotation(f) for f in findings]


def to_gha_annotations(findings: Iterable["ReviewFinding"]) -> str:
    """Findings as newline-joined GitHub Actions annotation commands.

    Printing this to a workflow step's stdout surfaces every finding inline on
    the pull request. An empty/zero-finding input yields the empty string (no
    trailing newline) so a step prints nothing.
    """
    return "\n".join(to_gha_annotations_lines(findings))
