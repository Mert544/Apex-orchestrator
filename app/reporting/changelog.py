"""Release notes from evidence — most changelogs are written from memory.

`apex changelog` writes one from artifacts instead: what actually shipped
(commit subjects since the last tag), what was *verifiably* fixed (the
proof-of-fix record, with shields and verification strength), which planned
work landed (roadmap ideas that no longer surface, signal-narrated), and
where the project's health stands (the grade). Every section renders only
when its artifact exists — the notes never claim more than the evidence
holds. Deterministic for a given repo state; zero tokens.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

_COMMIT_CAP = 20


def _git(root: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True,
                             text=True, timeout=15)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _commits_section(root: Path) -> list[str]:
    last_tag = _git(root, "describe", "--tags", "--abbrev=0")
    span = f"{last_tag}..HEAD" if last_tag else "HEAD"
    subjects = [s for s in _git(root, "log", span, "--format=%s",
                                "-n", str(_COMMIT_CAP + 1)).splitlines() if s]
    if not subjects:
        return []
    title = (f"## Changes since `{last_tag}`" if last_tag
             else "## Changes (no release tag yet — full recent history)")
    lines = [title, ""]
    lines += [f"- {s}" for s in subjects[:_COMMIT_CAP]]
    if len(subjects) > _COMMIT_CAP:
        lines.append(f"- … and more ({_COMMIT_CAP} shown)")
    lines.append("")
    return lines


def _fixes_section(root: Path) -> list[str]:
    path = root / ".apex" / "proof-of-fix.json"
    if not path.exists():
        return []
    try:
        proof = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    applied = [f for f in proof.get("fixes", []) if f.get("outcome") == "applied"]
    if not applied:
        return []
    lines = ["## Verified fixes (from the proof-of-fix record)", ""]
    strength_word = {"function": "tests name the changed function",
                     "module": "suite covers the module",
                     "test-change": "test-only change"}
    for f in applied[:12]:
        finding = f.get("finding") or {}
        extra = []
        level = ((f.get("verification") or {}).get("strength") or {}).get("level", "")
        if level in strength_word:
            extra.append(strength_word[level])
        if f.get("shield_test"):
            extra.append(f"shielded by `{f['shield_test']}`")
        suffix = f" — {'; '.join(extra)}" if extra else ""
        lines.append(f"- **{finding.get('action', '?')}** on "
                     f"`{finding.get('target', '?')}`{suffix}")
    lines.append("")
    return lines


def _resolved_section(root: Path) -> list[str]:
    """Planned work that LANDED: roadmap ideas that no longer surface."""
    try:
        from app.engine.idea_permutation import IdeaPermutationEngine
        from app.engine.idea_roadmap import RoadmapSynthesizer
        from app.engine.roadmap_history import diff_roadmaps, load_snapshot

        snapshot = load_snapshot(root / ".apex" / "roadmap-snapshot.json")
        if not snapshot:
            return []
        report = IdeaPermutationEngine(
            {"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4},
            project_root=str(root)).run()
        diff = diff_roadmaps(snapshot, RoadmapSynthesizer().build(report))
    except Exception:
        return []
    if not diff.dropped:
        return []
    lines = ["## Planned work that landed (no longer surfaces on the roadmap)", ""]
    for c in diff.dropped[:8]:
        suffix = f" — its `{c.signal}` signal no longer fires" if c.signal else ""
        lines.append(f"- {c.title}{suffix}")
    lines.append("")
    return lines


def _health_section(root: Path) -> list[str]:
    try:
        from app.engine.health_score import grade

        h = grade(root)
    except Exception:
        return []
    worst = max(h.components, key=lambda c: c.points_lost, default=None)
    note = (f" (largest cost: {worst.name} −{worst.points_lost})"
            if worst and worst.points_lost else "")
    return [f"## Health: **{h.letter} ({h.score}/100)**{note}", ""]


def _coordinator_section(root: Path) -> list[str]:
    """A structural watch-item: the project's heaviest coordinator module.

    The profiler names high-fan-OUT "god-modules" (``coordinator_modules`` — each
    a ``{module, fan_out, imports}`` dict, already sorted ``(-fan_out, module)``):
    modules that import many internal siblings and so are decoupling candidates.
    The changelog surfaces only the single widest-fan-out one as a forward-looking
    watch-item, so the health read-out points at where to refactor next, not just
    where the grade stands. Gated: a repo with no god-module yields [] and the
    notes render byte-identically. Deterministic — the list is already ordered by
    a stable key, so the top entry never wobbles for a given repo state.
    """
    try:
        from app.tools.project_profile import ProjectProfiler

        coordinators = (ProjectProfiler(str(root)).profile().coordinator_modules
                        or [])
    except Exception:
        return []
    top = next((c for c in coordinators
                if isinstance(c, dict) and c.get("module")), None)
    if top is None:
        return []
    imports = [m for m in (top.get("imports") or []) if isinstance(m, str)][:3]
    wires = (f" — wires {', '.join(f'`{m}`' for m in imports)}"
             if imports else "")
    return [
        "## Decoupling watch-item (heaviest coordinator module)", "",
        f"- `{top['module']}` (fan-out {top.get('fan_out', 0)}){wires}", "",
    ]


def build_changelog(project_root: str | Path) -> str:
    root = Path(project_root)
    body: list[str] = []
    for section in (_commits_section, _fixes_section, _resolved_section,
                    _health_section, _coordinator_section):
        try:
            body += section(root)
        except Exception:
            continue
    if not body:
        body = ["_Nothing to report yet — commit some work, run "
                "`apex maintain`, snapshot a roadmap._", ""]
    return "\n".join([
        "# Release notes — written from evidence, not memory", "",
        *body,
        "_Generated by `apex changelog` — every line above is backed by an "
        "artifact (git history, proof-of-fix, roadmap diff, the grade)._", "",
    ])
