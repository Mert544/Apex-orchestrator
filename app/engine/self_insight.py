"""Self-insight — Apex points its NEWEST organs at a codebase (incl. ITSELF).

The discovery organs each read one slice of a project: ``find_anomalies`` ranks
the modules that DEFY the codebase's patterns, ``propose_rules`` mines recurring
syntactic micro-patterns into candidate rewrite-rule descriptors,
``assess_weaknesses`` grades where Apex's OWN fixing fails most, and
``self_curriculum`` distils that into hardening directions. Individually each is
a lens; this module trains all four on a single ``root`` at once and folds their
verdicts into one structured reading — what Apex, with its newest tools, observes
about the codebase at ``root``. When ``root`` is the Apex tree itself, that
reading is Apex inspecting Apex: the organism turning its instruments on its own
body.

Three deterministic moves, no LLM, stdlib + the consumed organs only:

  - **profile** the root best-effort (a light profile is enough — the anomaly
    organ reads only the signal-tag rows), tolerating an unprofilable root;
  - **gather** a bounded, sorted set of the root's python sources (the
    ``{path: source}`` ``propose_rules`` needs), tolerating per-file read errors;
  - **run** every organ behind a best-effort guard so a failing organ yields an
    empty section instead of aborting the whole insight.

Everything is **pure-output and deterministic**: each section is sorted and
capped, no time/random is read, and the same ``root`` (same files on disk) yields
a byte-identical insight and markdown. An empty or unprofilable root yields a
valid empty insight — never raises.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.engine.anomaly_discovery import find_anomalies
from app.engine.proof_history import load_proof_history
from app.engine.rule_synthesis import propose_rules
from app.engine.self_assessment import assess_weaknesses, self_curriculum
from app.engine.skip_dirs import iter_source_files

# Per-section caps so the insight stays bounded regardless of project size.
_MAX_ANOMALIES = 5
_MAX_RULES = 3
_MAX_WEAKNESSES = 5
_MAX_CURRICULUM = 3
# Cap on python sources fed to rule synthesis, so the mine stays bounded and the
# gathered set is reproducible (the sorted source order is truncated, not random).
_MAX_SOURCES = 200


def _safe(fn: Callable[[], Any], fallback: Any) -> Any:
    """Run ``fn`` and return its result, or ``fallback`` if it raises.

    The best-effort guard every organ runs behind: a single misbehaving organ
    (or an odd profile it can't read) degrades to an empty section instead of
    aborting the whole insight. Deterministic — no exception is logged or timed.
    """
    try:
        return fn()
    except Exception:
        return fallback


def _profile(root: str | Path) -> Any:
    """Best-effort light profile of ``root``, or ``None`` if it can't be built.

    A light profile is sufficient: the anomaly organ reads only the signal-tag
    rows the grade-relevant scans populate. An unimportable profiler or an
    unprofilable root degrades to ``None`` so callers short-circuit cleanly.
    """
    def build() -> Any:
        from app.tools.project_profile import ProjectProfiler

        return ProjectProfiler(root).profile(light=True)

    return _safe(build, None)


def gather_sources(root: str | Path) -> dict[str, str]:
    """A bounded, sorted ``{relative-path: source}`` map of ``root``'s python.

    Reuses ``iter_source_files`` (already sorted, skip-dir aware) so the order is
    deterministic, reads each file tolerating per-file errors (skipping the
    unreadable), keys by the root-relative POSIX path for stable labels, and caps
    at ``_MAX_SOURCES`` so the mine is bounded. Empty/unreadable root → ``{}``.
    """
    root_path = Path(root)
    sources: dict[str, str] = {}
    for path in iter_source_files(root_path):
        if len(sources) >= _MAX_SOURCES:
            break
        try:
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(root_path).as_posix()
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        sources[rel] = text
    return sources


def self_insight(root: str | Path) -> dict[str, list[dict[str, Any]] | list[str]]:
    """What Apex's newest organs observe about the codebase at ``root``.

    Profiles ``root`` (best-effort, light), gathers its python sources, then runs
    each organ behind a best-effort guard, returning
    ``{"anomalies", "proposed_rules", "weaknesses", "curriculum"}``. Every section
    is independently sorted and capped by its organ, so a failing organ yields an
    empty section without aborting the rest. Deterministic: same files on disk →
    byte-identical insight. Empty/unprofilable root → all-empty insight; never
    raises.
    """
    profile = _profile(root)
    sources = _safe(lambda: gather_sources(root), {})
    history = _safe(lambda: load_proof_history(root), [])
    anomalies = _safe(lambda: find_anomalies(profile, top=_MAX_ANOMALIES), [])
    rules = _safe(lambda: propose_rules(sources, top=_MAX_RULES), [])
    weaknesses = _safe(lambda: assess_weaknesses(history), [])[:_MAX_WEAKNESSES]
    curriculum = _safe(lambda: self_curriculum(history, top=_MAX_CURRICULUM), [])
    return {
        "anomalies": anomalies,
        "proposed_rules": rules,
        "weaknesses": weaknesses,
        "curriculum": curriculum,
    }


def _anomaly_lines(anomalies: list[dict[str, Any]]) -> list[str]:
    """One bullet per anomaly: the off-pattern module and why it deviates."""
    lines: list[str] = []
    for item in anomalies:
        module = item.get("module", "?")
        deviation = item.get("deviation", 0.0)
        why = item.get("why", "")
        lines.append(f"- `{module}` (deviation {deviation:g}) — {why}")
    return lines


def _rule_lines(rules: list[dict[str, Any]]) -> list[str]:
    """One bullet per proposed rule: its suggested name, support, and shape."""
    lines: list[str] = []
    for rule in rules:
        name = rule.get("suggested_name", "?")
        support = rule.get("support", 0)
        shape = rule.get("shape", "")
        lines.append(f"- `{name}` — {support} sites of shape `{shape}`")
    return lines


def _weakness_lines(weaknesses: list[dict[str, Any]]) -> list[str]:
    """One bullet per weak action family: its verdict and reliability."""
    lines: list[str] = []
    for item in weaknesses:
        action = item.get("action", "?")
        reliability = item.get("reliability", 0.0)
        verdict = item.get("verdict", "")
        lines.append(f"- `{action}` (reliability {reliability:g}) — {verdict}")
    return lines


def _section(heading: str, lines: list[str], empty: str) -> list[str]:
    """A markdown section: a heading, then the bullets or a single empty-state line."""
    body = lines if lines else [empty]
    return [f"## {heading}", *body, ""]


def render_self_insight_markdown(root: str | Path) -> str:
    """A deterministic markdown summary of ``self_insight(root)``.

    A heading per organ, bounded bullets beneath each, and an explicit empty-state
    line when an organ found nothing (or failed). Same ``root`` (same files) →
    byte-identical markdown; never raises.
    """
    insight = self_insight(root)
    curriculum = insight["curriculum"]
    curriculum_lines = [f"- {line}" for line in curriculum]
    out: list[str] = ["# Apex self-insight", ""]
    out += _section(
        "Anomalies — modules that defy the codebase's patterns",
        _anomaly_lines(insight["anomalies"]),  # type: ignore[arg-type]
        "- No off-pattern modules surfaced.",
    )
    out += _section(
        "Proposed rules — recurring micro-patterns worth a transform",
        _rule_lines(insight["proposed_rules"]),  # type: ignore[arg-type]
        "- No recurring rewritable pattern surfaced.",
    )
    out += _section(
        "Weaknesses — where Apex's own fixing fails most",
        _weakness_lines(insight["weaknesses"]),  # type: ignore[arg-type]
        "- No proof history to grade fixing from.",
    )
    out += _section(
        "Curriculum — what Apex should harden next",
        curriculum_lines,
        "- No hardening directions yet.",
    )
    return "\n".join(out).rstrip("\n") + "\n"
