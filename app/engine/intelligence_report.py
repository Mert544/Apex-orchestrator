"""Apex Intelligence — one deterministic markdown that makes the dormant research
organs VISIBLE to a user running Apex on their project.

Apex grows new research capabilities (anomaly discovery, self-validating
hypotheses, temporal hotspots, rule synthesis, self-assessment) that each answer
a sharp question but stay invisible unless something *surfaces* them. This module
is that surface: it CALLS each organ best-effort and aggregates their findings
into a single, clearly-headed report a user gets on a run. It reimplements none
of their logic — it only consumes their public functions, bounds the output, and
renders.

Five sections, each a heading plus a few bullets (or a short "nothing notable"
line when the organ has nothing to say):

  - **Anomalies** — modules that DEFY the codebase's pattern
    (``anomaly_discovery.find_anomalies``);
  - **Validated discoveries** — discovered patterns turned into falsifiable
    claims and tested project-wide
    (``hypothesis_validation.validate_discoveries``), grouped confirmed / weak /
    refuted;
  - **Emerging hotspots** — files whose change-rate is accelerating over git
    history (``temporal_discovery.emerging_hotspots``);
  - **Proposed fix-rules** — recurring rewritable micro-patterns Apex proposes a
    human turn into a transform (``rule_synthesis.propose_rules``,
    recommend-only);
  - **Self-assessment** — where Apex's OWN fixing is weakest and what it should
    improve (``self_assessment`` over ``proof_history.load_proof_history``).

Every organ is wrapped best-effort: a sub-capability that raises or returns
nothing yields its empty-state section and NEVER aborts the whole report. The
result is deterministic — every organ is itself sorted/capped and fed
deterministic input (a sorted, bounded set of the project's python sources for
rule synthesis), and this module adds no time/random. An empty project renders a
valid report whose sections are all in their empty state. Offline, stdlib + git,
no LLM.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.engine.anomaly_discovery import find_anomalies
from app.engine.hypothesis_validation import validate_discoveries
from app.engine.proof_history import load_proof_history
from app.engine.rule_synthesis import propose_rules
from app.engine.self_assessment import assess_weaknesses, self_curriculum
from app.engine.skip_dirs import is_test_or_fixture_path, iter_source_files
from app.engine.temporal_discovery import emerging_hotspots

# Per-section item cap so the report stays bounded regardless of project size.
_MAX_ITEMS = 5
# How many python sources to feed rule synthesis: bounded so the AST mine stays
# fast and the result is reproducible (sources are sorted before truncating).
_MAX_SOURCES = 80
# A single source larger than this is skipped — a vendored blob is not a pattern
# worth mining and reading it wastes the budget.
_MAX_SOURCE_BYTES = 200_000
# Empty-state line reused by every section that has nothing to report.
_NOTHING = "_Nothing notable._"

# The hypothesis verdicts, in the order they are rendered. ``candidate`` (a clean
# rule on a thin 2-4 module population) is surfaced too: dropping it would turn the
# over-claim suppression into a SILENT under-report — an honest low-support lead
# must be shown as "candidate", not hidden as "nothing notable".
_VERDICTS = ("confirmed", "candidate", "weak", "refuted")


def _safe(call: Callable[[], Any], default: Any) -> Any:
    """Run ``call`` best-effort, returning ``default`` if it raises.

    The single guard every organ is invoked through: a failing organ yields its
    empty section (the ``default``) instead of aborting the whole report. Pure
    aside from whatever ``call`` does.
    """
    try:
        return call()
    except Exception:
        return default


def _section(title: str, bullets: list[str]) -> list[str]:
    """A ``## title`` heading followed by its bullets, or the empty-state line.

    Centralises the heading + empty-state shape so every section renders
    identically and an organ with no findings still produces a valid section.
    """
    body = bullets if bullets else [_NOTHING]
    return [f"## {title}", "", *body, ""]


def gather_sources(root: str, max_sources: int = _MAX_SOURCES) -> dict[str, str]:
    """A bounded, sorted ``{relpath: source}`` map of the project's own python.

    Reuses the canonical ``iter_source_files`` walk (so worktrees / caches never
    leak in) and drops the project's tests/fixtures, keeping the mine focused on
    shipped code. Paths are relative-and-sorted before the ``max_sources`` cap so
    the selection is reproducible. Oversized or unreadable files are skipped —
    a read error tolerated per file, never raising. Deterministic for a tree.
    """
    if max_sources <= 0:
        return {}
    root_path = Path(root)
    sources: dict[str, str] = {}
    for path in iter_source_files(root_path):
        rel = path.relative_to(root_path)
        if is_test_or_fixture_path(rel):
            continue
        text = _read_source(path)
        if text is None:
            continue
        sources[rel.as_posix()] = text
        if len(sources) >= max_sources:
            break
    return sources


def _read_source(path: Path) -> str | None:
    """Read one source if it is within the size cap, else ``None``. Tolerant.

    Any OS error (missing, unreadable, decode failure) is swallowed so a single
    bad file never derails source gathering.
    """
    try:
        if path.stat().st_size > _MAX_SOURCE_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _anomaly_bullets(profile: Any) -> list[str]:
    """Bullets for the anomaly section, bounded and best-effort."""
    anomalies = _safe(lambda: find_anomalies(profile, top=_MAX_ITEMS), [])
    bullets: list[str] = []
    for row in anomalies[:_MAX_ITEMS]:
        bullets.append(
            f"`{row.get('module', '?')}` (deviation {row.get('deviation', 0)}): "
            f"{row.get('why', '')}".rstrip()
        )
    return bullets


def _verdict_bullet(result: dict) -> str:
    """One validated-discovery bullet, naming verdict, claim, and the evidence."""
    verdict = result.get("verdict", "?")
    claim = result.get("claim", "")
    confidence = result.get("confidence", 0)
    support = result.get("support", 0)
    line = f"**{verdict}** ({confidence}, support {support}): {claim}"
    evidence = result.get("evidence") or []
    if verdict != "confirmed" and evidence:
        joined = ", ".join(f"`{m}`" for m in evidence[:3])
        line += f" — counter-examples: {joined}"
    return line


def _discovery_bullets(profile: Any) -> list[str]:
    """Bullets for validated discoveries, grouped confirmed -> weak -> refuted.

    ``validate_discoveries`` already ranks confirmed-first; we re-group by verdict
    so the section reads as the three buckets, each bounded.
    """
    results = _safe(lambda: validate_discoveries(profile, top=_MAX_ITEMS * 2), [])
    bullets: list[str] = []
    for verdict in _VERDICTS:
        for result in results:
            if result.get("verdict") == verdict and len(bullets) < _MAX_ITEMS:
                bullets.append(_verdict_bullet(result))
    return bullets


def _hotspot_bullets(root: str) -> list[str]:
    """Bullets for emerging (accelerating) hotspots from git history, bounded."""
    hotspots = _safe(lambda: emerging_hotspots(root), [])
    bullets: list[str] = []
    for row in hotspots[:_MAX_ITEMS]:
        bullets.append(
            f"`{row.get('module', '?')}` accelerating "
            f"(recent {row.get('recent', 0)} vs older {row.get('older', 0)})"
        )
    return bullets


def _rule_bullets(sources: dict[str, str]) -> list[str]:
    """Bullets for proposed fix-rules (recommend-only), bounded.

    The descriptors already carry a ``safety_note``; we surface the shape, its
    support, and the suggested transform name a human could implement.
    """
    rules = _safe(lambda: propose_rules(sources, top=_MAX_ITEMS), [])
    bullets: list[str] = []
    for rule in rules[:_MAX_ITEMS]:
        bullets.append(
            f"`{rule.get('suggested_name', '?')}` — shape "
            f"`{rule.get('shape', '?')}` recurs at {rule.get('support', 0)} sites "
            "(recommend-only; verify behaviour-preservation)"
        )
    return bullets


def _self_bullets(history: list[dict]) -> list[str]:
    """Bullets for self-assessment: weakest fix families + curriculum directions.

    Combines the ranked weaknesses with the distilled "Apex should get better at
    X" curriculum lines, all bounded.
    """
    weaknesses = _safe(lambda: assess_weaknesses(history), [])
    bullets: list[str] = []
    for item in weaknesses[:_MAX_ITEMS]:
        bullets.append(
            f"`{item.get('action', '?')}` — {item.get('verdict', '')} "
            f"(reliability {item.get('reliability', 0)} over "
            f"{item.get('attempts', 0)} attempts)"
        )
    for line in _safe(lambda: self_curriculum(history, top=_MAX_ITEMS), []):
        if len(bullets) < _MAX_ITEMS * 2:
            bullets.append(line)
    return bullets


def build_intelligence_report(profile: Any, root: str) -> str:
    """Aggregate Apex's research organs into one deterministic markdown report.

    Calls each organ best-effort (a raising/empty organ yields only its
    empty-state section, never aborting), bounds every section, and renders a
    single document with five clearly-headed sections: Anomalies, Validated
    discoveries, Emerging hotspots, Proposed fix-rules, and Self-assessment.

    Deterministic: each organ is sorted/capped, the rule-synthesis input is a
    sorted, bounded source set, and nothing here uses time/random — same
    ``(profile, root)`` -> byte-identical markdown. An empty project renders a
    valid report whose sections are all in their empty state; never raises.
    """
    sources = _safe(lambda: gather_sources(root), {})
    history = _safe(lambda: load_proof_history(root), [])

    lines: list[str] = ["# Apex Intelligence", ""]
    lines += _section("Anomalies", _anomaly_bullets(profile))
    lines += _section("Validated discoveries", _discovery_bullets(profile))
    lines += _section("Emerging hotspots", _hotspot_bullets(root))
    lines += _section("Proposed fix-rules", _rule_bullets(sources))
    lines += _section("Self-assessment", _self_bullets(history))
    return "\n".join(lines)
