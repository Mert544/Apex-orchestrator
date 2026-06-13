"""A single, memorable project health grade (A–F) from real signals.

Every other view is a list; this is the number a person remembers. It rolls the
engine's structural signals — security findings, import cycles, fragile hubs,
test linkage, and modernization/mutable-default debt — into a 0–100 score and a
letter grade, with a breakdown of exactly what is costing points and the cheapest
ways to climb. Deterministic; built from the ProjectProfile + a security scan.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_SNAPSHOT_REL = ".apex/grade-snapshot.json"


@dataclass
class Component:
    name: str
    points_lost: int
    detail: str
    top_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HealthScore:
    score: int
    letter: str
    components: list[Component] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score, "letter": self.letter,
            "components": [c.to_dict() for c in self.components], "fixes": self.fixes,
        }


def _is_fixture_path(path: str) -> bool:
    """True for example/test/fixture files, which may carry intentional risks."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


# Severity -> grade weight: a pile of medium smells must not score like RCEs.
_SEVERITY_WEIGHT = {"critical": 6, "high": 4, "medium": 2, "low": 1}


def _scan_own_modules(
    project_root: str | Path, profile: Any,
) -> tuple[set[str], int, int, int, list[str], list[str]]:
    """One detect() pass over the project's own modules — the single grade source.

    Returns ``(reliability_debt_modules, correctness_bug_count, security_count,
    security_weight, top_sec_files, top_bug_files)``.  Top-offender lists are
    sorted by severity weight (security) or bug count (correctness), capped at 3,
    and used by the render to tell the user WHERE to look first — not just how bad.
    """
    from app.engine.detectors import detect

    root = Path(project_root)
    reliability: set[str] = set()
    bugs = 0
    sec_count = 0
    sec_weight = 0
    sec_by_file: dict[str, int] = {}
    bug_files: list[str] = []
    for m in (getattr(profile, "module_to_tests", {}) or {}):
        if not isinstance(m, str) or not m.endswith(".py") or _is_fixture_path(m):
            continue
        try:
            text = (root / m).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        issues = detect(text)
        if any(i.fix_kind in ("open-encoding", "net-timeout") for i in issues):
            reliability.add(m)
        file_bugs = sum(1 for i in issues
                        if i.category == "bug" and i.severity == "high" and not i.fix_kind)
        if file_bugs:
            bug_files.append(m)
        bugs += file_bugs
        security = [i for i in issues if i.category == "security"]
        w = sum(_SEVERITY_WEIGHT.get(i.severity, 1) for i in security)
        if w:
            sec_by_file[m] = sec_by_file.get(m, 0) + w
        sec_count += len(security)
        sec_weight += w
    top_sec = [f for f, _ in sorted(sec_by_file.items(), key=lambda kv: -kv[1])[:3]]
    return reliability, bugs, sec_count, sec_weight, top_sec, bug_files[:3]


def _letter(score: int) -> str:
    table = [(97, "A+"), (93, "A"), (90, "A-"), (87, "B+"), (83, "B"), (80, "B-"),
             (77, "C+"), (73, "C"), (70, "C-"), (67, "D+"), (63, "D"), (60, "D-")]
    for cutoff, letter in table:
        if score >= cutoff:
            return letter
    return "F"


