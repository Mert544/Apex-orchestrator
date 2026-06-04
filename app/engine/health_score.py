"""A single, memorable project health grade (A–F) from real signals.

Every other view is a list; this is the number a person remembers. It rolls the
engine's structural signals — security findings, import cycles, fragile hubs,
test linkage, and modernization/mutable-default debt — into a 0–100 score and a
letter grade, with a breakdown of exactly what is costing points and the cheapest
ways to climb. Deterministic; built from the ProjectProfile + a security scan.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Component:
    name: str
    points_lost: int
    detail: str

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
    try:
        from app.agents.skills import SecurityAgent

        result = SecurityAgent().run(project_root=str(project_root))
        # A health grade reflects the project's *own* code — not intentional
        # vulnerability fixtures or test files, which legitimately contain
        # "risky" patterns. Exclude those from the security count.
        findings = sum(
            1 for f in (result.get("findings") or [])
            if not _is_fixture_path(str(f.get("file", "")))
        )
    except Exception:
        findings = 0

    cycles = len(getattr(profile, "import_cycles", []) or [])
    fragile = len(getattr(profile, "fragile_modules", []) or [])
    untested = len(getattr(profile, "untested_modules", []) or [])
    total_modules = max(1, len(getattr(profile, "module_to_tests", {}) or {}))
    # Code-debt counts the project's *own* code, not test/fixture files — the
    # same exclusion already applied to security findings above. A mutable
    # default inside tests/ shouldn't drag down a project's production grade.
    debt = sum(
        1 for m in (
            (getattr(profile, "modernizable_modules", []) or [])
            + (getattr(profile, "mutable_default_modules", []) or [])
        )
        if not _is_fixture_path(str(m))
    )

    components: list[Component] = []
    fixes: list[str] = []

    def penalize(name: str, lost: int, detail: str, fix: str | None = None) -> None:
        components.append(Component(name, lost, detail))
        if lost > 0 and fix:
            fixes.append(fix)

    sec_lost = min(30, findings * 5)
    penalize("Security", sec_lost, f"{findings} finding(s)",
             "run `apex maintain` to auto-fix eval/os.system/yaml/bare-except" if sec_lost else None)

    arch_lost = min(20, cycles * 5 + fragile * 4)
    penalize("Architecture", arch_lost, f"{cycles} import cycle(s), {fragile} fragile module(s)",
             "break import cycles and add tests to fragile hubs" if arch_lost else None)

    untested_ratio = untested / total_modules
    test_lost = min(25, round(untested_ratio * 25))
    penalize("Testing", test_lost, f"{untested} untested module(s) of ~{total_modules}",
             "add a first test layer to the untested modules" if test_lost else None)

    debt_lost = min(15, debt * 3)
    penalize("Code debt", debt_lost, f"{debt} module(s) with modernization/mutable-default debt",
             "run `apex maintain` to modernize comparisons and fix mutable defaults" if debt_lost else None)

    score = max(0, 100 - (sec_lost + arch_lost + test_lost + debt_lost))
    return HealthScore(score=score, letter=_letter(score), components=components, fixes=fixes)


def render_grade_markdown(h: HealthScore) -> str:
    """Render the grade with its breakdown and the cheapest ways to improve."""
    badge = {"A+": "🏆", "A": "🥇", "A-": "🥇", "B+": "🟢", "B": "🟢", "B-": "🟢",
             "C+": "🟡", "C": "🟡", "C-": "🟡", "D+": "🟠", "D": "🟠", "D-": "🟠"}.get(h.letter, "🔴")
    lines = [f"# Project health: {badge} **{h.letter}**  ({h.score}/100)", ""]
    lines.append("| Area | Points lost | Detail |")
    lines.append("|---|---:|---|")
    for c in h.components:
        lines.append(f"| {c.name} | −{c.points_lost} | {c.detail} |")
    lines.append("")
    if h.fixes:
        lines.append("## Cheapest ways to climb")
        for f in h.fixes:
            lines.append(f"- {f}")
    else:
        lines.append("_Clean bill of health — nothing is costing points._")
    lines.append("")
    return "\n".join(lines)
