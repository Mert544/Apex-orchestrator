"""Discovery synthesis — FUSE Apex's three discovery engines into one ranked list.

Apex ships three independent DISCOVERY engines, each surfacing a different slice
of latent structure, but their outputs are never fused or ranked against each
other:

  - ``anomaly_discovery`` — modules whose signal fingerprint DEFIES the
    codebase's "normal" (``find_anomalies``);
  - ``temporal_discovery`` — files/pairs whose change-rate or coupling is
    ACCELERATING over git history (``emerging_hotspots`` / ``spreading_pairs``);
  - ``rule_synthesis`` — recurring, mechanically-rewritable micro-patterns mined
    from the source ASTs (``propose_rules``).

This module is the deterministic SYNTHESIS layer on top. It calls all three,
NORMALISES every finding into one uniform "discovery lead" shape, DE-DUPLICATES
leads pointing at the same ``(subject, kind)``, and — when two engines
corroborate the same SUBJECT — BOOSTS that subject's leads so cross-engine
agreement floats to the top. It produces a ranked, read-only artifact only:

  - it NEVER seeds an idea, never mutates planning state, never writes anything;
  - an earlier attempt to auto-seed these engines displaced budgeted synthesis
    and was reverted, so this layer is deliberately a pure *read*.

Determinism / totality (matching the sibling discovery engines):

  - no time / random / network / hash-order dependence; every collection is
    sorted and every float rounded to a fixed precision;
  - the profile and the source map are built deterministically (sorted ``.py``
    files under ``app/``) when not supplied;
  - ``except Exception`` only at the engine / I-O edges, so a non-git or empty
    root yields ``[]`` and NOTHING ever raises.

Pure, stdlib + the three engines, offline, no LLM.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.engine import anomaly_discovery, rule_synthesis, temporal_discovery
from app.engine.skip_dirs import is_skipped

__all__ = [
    "ANOMALY_SOURCE",
    "TEMPORAL_SOURCE",
    "RULE_SOURCE",
    "CORROBORATION_BOOST",
    "ROUND_NDIGITS",
    "synthesize_discoveries",
    "discovery_report",
    "render_discoveries_markdown",
]

# Engine names recorded on each lead's ``source`` — stable identifiers a
# consumer can group by, independent of the kind.
ANOMALY_SOURCE = "anomaly_discovery"
TEMPORAL_SOURCE = "temporal_discovery"
RULE_SOURCE = "rule_synthesis"

# Lead ``kind`` tags.
KIND_ANOMALY = "anomaly"
KIND_EMERGING_HOTSPOT = "emerging-hotspot"
KIND_SPREADING_PAIR = "spreading-pair"
KIND_CANDIDATE_RULE = "candidate-rule"

# When a SUBJECT is named by more than one engine, every lead on that subject is
# multiplied by this factor PER extra corroborating engine, then clamped to
# [0, 1]. One engine → x1 (no boost); two engines → x1.25; three → x1.5. The
# boost rewards cross-engine agreement without ever letting a score leave its
# bound. Applied AFTER per-lead scores are computed and BEFORE the final sort.
CORROBORATION_BOOST = 0.25

# Fixed float precision so the ranked output is byte-stable across runs.
ROUND_NDIGITS = 4

# How many leads ``discovery_report`` keeps in its ``top`` slice / markdown.
_TOP_N = 10

# The largest emerging-hotspot acceleration we expect to normalise against; a
# fixed denominator keeps the hotspot score bounded in (0, 1] and deterministic
# (the raw ``recent - older`` delta has no intrinsic ceiling).
_HOTSPOT_SCALE = 10.0
_PAIR_SCALE = 10.0
# Rule support normaliser: support of this many sites maps to a near-1 score.
_RULE_SCALE = 12.0


def _clamp(value: float) -> float:
    """Clamp a float into ``[0, 1]`` (scores are bounded by contract)."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _round(value: float) -> float:
    """Round to the fixed output precision."""
    return round(float(value), ROUND_NDIGITS)


def _pair_subject(a: str, b: str) -> str:
    """Canonical ``a | b`` subject for a co-change pair (inputs already sorted)."""
    lo, hi = sorted((a, b))
    return f"{lo} | {hi}"


def _build_profile(root: str) -> Any:
    """Build the ``ProjectProfile`` the anomaly engine consumes — best-effort.

    Any failure (unreadable tree, scan error) degrades to ``None`` so the
    synthesis still runs over whatever the other engines produce.
    """
    try:
        from app.tools.project_profile import ProjectProfiler

        return ProjectProfiler(root).profile()
    except Exception:
        return None


