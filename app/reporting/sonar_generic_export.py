"""Export Apex findings as SonarQube "Generic Issue Import" JSON.

SonarQube is the market-leading code-quality dashboard, and it ingests
third-party findings through one documented format: the *Generic Issue Import*
report (``sonar.externalIssuesReportPaths``). Emitting Apex's deterministic
detector findings in that exact shape lets a team feed ``apex review`` straight
into their existing SonarQube quality gate — drop-in interop, no glue code.

The output is a single JSON object::

    {"issues": [
        {"engineId": "apex",
         "ruleId": "apex/eval",
         "severity": "BLOCKER",
         "type": "VULNERABILITY",
         "primaryLocation": {
             "message": "...",
             "filePath": "app/foo.py",
             "textRange": {"startLine": 12}}}
    ]}

Both of Apex's finding shapes are accepted: the canonical
:class:`app.engine.detectors.Issue` (no ``file`` field) and the richer
:class:`app.engine.diff_review.ReviewFinding` (carries ``file``), as well as a
plain dict with the same keys. Each is read defensively through attribute- and
key-lookup so a caller can hand over whatever it already has.

Everything here is deterministic and pure stdlib (``json`` only): the issue list
is sorted by a stable key, the category/severity → SonarQube mapping is a fixed
table with a sane default, and ``startLine`` is clamped to ``>= 1`` (SonarQube
rejects a non-positive line). No LLM, no clock, no randomness, no network — the
same findings always serialize to byte-identical JSON.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

# This engine's stable identifier in the SonarQube "external issues" namespace.
ENGINE_ID = "apex"

# SonarQube's fixed enumerations (validated by its import; an unknown value is
# rejected). We map every Apex finding onto exactly one member of each.
_SEVERITIES = ("INFO", "MINOR", "MAJOR", "CRITICAL", "BLOCKER")
_TYPES = ("BUG", "VULNERABILITY", "CODE_SMELL")

# --- Apex category → SonarQube issue type -----------------------------------
# Apex categories (the ``category`` field on every finding) are, exhaustively:
#   security    -> VULNERABILITY  (eval/pickle/SQL/secret/... — a real exploit)
#   bug         -> BUG            (correctness: mutable default, dead code, ...)
#   style       -> CODE_SMELL     (idiom nits: `== None`, empty `dict()`, ...)
#   docs        -> CODE_SMELL     (missing docstrings — maintainability)
#   convention  -> CODE_SMELL     (team rewrite-rule violations)
#   refactor    -> CODE_SMELL     (extract/inline/duplication suggestions)
# Anything unrecognised falls back to CODE_SMELL: the least-alarming bucket, so
# a new Apex category never silently inflates a SonarQube quality gate.
_CATEGORY_TYPE = {
    "security": "VULNERABILITY",
    "bug": "BUG",
    "style": "CODE_SMELL",
    "docs": "CODE_SMELL",
    "convention": "CODE_SMELL",
    "refactor": "CODE_SMELL",
}
_DEFAULT_TYPE = "CODE_SMELL"

# --- Apex severity → SonarQube severity --------------------------------------
# Apex grades severity as high | medium | low. SonarQube's five-level scale is
# coarser at the top for security, so a security finding is lifted one notch:
# a high-severity vulnerability is a BLOCKER, a high non-security finding is
# CRITICAL. Medium maps to MAJOR, low to MINOR, and an unknown severity falls
# back to the neutral INFO (never a gate-failing level for an unknown input).
_SEVERITY_BASE = {
    "high": "CRITICAL",
    "medium": "MAJOR",
    "low": "MINOR",
}
_DEFAULT_SEVERITY = "INFO"


def _get(finding: Any, *names: str, default: Any = None) -> Any:
    """Read the first present field from ``finding`` by attribute or dict key.

    Accepts a dataclass/object finding (``finding.category``) or a plain mapping
    (``finding["category"]``) and tries each candidate name in order, so the
    exporter works against ``Issue``, ``ReviewFinding``, and dict findings alike.
    """
    if isinstance(finding, dict):
        for name in names:
            if name in finding:
                return finding[name]
        return default
    for name in names:
        if hasattr(finding, name):
            return getattr(finding, name)
    return default


def _issue_type(category: Any) -> str:
    """SonarQube issue type for an Apex category (CODE_SMELL when unknown)."""
    key = str(category).strip().lower() if category is not None else ""
    return _CATEGORY_TYPE.get(key, _DEFAULT_TYPE)


def _severity(category: Any, severity: Any) -> str:
    """SonarQube severity for an Apex (category, severity) pair.

    A *high*-severity *security* finding becomes BLOCKER (SonarQube's top
    level — a vulnerability you must not ship); every other mapping follows the
    fixed high/medium/low → CRITICAL/MAJOR/MINOR table, defaulting to INFO.
    """
    sev_key = str(severity).strip().lower() if severity is not None else ""
    base = _SEVERITY_BASE.get(sev_key, _DEFAULT_SEVERITY)
    cat_key = str(category).strip().lower() if category is not None else ""
    if cat_key == "security" and base == "CRITICAL":
        return "BLOCKER"
    return base


def _rule_id(finding: Any, category: Any) -> str:
    """Stable SonarQube ``ruleId``: the detector's fix_kind when routed, else the
    category. Mirrors ``sarif_export._rule_id`` so the same finding carries the
    same rule identity across both exporters."""
    fix_kind = _get(finding, "fix_kind", default="") or ""
    key = (str(fix_kind) or str(category) or "finding").strip()
    key = key.replace(" ", "-") or "finding"
    return f"{ENGINE_ID}/{key}"


def _start_line(finding: Any) -> int:
    """The 1-based start line, clamped to ``>= 1`` (SonarQube rejects line < 1).

    A missing or non-integer line (e.g. a project-level finding) becomes 1, the
    smallest line SonarQube accepts."""
    raw = _get(finding, "line", "startLine", default=1)
    try:
        line = int(raw)
    except (TypeError, ValueError):
        return 1
    return line if line >= 1 else 1


def _file_path(finding: Any) -> str:
    """The source path for the issue's primary location.

    ``ReviewFinding`` carries ``file``; an ``Issue`` (line-level, file-agnostic)
    has none, so the caller's path is read from ``file``/``filePath``/``path``
    and an empty string is used when truly unknown."""
    value = _get(finding, "file", "filePath", "path", default="")
    return str(value) if value is not None else ""


def to_sonar_issue(finding: Any) -> dict[str, Any]:
    """Convert one Apex finding to a SonarQube generic-import issue dict.

    Deterministic and total: every finding yields a complete issue with a valid
    ``severity``/``type`` and a ``startLine`` >= 1, regardless of which finding
    shape (``Issue``/``ReviewFinding``/dict) or how sparse it is.
    """
    category = _get(finding, "category")
    message = _get(finding, "message", default="")
    return {
        "engineId": ENGINE_ID,
        "ruleId": _rule_id(finding, category),
        "severity": _severity(category, _get(finding, "severity")),
        "type": _issue_type(category),
        "primaryLocation": {
            "message": str(message) if message is not None else "",
            "filePath": _file_path(finding),
            "textRange": {"startLine": _start_line(finding)},
        },
    }


def to_sonar_generic(findings: Iterable[Any]) -> dict[str, Any]:
    """Build the SonarQube generic-import report object from Apex findings.

    Returns ``{"issues": [...]}`` with the issues sorted by a stable key
    (filePath, startLine, ruleId, severity, type, message) so the report is
    byte-identical for the same input. An empty/exhausted iterable yields
    ``{"issues": []}``.
    """
    issues = [to_sonar_issue(f) for f in findings]
    issues.sort(key=_sort_key)
    return {"issues": issues}


def _sort_key(issue: dict[str, Any]) -> tuple[str, int, str, str, str, str]:
    """Total, deterministic ordering key for a built issue dict."""
    loc = issue["primaryLocation"]
    return (
        loc["filePath"],
        loc["textRange"]["startLine"],
        issue["ruleId"],
        issue["severity"],
        issue["type"],
        loc["message"],
    )


def to_sonar_generic_json(findings: Iterable[Any], *, indent: int = 2) -> str:
    """Serialize Apex findings as a SonarQube generic-import JSON string.

    The deterministic top-level entry point: keys are sorted and a trailing
    newline is appended, so the same findings always produce byte-identical
    output. Pass ``indent=None`` for compact one-line JSON.
    """
    report = to_sonar_generic(findings)
    return json.dumps(report, indent=indent, sort_keys=True) + "\n"
