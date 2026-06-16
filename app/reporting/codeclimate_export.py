"""CodeClimate / GitLab "Code Quality" export for Apex findings.

GitLab's "Code Quality" widget (and the broader CodeClimate ecosystem) consumes
a single, well-specified artifact: a JSON **array** of issue objects, each

    {
      "description": str,
      "check_name": str,
      "fingerprint": <stable hash>,
      "severity": "info" | "minor" | "major" | "critical" | "blocker",
      "location": {"path": str, "lines": {"begin": int}}
    }

Emitting Apex's deterministic findings in this shape makes Apex a drop-in
replacement for CodeClimate/`gl-code-quality-report.json` in a CI pipeline — the
same place reviewers already see quality deltas on a merge request, with no LLM,
no network, and no tokens.

This mirrors :mod:`app.engine.sarif_export`: it is a pure function of the
findings (an Apex ``ReviewFinding``/``Issue`` or any object/dict carrying the
same fields), so the same findings in always yield byte-identical JSON out. The
``fingerprint`` is a stable SHA-256 over the finding's identity, which is exactly
what GitLab uses to deduplicate an issue across pipeline runs — so a finding that
persists across two commits keeps the same fingerprint and is not re-reported.

Pure stdlib (``json``, ``hashlib``). No clock, no randomness, no network.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.reporting._finding_export_common import field as _field
from app.reporting._finding_export_common import path_of as _path_of
from app.reporting._finding_export_common import relative_path as _relative_path

# --- severity mapping --------------------------------------------------------
#
# Apex grades a finding on a 3-level scale (high | medium | low). CodeClimate /
# GitLab uses a 5-level scale (info | minor | major | critical | blocker). The
# mapping below is deterministic and intentional:
#
#   Apex "high"   -> "critical"  (a real risk in shipping code: eval, os.system,
#                                 a frozen-dataclass write, a mutable default)
#   Apex "medium" -> "major"     (a probable bug or weakness worth fixing)
#   Apex "low"    -> "minor"     (style/docs nits)
#
# "info" and "blocker" are the CodeClimate extremes; Apex never auto-assigns
# them (it has no "purely informational" tier, and "blocker" implies a release
# gate Apex deliberately leaves to the CI policy, not the detector). The mapping
# is total over Apex's scale; an unknown/missing severity falls back to "minor"
# so a malformed finding still produces a valid, conservative artifact.
_SEVERITY_MAP = {
    "high": "critical",
    "medium": "major",
    "low": "minor",
}
_DEFAULT_SEVERITY = "minor"

# The CodeClimate severities, in ascending order — surfaced so callers/tests can
# assert the mapping lands inside the spec'd vocabulary.
CODECLIMATE_SEVERITIES = ("info", "minor", "major", "critical", "blocker")


def _check_name(finding: Any) -> str:
    """A stable, human-meaningful rule id for the finding.

    Mirrors :func:`app.engine.sarif_export._rule_id`: prefer the detector's
    routing key (``fix_kind``) so the same rule reads identically across SARIF
    and CodeClimate, fall back to the finding's ``category``, then a constant.
    """
    key = _field(finding, "fix_kind", "") or _field(finding, "category", "") or "finding"
    return f"apex/{str(key).replace(' ', '-')}"


def _severity_of(finding: Any) -> str:
    """Map an Apex severity (high|medium|low) to the CodeClimate scale."""
    return _SEVERITY_MAP.get(str(_field(finding, "severity", "")), _DEFAULT_SEVERITY)


def _fingerprint(path: str, check_name: str, line: int, message: str) -> str:
    """A stable SHA-256 fingerprint of the finding's identity.

    GitLab dedups a code-quality issue across pipeline runs by this fingerprint,
    so it MUST be a pure function of the finding's identity (path, rule, line,
    message) and nothing else — no clock, no run id, no randomness. The four
    parts are joined with a NUL separator so they can never collide across a
    boundary (``a|b`` vs ``a`` + ``|b``).
    """
    payload = "\x00".join((path, check_name, str(line), message))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _to_issue(finding: Any, project_root: str) -> dict[str, Any]:
    """Map one Apex finding to a CodeClimate issue object."""
    path = _relative_path(_path_of(finding), project_root)
    check_name = _check_name(finding)
    line = int(_field(finding, "line", 1) or 1)
    message = str(_field(finding, "message", ""))
    return {
        "description": message,
        "check_name": check_name,
        "fingerprint": _fingerprint(path, check_name, line, message),
        "severity": _severity_of(finding),
        "location": {"path": path, "lines": {"begin": line}},
    }


def to_codeclimate_json(findings: Any, *, project_root: str = "") -> str:
    """Render Apex findings as a CodeClimate/GitLab Code Quality JSON array.

    ``findings`` is any iterable of Apex findings — a ``ReviewFinding``/``Issue``,
    or any object/dict carrying ``file``/``path``, ``line``, ``severity``,
    ``message`` and (optionally) ``fix_kind``/``category``. ``project_root``, when
    given, is stripped from each path so locations are repo-relative.

    Returns a JSON string (a 2-space-indented array). The output is fully
    deterministic: issues are sorted by ``(path, begin-line, check_name,
    fingerprint)`` so the same findings always serialize byte-identically, and
    each ``fingerprint`` is a stable SHA-256 of the finding's identity — exactly
    what GitLab uses to deduplicate an issue across pipeline runs.
    """
    issues = [_to_issue(f, project_root) for f in findings]
    issues.sort(key=lambda i: (
        i["location"]["path"],
        i["location"]["lines"]["begin"],
        i["check_name"],
        i["fingerprint"],
    ))
    return json.dumps(issues, indent=2, sort_keys=True)


# Public, descriptive alias. Some call sites read better spelling the source out
# ("...from findings"); the two names are the same function so the API stays
# minimal and there is exactly one implementation to reason about.
to_codeclimate_json_from_findings = to_codeclimate_json


__all__ = [
    "to_codeclimate_json",
    "to_codeclimate_json_from_findings",
    "CODECLIMATE_SEVERITIES",
]