def _gather_sources(root: str) -> dict[str, str]:
    """Map relpath -> source for the project's ``app/`` ``.py`` files, sorted.

    Deterministic (paths sorted, canonical skip set applied) and best-effort:
    an unreadable file is dropped, a missing ``app/`` dir yields ``{}``, and
    nothing raises.
    """
    sources: dict[str, str] = {}
    try:
        base = Path(root)
        app_dir = base / "app"
        if not app_dir.is_dir():
            return {}
        for path in sorted(app_dir.rglob("*.py")):
            try:
                rel = path.relative_to(base).as_posix()
            except ValueError:
                continue
            if is_skipped(rel):
                continue
            try:
                sources[rel] = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
    except Exception:
        return sources
    return sources


def _anomaly_leads(profile: Any) -> list[dict[str, Any]]:
    """Normalise ``find_anomalies`` records into uniform leads — best-effort."""
    if profile is None:
        return []
    try:
        anomalies = anomaly_discovery.find_anomalies(profile)
    except Exception:
        return []
    leads: list[dict[str, Any]] = []
    for a in anomalies:
        module = str(a.get("module", ""))
        if not module:
            continue
        leads.append({
            "kind": KIND_ANOMALY,
            "subject": module,
            "score": _clamp(float(a.get("deviation", 0.0))),
            "source": ANOMALY_SOURCE,
            "evidence": str(a.get("why", "off-pattern fingerprint.")),
        })
    return leads


def _hotspot_leads(root: str) -> list[dict[str, Any]]:
    """Normalise ``emerging_hotspots`` rows into uniform leads — best-effort."""
    try:
        hotspots = temporal_discovery.emerging_hotspots(root)
    except Exception:
        return []
    leads: list[dict[str, Any]] = []
    for h in hotspots:
        module = str(h.get("module", ""))
        if not module:
            continue
        recent = int(h.get("recent", 0))
        older = int(h.get("older", 0))
        score = _clamp((recent - older) / _HOTSPOT_SCALE)
        leads.append({
            "kind": KIND_EMERGING_HOTSPOT,
            "subject": module,
            "score": score,
            "source": TEMPORAL_SOURCE,
            "evidence": f"change-rate accelerating ({recent} recent vs {older} older).",
        })
    return leads


def _pair_leads(root: str) -> list[dict[str, Any]]:
    """Normalise ``spreading_pairs`` rows into uniform leads — best-effort."""
    try:
        pairs = temporal_discovery.spreading_pairs(root)
    except Exception:
        return []
    leads: list[dict[str, Any]] = []
    for p in pairs:
        a, b = str(p.get("a", "")), str(p.get("b", ""))
        if not a or not b:
            continue
        recent = int(p.get("recent", 0))
        older = int(p.get("older", 0))
        cochanges = int(p.get("cochanges", 0))
        score = _clamp((recent - older) / _PAIR_SCALE)
        leads.append({
            "kind": KIND_SPREADING_PAIR,
            "subject": _pair_subject(a, b),
            "score": score,
            "source": TEMPORAL_SOURCE,
            "evidence": f"coupling tightening ({recent} recent vs {older} older "
                        f"co-changes, {cochanges} total).",
        })
    return leads


def _rule_leads(sources: dict[str, str]) -> list[dict[str, Any]]:
    """Normalise ``propose_rules`` descriptors into uniform leads — best-effort."""
    if not sources:
        return []
    try:
        proposals = rule_synthesis.propose_rules(sources)
    except Exception:
        return []
    leads: list[dict[str, Any]] = []
    for r in proposals:
        shape = str(r.get("shape", ""))
        if not shape:
            continue
        support = int(r.get("support", 0))
        score = _clamp(support / _RULE_SCALE)
        leads.append({
            "kind": KIND_CANDIDATE_RULE,
            "subject": shape,
            "score": score,
            "source": RULE_SOURCE,
            "evidence": f"structural shape recurs across {support} sites "
                        "(recommend-only).",
        })
    return leads


