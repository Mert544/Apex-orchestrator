"""Foreign-repo develop-readiness — what share of findings can Apex LAND?

The "develops-OTHER-projects" moat rests on honesty: before spending an apply on
a stranger's repo, Apex should say UP FRONT what fraction of what it detects it
can actually FIX, never overclaiming. A linter that flags 100 issues but can
auto-fix none is not a developer; a developer knows which of its findings carry a
landing transform and which are merely annotated for a human.

This module answers the sharp question — *on THIS repo, what share of detected
findings does Apex have a landing (auto-fixable) transform for?* — by crossing
the canonical detector's findings (:func:`app.engine.detectors.detect`, the same
single source of truth ``review``/``maintain``/the seeder use) against the
catalog of transforms and the risk-tier map (:mod:`app.execution.risk_tiers`):

  - **fixable_now** — a finding whose ``fix_kind`` routes to a transform that
    REWRITES the code AND whose action tier is auto-appliable (Tier 0/1, i.e.
    semantics-preserving or behaviour-adjacent-with-coverage). Apex can land it.
  - **flag_only** — a finding whose transform only ANNOTATES the call site with a
    ``# SECURITY``/marker comment (pickle, SQL, tempfile, weak-hash, os.popen,
    TLS-verify, Zip-Slip) or whose fix is contextual (net-timeout, debug-flag).
    Apex can point at it, honestly, but cannot rewrite it.
  - **unknown** — a finding the detector emits with NO ``fix_kind`` (exec,
    shell=True, hardcoded secret, a swallowed exception, dead code, a frozen-
    dataclass write, ...). Apex has no mapping; it claims nothing.

The partition is EXHAUSTIVE and disjoint: every detected finding lands in exactly
one bucket. The readiness score is the fixable share, optionally reliability-
weighted by the FLAT ``learned_reliability`` track record (an action that has
historically been rolled back/blocked on this project counts for less) — never
the recency-decayed variant, so the score stays a function of the input alone.

Everything here is READ-ONLY and byte-deterministic: it parses sources, never
writes; buckets are sorted and the per-file scan is capped; no clock, no random.
Best-effort like the rest of the engine — an unreadable file contributes nothing
rather than raising.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.execution.risk_tiers import tier_for

__all__ = [
    "classify_fix_kind",
    "develop_readiness",
    "render_develop_readiness_markdown",
]

# Hard cap on the number of source files scanned, so the profile is bounded on a
# huge foreign repo. Deterministic: ``iter_source_files`` returns a sorted list,
# so the same prefix is taken every run.
_MAX_FILES = 2000

# ---------------------------------------------------------------------------
# fix_kind -> (action_type, landability) — the routing table, grounded in the
# detector's emitted fix_kinds and the action bridge's routing.
#
# ``landability`` is "fix" when the transform REWRITES the pattern away (so the
# finding self-clears after applying) and "flag" when it only inserts a marker
# comment / the fix is contextual (the pattern persists). The action_type feeds
# the tier map so a non-auto-appliable rewrite (none exist today, but a future
# Tier-2 rewrite would) is demoted to flag-only honestly.
#
# A fix_kind not in this table, and the empty fix_kind "" the detector emits for
# a finding it can only describe, both fall through to "unknown".
# ---------------------------------------------------------------------------
_FIX_KIND_ROUTING: dict[str, tuple[str, str]] = {
    # --- Rewrites (the pattern is removed) -> fixable_now when the tier permits.
    "eval": ("harden_security", "fix"),
    "os.system": ("harden_security", "fix"),
    "yaml": ("harden_security", "fix"),
    "bare except": ("harden_security", "fix"),
    "base-exception": ("harden_security", "fix"),
    "subprocess-shell-literal": ("harden_security", "fix"),
    "hashlib-new-weak": ("harden_security", "fix"),
    "mutable-default": ("fix_mutable_defaults", "fix"),
    "none-comparison": ("modernize_comparisons", "fix"),
    "identity-literal": ("modernize_comparisons", "fix"),
    "open-encoding": ("modernize_comparisons", "fix"),
    "raise-from": ("modernize_comparisons", "fix"),
    "negated-comparison": ("modernize_comparisons", "fix"),
    "collection-literal": ("modernize_comparisons", "fix"),
    "fstring-no-placeholder": ("modernize_comparisons", "fix"),
    "docstring": ("add_docstring", "fix"),
    # --- Flag-only (a marker comment; the pattern persists) -> flag_only.
    # These mirror the bridge's _FLAG_MARKERS / annotation-flag set plus the
    # contextual-fix findings whose detector docstring says "flag-only".
    "pickle": ("harden_security", "flag"),
    "sql": ("harden_security", "flag"),
    "tempfile": ("harden_security", "flag"),
    "weak-hash": ("harden_security", "flag"),
    "os.popen": ("harden_security", "flag"),
    "tls-verify": ("harden_security", "flag"),
    "zip-slip": ("harden_security", "flag"),
    "net-timeout": ("harden_security", "flag"),
    "debug-flag": ("harden_security", "flag"),
}

# Tier 2 (design-level) is never auto-applied, so a fixable-classed rewrite whose
# action sits at Tier 2 is demoted to flag-only honesty. Tier 0/1 are landable
# (Tier 1 under the verify/coverage gate). Kept as a named threshold so the
# auto-appliable boundary is explicit and matches risk_tiers' contract.
_AUTO_APPLIABLE_MAX_TIER = 1


def classify_fix_kind(fix_kind: str) -> str:
    """Bucket a single detector ``fix_kind`` → ``fixable_now``/``flag_only``/``unknown``.

    A ``fix_kind`` with a rewriting transform whose action tier is auto-appliable
    (Tier <= 1) is ``fixable_now``; a flag/annotation-only transform is
    ``flag_only``; an unmapped or empty ``fix_kind`` (a finding Apex can only
    describe) is ``unknown``. Pure and total — every input maps to exactly one
    bucket.
    """
    route = _FIX_KIND_ROUTING.get(fix_kind)
    if route is None:
        return "unknown"
    action_type, landability = route
    if landability == "fix" and tier_for(action_type) <= _AUTO_APPLIABLE_MAX_TIER:
        return "fixable_now"
    return "flag_only"


def _iter_findings(root: str) -> list[tuple[str, Any]]:
    """Every ``(rel_path, Issue)`` the detector finds across the repo's Python
    sources, in deterministic order. Best-effort: an unreadable/binary file or a
    walk that fails contributes nothing rather than raising.

    READ-ONLY: opens each file for reading only; never writes or mutates.
    """
    try:
        from app.engine.detectors import detect
        from app.engine.skip_dirs import iter_source_files
    except Exception:
        return []
    out: list[tuple[str, Any]] = []
    try:
        files = list(iter_source_files(root))[:_MAX_FILES]
    except Exception:
        return []
    root_path = Path(root)
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            rel = path.relative_to(root_path).as_posix()
        except ValueError:
            rel = path.as_posix()
        try:
            for issue in detect(source):
                out.append((rel, issue))
        except Exception:
            continue
    return out


def _reliability_map(root: str) -> dict[str, float]:
    """The FLAT learned-reliability map (action_type -> [0,1] landing share) for
    this project, or ``{}`` when there is no track record / it can't be read.

    Deliberately the flat ``learned_reliability`` (a pure function of the recorded
    history), NOT the recency-decayed variant — the readiness score must depend on
    the repo's input alone, never on wall-clock age. Best-effort: any failure
    yields ``{}`` so the score falls back to an unweighted count.
    """
    try:
        from app.engine.proof_history import learned_reliability, load_proof_history
    except Exception:
        return {}
    try:
        history = load_proof_history(root)
    except Exception:
        return {}
    try:
        rel = learned_reliability(history)
    except Exception:
        return {}
    return {k: float(v) for k, v in rel.items() if isinstance(v, (int, float))}


def _weight_for(fix_kind: str, reliability: dict[str, float]) -> float:
    """The reliability weight of a finding's action (default 1.0).

    When no track record is available (or the action was never recorded), every
    finding weighs 1.0 — so the score reduces to a plain fixable share. With a
    record, a fixable finding's action is discounted by how often that action has
    actually LANDED on this project, so an action that keeps getting rolled back
    can't be over-claimed.
    """
    if not reliability:
        return 1.0
    route = _FIX_KIND_ROUTING.get(fix_kind)
    if route is None:
        return 1.0
    return reliability.get(route[0], 1.0)


def develop_readiness(profile: Any = None, root: str = "", *,
                      weight_by_reliability: bool = False) -> dict[str, Any]:
    """How much of THIS repo Apex can actually LAND — fixable-now vs flag vs unknown.

    Crosses every detected finding against the transform catalog / tier map and
    partitions it into three exhaustive, disjoint buckets. Returns a deterministic
    dict::

        {
          "score": float in [0,1],            # fixable share (the headline)
          "weighted": bool,                   # reliability-weighted?
          "total": int,                       # total findings
          "counts": {"fixable_now", "flag_only", "unknown"},
          "buckets": {<bucket>: [ {file,line,category,severity,fix_kind,message} ]},
        }

    ``root`` is the repo path; ``profile`` is accepted for signature symmetry with
    the other engine entry points and to let a caller pass an already-built profile
    whose ``root`` we can recover — the findings come from a fresh READ-ONLY scan
    either way. With ``weight_by_reliability=True`` the fixable share is weighted by
    the FLAT learned-reliability track record (opt-in, default off, so the headline
    score stays a plain count unless asked). Never raises.
    """
    target_root = root or _profile_root(profile)
    if not target_root:
        return _empty_result(weight_by_reliability)

    reliability = _reliability_map(target_root) if weight_by_reliability else {}
    buckets: dict[str, list[dict[str, Any]]] = {
        "fixable_now": [], "flag_only": [], "unknown": [],
    }
    fixable_weight = 0.0
    total_weight = 0.0

    for rel, issue in _iter_findings(target_root):
        fix_kind = getattr(issue, "fix_kind", "") or ""
        bucket = classify_fix_kind(fix_kind)
        buckets[bucket].append(_finding_record(rel, issue, fix_kind))
        weight = _weight_for(fix_kind, reliability)
        total_weight += weight
        if bucket == "fixable_now":
            fixable_weight += weight

    for items in buckets.values():
        items.sort(key=_finding_sort_key)

    total = sum(len(v) for v in buckets.values())
    score = (fixable_weight / total_weight) if total_weight > 0 else 0.0
    return {
        "score": round(score, 6),
        "weighted": bool(weight_by_reliability and reliability),
        "total": total,
        "counts": {k: len(v) for k, v in buckets.items()},
        "buckets": buckets,
    }


def _profile_root(profile: Any) -> str:
    """Best-effort recovery of a repo path from a profile object (or ``""``).

    Tries the common attribute names a ProjectProfile / engine profile carries,
    so a caller can pass just the profile. Read-only attribute access; never
    raises.
    """
    if profile is None:
        return ""
    for attr in ("root", "project_root", "path", "root_path"):
        value = getattr(profile, attr, None)
        if value:
            return str(value)
    return ""


def _finding_record(rel: str, issue: Any, fix_kind: str) -> dict[str, Any]:
    """A finding as a flat, JSON-friendly record (read-only projection of Issue)."""
    return {
        "file": rel,
        "line": int(getattr(issue, "line", 0) or 0),
        "category": str(getattr(issue, "category", "") or ""),
        "severity": str(getattr(issue, "severity", "") or ""),
        "fix_kind": fix_kind,
        "message": str(getattr(issue, "message", "") or ""),
    }


def _finding_sort_key(record: dict[str, Any]) -> tuple[str, int, str]:
    """Stable sort key for a finding record (file, line, fix_kind) — deterministic."""
    return (record["file"], record["line"], record["fix_kind"])


def _empty_result(weight_by_reliability: bool) -> dict[str, Any]:
    """The safe zero result for an empty / unresolvable repo (score 0.0)."""
    return {
        "score": 0.0,
        "weighted": False,
        "total": 0,
        "counts": {"fixable_now": 0, "flag_only": 0, "unknown": 0},
        "buckets": {"fixable_now": [], "flag_only": [], "unknown": []},
        "_unused_weight_flag": weight_by_reliability,
    }


def render_develop_readiness_markdown(result: dict[str, Any]) -> str:
    """A short, honest readiness section for a develop brief (additive narrative).

    Deterministic and self-contained — no second scan, just a render of the dict
    :func:`develop_readiness` returns. Leads with the headline landing share, then
    the three-bucket breakdown, so a reader sees up front what Apex can fix vs only
    flag vs has no mapping for.
    """
    total = int(result.get("total", 0) or 0)
    counts = result.get("counts", {}) or {}
    score = float(result.get("score", 0.0) or 0.0)
    pct = round(score * 100)
    weighted = " (reliability-weighted)" if result.get("weighted") else ""
    lines = ["## Develop-readiness — what Apex can land here", ""]
    if total == 0:
        lines.append("_No detectable findings — nothing to land or flag._")
        return "\n".join(lines)
    lines += [
        f"**Landing share: {pct}%**{weighted} — of {total} detected finding(s), "
        f"Apex has an auto-fixable transform for {counts.get('fixable_now', 0)}.",
        "",
        f"- **Fixable now:** {counts.get('fixable_now', 0)} — a rewrite lands the fix.",
        f"- **Flag only:** {counts.get('flag_only', 0)} — Apex annotates; a human decides.",
        f"- **Unknown:** {counts.get('unknown', 0)} — no mapping; not claimed.",
    ]
    return "\n".join(lines)
