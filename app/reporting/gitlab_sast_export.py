"""GitLab SAST report export for Apex findings.

GitLab's "Security & Compliance" tab consumes a dedicated **SAST report**
artifact (distinct from the Code Quality widget that
:mod:`app.reporting.codeclimate_export` targets). The report is a single JSON
object conforming to the GitLab SAST schema (version 15.x):

    {
      "version": "15.0.6",
      "scan": {
        "scanner": {"id": "apex", "name": "Apex"},
        "type": "sast",
        "status": "success",
        ...
      },
      "vulnerabilities": [
        {
          "id": <stable hash>,
          "category": "sast",
          "name": str,
          "description": str,
          "severity": "Info"|"Low"|"Medium"|"High"|"Critical",
          "location": {"file": str, "start_line": int},
          "identifiers": [{"type": "apex_rule", "name": str, "value": str}]
        }
      ]
    }

Emitting Apex's deterministic findings in this shape makes Apex a drop-in SAST
scanner inside a GitLab pipeline — findings light up the merge request's
"Security" widget where reviewers already look, with no LLM, no network, and no
tokens.

This mirrors :mod:`app.engine.sarif_export` and
:mod:`app.reporting.codeclimate_export`: it is a pure function of the findings
(an Apex ``ReviewFinding`` / ``Issue`` or any object/dict carrying the same
fields), so the same findings in always yield byte-identical JSON out. The
``id`` is a stable SHA-256 over the finding's identity — exactly what GitLab
uses to track a vulnerability across pipeline runs.

Pure stdlib (``json``, ``hashlib``). No clock, no randomness, no network — the
report carries no per-run timestamp so two runs over the same findings produce
identical bytes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.reporting._finding_export_common import field as _field
from app.reporting._finding_export_common import path_of as _path_of
from app.reporting._finding_export_common import relative_path as _relative_path

# GitLab SAST report schema version this serializer targets (15.x family).
GITLAB_SAST_VERSION = "15.0.6"

# --- severity mapping --------------------------------------------------------
#
# Apex grades a finding on a 3-level scale (high | medium | low). GitLab's SAST
# schema uses a 5-level scale (Info | Low | Medium | High | Critical). Apex's
# three tiers map straight onto the middle three:
#
#   Apex "high"   -> "High"
#   Apex "medium" -> "Medium"
#   Apex "low"    -> "Low"
#
# "Info" and "Critical" are the GitLab extremes; Apex never auto-assigns them
# (it has no purely-informational tier, and "Critical" implies a release-gating
# judgement Apex leaves to CI policy, not the detector). The mapping is total
# over Apex's scale; an unknown/missing severity falls back to "Low" so a
# malformed finding still produces a valid, conservative artifact.
_SEVERITY_MAP = {
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}
_DEFAULT_SEVERITY = "Low"

# The GitLab SAST severities, in ascending order — surfaced so callers/tests can
# assert the mapping lands inside the spec'd vocabulary.
GITLAB_SAST_SEVERITIES = ("Info", "Low", "Medium", "High", "Critical")


def _rule(finding: Any) -> str:
    """A stable, human-meaningful rule id for the finding.

    Mirrors :func:`app.engine.sarif_export._rule_id`: prefer the detector's
    routing key (``fix_kind``) so the same rule reads identically across SARIF,
    CodeClimate, and the GitLab SAST report, fall back to the finding's
    ``category``, then a constant.
    """
    key = _field(finding, "fix_kind", "") or _field(finding, "category", "") or "finding"
    return f"apex/{str(key).replace(' ', '-')}"


def _severity_of(finding: Any) -> str:
    """Map an Apex severity (high|medium|low) to the GitLab SAST scale."""
    return _SEVERITY_MAP.get(str(_field(finding, "severity", "")), _DEFAULT_SEVERITY)


def _stable_id(path: str, rule: str, line: int, message: str) -> str:
    """A stable SHA-256 id for the vulnerability's identity.

    GitLab tracks a vulnerability across pipeline runs by this id, so it MUST be
    a pure function of the finding's identity (file, rule, line, message) and
    nothing else — no clock, no run id, no randomness. The four parts are joined
    with a NUL separator so they can never collide across a boundary (``a|b`` vs
    ``a`` + ``|b``).
    """
    payload = "\x00".join((path, rule, str(line), message))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _to_vulnerability(finding: Any, project_root: str) -> dict[str, Any]:
    """Map one Apex finding to a GitLab SAST vulnerability object."""
    path = _relative_path(_path_of(finding), project_root)
    rule = _rule(finding)
    line = int(_field(finding, "line", 1) or 1)
    message = str(_field(finding, "message", ""))
    category = str(_field(finding, "category", "") or "finding")
    return {
        "id": _stable_id(path, rule, line, message),
        "category": "sast",
        "name": f"{category}: {message}" if message else category,
        "description": message,
        "severity": _severity_of(finding),
        "location": {"file": path, "start_line": line},
        "identifiers": [{"type": "apex_rule", "name": rule, "value": rule}],
    }


def _report(findings: Any, project_root: str) -> dict[str, Any]:
    """Build the full GitLab SAST report object for ``findings``.

    The ``scan`` block carries no timestamp: the schema's ``start_time`` /
    ``end_time`` are optional, and omitting them keeps the report byte-stable
    across runs (the determinism invariant). Vulnerabilities are sorted by
    ``(file, start_line, rule, id)`` so the array is order-independent.
    """
    vulns = [_to_vulnerability(f, project_root) for f in findings]
    vulns.sort(key=lambda v: (
        v["location"]["file"],
        v["location"]["start_line"],
        v["identifiers"][0]["value"],
        v["id"],
    ))
    return {
        "version": GITLAB_SAST_VERSION,
        "scan": {
            "scanner": {"id": "apex", "name": "Apex"},
            "type": "sast",
            "status": "success",
        },
        "vulnerabilities": vulns,
    }


def to_gitlab_sast_json(findings: Any, *, project_root: str = "") -> str:
    """Render Apex findings as a GitLab SAST report JSON object.

    ``findings`` is any iterable of Apex findings — a ``ReviewFinding`` /
    ``Issue``, or any object/dict carrying ``file``/``path``, ``line``,
    ``severity``, ``message`` and (optionally) ``fix_kind``/``category``.
    ``project_root``, when given, is stripped from each path so locations are
    repo-relative.

    Returns a JSON string (a 2-space-indented object). The output is fully
    deterministic: vulnerabilities are sorted by ``(file, start_line, rule,
    id)`` so the same findings always serialize byte-identically, no per-run
    timestamp is emitted, and each ``id`` is a stable SHA-256 of the finding's
    identity — exactly what GitLab uses to track a vulnerability across runs.
    """
    return json.dumps(_report(findings, project_root), indent=2, sort_keys=True)


# Public, descriptive alias mirroring the CodeClimate exporter — the two names
# are the same function so the API stays minimal.
to_gitlab_sast_json_from_findings = to_gitlab_sast_json


__all__ = [
    "to_gitlab_sast_json",
    "to_gitlab_sast_json_from_findings",
    "GITLAB_SAST_SEVERITIES",
    "GITLAB_SAST_VERSION",
]