def _dedup(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse leads sharing ``(subject, kind)``, keeping the strongest.

    Two engines never emit the SAME kind, so a duplicate is always one engine
    re-reporting the same subject+kind; we keep the highest-scoring record (ties
    broken by ``source`` then ``evidence`` for a stable winner). Order within the
    result is irrelevant — the caller sorts.
    """
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for lead in leads:
        key = (lead["subject"], lead["kind"])
        current = best.get(key)
        if current is None:
            best[key] = lead
            continue
        challenger = (lead["score"], lead["source"], lead["evidence"])
        incumbent = (current["score"], current["source"], current["evidence"])
        if challenger > incumbent:
            best[key] = lead
    return list(best.values())


def _subject_engine_count(leads: list[dict[str, Any]]) -> dict[str, int]:
    """How many DISTINCT engines name each subject (the corroboration count)."""
    engines: dict[str, set[str]] = {}
    for lead in leads:
        engines.setdefault(lead["subject"], set()).add(lead["source"])
    return {subject: len(srcs) for subject, srcs in engines.items()}


def _apply_corroboration(leads: list[dict[str, Any]],
                         engine_count: dict[str, int]) -> None:
    """Boost (in place) every lead whose subject >1 engine corroborates.

    A subject named by ``n`` distinct engines multiplies each of its leads'
    scores by ``1 + CORROBORATION_BOOST * (n - 1)``, clamped to ``[0, 1]``. One
    engine → unchanged. The corroboration count is recorded on each lead.
    """
    for lead in leads:
        n = engine_count.get(lead["subject"], 1)
        factor = 1.0 + CORROBORATION_BOOST * (n - 1)
        lead["score"] = _round(_clamp(lead["score"] * factor))
        lead["corroborated_by"] = n


def _sort_key(lead: dict[str, Any]) -> tuple[float, str, str]:
    """Deterministic order: highest score, then kind, then subject."""
    return (-lead["score"], lead["kind"], lead["subject"])


def synthesize_discoveries(root: str, profile: Any = None) -> list[dict[str, Any]]:
    """Fuse the three discovery engines into one ranked list of discovery leads.

    Calls ``find_anomalies`` (over ``profile``, built from ``root`` when not
    supplied), ``emerging_hotspots`` / ``spreading_pairs`` (over the git history
    at ``root``), and ``propose_rules`` (over the ``app/`` source map). Every
    finding is normalised into a uniform lead::

        {"kind": str, "subject": str, "score": float, "source": str,
         "evidence": str, "corroborated_by": int}

    ``score`` is bounded in ``[0, 1]`` and rounded to ``ROUND_NDIGITS``. Leads
    sharing a ``(subject, kind)`` are de-duplicated (strongest kept). When >1
    distinct engine names the SAME subject, every lead on that subject is boosted
    by ``1 + CORROBORATION_BOOST * (engines - 1)`` (clamped), so cross-engine
    agreement ranks higher. The result is sorted by ``(-score, kind, subject)``.

    Pure and total: a non-git / empty / unreadable root yields ``[]`` and never
    raises; identical for a given repo state.
    """
    if profile is None:
        profile = _build_profile(root)
    sources = _gather_sources(root)

    leads: list[dict[str, Any]] = []
    leads.extend(_anomaly_leads(profile))
    leads.extend(_hotspot_leads(root))
    leads.extend(_pair_leads(root))
    leads.extend(_rule_leads(sources))

    leads = _dedup(leads)
    # Corroboration counts distinct ENGINES per subject over the de-duplicated
    # set (so a single engine re-reporting a subject under two kinds is not
    # mistaken for cross-engine agreement).
    engine_count = _subject_engine_count(leads)
    _apply_corroboration(leads, engine_count)

    leads.sort(key=_sort_key)
    return leads


def discovery_report(root: str) -> dict[str, Any]:
    """Deterministic summary of the fused discovery leads at ``root``.

    Returns::

        {
          "total": int,
          "corroborated": int,        # leads whose subject >1 engine named
          "by_source": {source: count, ...},   # sorted by source
          "by_kind": {kind: count, ...},        # sorted by kind
          "top": [lead, ...],         # the top _TOP_N leads, already ranked
        }

    Pure and total: an empty discovery set yields zero counts and ``[]`` top,
    never raises.
    """
    leads = synthesize_discoveries(root)
    by_source: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    corroborated = 0
    for lead in leads:
        by_source[lead["source"]] = by_source.get(lead["source"], 0) + 1
        by_kind[lead["kind"]] = by_kind.get(lead["kind"], 0) + 1
        if lead.get("corroborated_by", 1) > 1:
            corroborated += 1
    return {
        "total": len(leads),
        "corroborated": corroborated,
        "by_source": dict(sorted(by_source.items())),
        "by_kind": dict(sorted(by_kind.items())),
        "top": leads[:_TOP_N],
    }


def render_discoveries_markdown(root: str) -> str:
    """Pure markdown rendering over ``discovery_report`` — no clock, no I/O here."""
    report = discovery_report(root)
    lines = ["# Discovery synthesis — fused, ranked discovery leads", ""]
    lines.append(
        f"_{report['total']} lead(s) · {report['corroborated']} corroborated "
        "by >1 engine · deterministic · read-only._"
    )
    lines.append("")

    lines.append("## By source")
    if report["by_source"]:
        for source, count in report["by_source"].items():
            lines.append(f"- `{source}`: {count}")
    else:
        lines.append("- _none_")
    lines.append("")

    lines.append("## By kind")
    if report["by_kind"]:
        for kind, count in report["by_kind"].items():
            lines.append(f"- `{kind}`: {count}")
    else:
        lines.append("- _none_")
    lines.append("")

    lines.append(f"## Top {_TOP_N} leads")
    if report["top"]:
        for lead in report["top"]:
            flag = " ✦" if lead.get("corroborated_by", 1) > 1 else ""
            lines.append(
                f"- [{lead['score']:.4f}] `{lead['kind']}` **{lead['subject']}** "
                f"({lead['source']}){flag} — {lead['evidence']}"
            )
    else:
        lines.append("- _no discovery leads found_")
    lines.append("")

    return "\n".join(lines)