def grade(project_root: str | Path) -> HealthScore:
    """Compute the project's health grade from its real structure."""
    from app.tools.project_profile import ProjectProfiler

    profile = ProjectProfiler(str(project_root)).profile()

    cycles = len(getattr(profile, "import_cycles", []) or [])
    fragile = len(getattr(profile, "fragile_modules", []) or [])
    untested = len(getattr(profile, "untested_modules", []) or [])
    shallow = len(getattr(profile, "shallow_tested_modules", []) or [])
    total_modules = max(1, len(getattr(profile, "module_to_tests", {}) or {}))
    # Code-debt counts the project's *own* code, not test/fixture files. A mutable
    # default inside tests/ shouldn't drag down a project's production grade.
    debt_modules = {
        str(m) for m in (
            (getattr(profile, "modernizable_modules", []) or [])
            + (getattr(profile, "mutable_default_modules", []) or [])
        )
        if not _is_fixture_path(str(m))
    }
    # ONE detect() pass over the project's own code is the single source for the
    # grade (same detector + suppression rules as `apex review`): it yields the
    # severity-weighted Security count, the reliability debt (folded into
    # code-debt), and the Correctness logic-bug count. Grade path only, so the
    # cost stays out of the common profiler call.
    (reliability_modules, correctness_bugs, findings,
     weighted_findings, top_sec_files, top_bug_files) = _scan_own_modules(project_root, profile)
    debt_modules |= reliability_modules
    debt = len(debt_modules)

    components: list[Component] = []
    fixes: list[str] = []

    def penalize(name: str, lost: int, detail: str, fix: str | None = None,
                 top_files: list[str] | None = None) -> None:
        components.append(Component(name, lost, detail, top_files or []))
        if lost > 0 and fix:
            fixes.append(fix)

    sec_lost = min(30, weighted_findings)
    penalize("Security", sec_lost, f"{findings} finding(s)",
             "run `apex maintain` to auto-fix eval/os.system/yaml/bare-except" if sec_lost else None,
             top_files=top_sec_files)

    # Top architecture offenders: cycle members + fragile modules.
    cycle_mods = sorted({m for cyc in (getattr(profile, "import_cycles", []) or [])
                         for m in cyc})[:3]
    arch_top = cycle_mods or sorted(getattr(profile, "fragile_modules", []) or [])[:3]
    arch_lost = min(20, cycles * 5 + fragile * 4)
    penalize("Architecture", arch_lost, f"{cycles} import cycle(s), {fragile} fragile module(s)",
             "break import cycles and add tests to fragile hubs" if arch_lost else None,
             top_files=[str(m) for m in arch_top])

    # Shallow-tested modules (covered only by import-smoke / type stubs) get
    # HALF credit, not full — linkage is not correctness, so a project can't
    # claim a clean Testing score on shape-only tests.
    effective_untested = untested + 0.5 * shallow
    test_lost = min(25, round(effective_untested / total_modules * 25))
    untested_list = sorted(getattr(profile, "untested_modules", []) or [])[:3]
    if shallow:
        detail = f"{untested} untested + {shallow} shallow-tested module(s) of ~{total_modules}"
        fix = "add tests to the untested modules and deepen the shallow (type-only) ones"
    else:
        detail = f"{untested} untested module(s) of ~{total_modules}"
        fix = "add a first test layer to the untested modules"
    penalize("Testing", test_lost, detail, fix if test_lost else None,
             top_files=[str(m) for m in untested_list])

    debt_top = sorted(debt_modules)[:3]
    debt_lost = min(15, debt * 3)
    penalize("Code debt", debt_lost, f"{debt} module(s) with modernization / mutable-default / reliability debt",
             "run `apex maintain` to modernize, fix mutable defaults, and add encodings/timeouts" if debt_lost else None,
             top_files=list(debt_top))

    # Correctness: high-severity logic bugs (likely/guaranteed crashes or dead
    # code) the detector finds but that no other component reflected — so a real
    # bug now visibly costs the grade, not just a review note.
    corr_lost = min(20, correctness_bugs * 5)
    penalize("Correctness", corr_lost, f"{correctness_bugs} likely-crash / dead-code bug(s)",
             "fix the logic bugs flagged by `apex review` (frozen-dataclass mutation, "
             "return-in-finally, unreachable except, ...)" if corr_lost else None,
             top_files=top_bug_files)

    score = max(0, 100 - (sec_lost + arch_lost + test_lost + debt_lost + corr_lost))
    return HealthScore(score=score, letter=_letter(score), components=components, fixes=fixes)


def render_grade_markdown(h: HealthScore) -> str:
    """Render the grade with its breakdown, top offenders, and cheapest ways to improve."""
    badge = {"A+": "🏆", "A": "🥇", "A-": "🥇", "B+": "🟢", "B": "🟢", "B-": "🟢",
             "C+": "🟡", "C": "🟡", "C-": "🟡", "D+": "🟠", "D": "🟠", "D-": "🟠"}.get(h.letter, "🔴")
    lines = [f"# Project health: {badge} **{h.letter}**  ({h.score}/100)", ""]
    lines.append("| Area | Points lost | Detail |")
    lines.append("|---|---:|---|")
    for c in h.components:
        lines.append(f"| {c.name} | −{c.points_lost} | {c.detail} |")
    lines.append("")
    # Top offenders — per-component file list to direct the developer's attention.
    offenders = [(c.name, c.top_files) for c in h.components
                 if c.points_lost > 0 and c.top_files]
    if offenders:
        lines.append("## Top offenders")
        for name, files in offenders:
            lines.append(f"- **{name}**: {', '.join(f'`{f}`' for f in files)}")
        lines.append("")
    if h.fixes:
        lines.append("## Cheapest ways to climb")
        for f in h.fixes:
            lines.append(f"- {f}")
    else:
        lines.append("_Clean bill of health — nothing is costing points._")
    lines.append("")
    return "\n".join(lines)


def save_grade_snapshot(project_root: str | Path, h: HealthScore) -> None:
    """Persist the grade to ``.apex/grade-snapshot.json`` for trend tracking."""
    from datetime import date

    path = Path(project_root) / _SNAPSHOT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": date.today().isoformat(),
        "score": h.score,
        "letter": h.letter,
        "components": [{"name": c.name, "points_lost": c.points_lost} for c in h.components],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_grade_snapshot(project_root: str | Path) -> dict | None:
    """Load the saved grade snapshot, or None when none exists."""
    path = Path(project_root) / _SNAPSHOT_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "score" not in data:
        return None
    return data


def render_grade_diff_markdown(old: dict, new: HealthScore) -> str:
    """Compare the saved snapshot to the current grade and render as a trend report."""
    delta = new.score - old["score"]
    sign = "+" if delta > 0 else ""
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
    lines = [
        f"## Grade trend: {old.get('date', '?')} → today",
        f"Score: **{old['score']} {old.get('letter', '')}** → "
        f"**{new.score} {new.letter}** ({sign}{delta} {arrow})",
        "",
        "| Area | Before | After | Change |",
        "|---|---:|---:|---:|",
    ]
    old_comp = {c["name"]: c["points_lost"] for c in old.get("components", [])}
    for c in new.components:
        prev = old_comp.get(c.name, 0)
        diff = prev - c.points_lost  # positive = improvement
        icon = " ✅" if diff > 0 else (" ⚠️" if diff < 0 else "")
        lines.append(f"| {c.name} | −{prev} | −{c.points_lost} | {'+' if diff >= 0 else ''}{diff}{icon} |")
    lines.append("")
    return "\n".join(lines)
