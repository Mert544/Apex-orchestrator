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


# Severity -> grade weight: a pile of medium smells must not score like RCEs.
_SEVERITY_WEIGHT = {"critical": 6, "high": 4, "medium": 2, "low": 1}


def _scan_own_modules(project_root: str | Path, profile: Any) -> tuple[set[str], int, int, int]:
    """One detect() pass over the project's own modules — the single grade source.

    Returns ``(reliability_debt_modules, correctness_bug_count, security_count,
    security_weight)``:
    - reliability debt = modules with an auto-fixable reliability issue
      (open() without encoding / network call without timeout);
    - correctness bugs = high-severity *logic* bugs that are likely/guaranteed
      crashes or dead code (frozen-dataclass mutation, return-in-finally,
      unreachable except, assert-on-a-tuple, comparison-with-itself).
      ``mutable-default`` is excluded — it already counts under code-debt;
    - security = every security-category finding (count + severity weight), so
      the grade and ``apex review`` are built on the same detector (and the same
      inline-suppression rules). Fixtures/tests are skipped throughout.
    """
    from app.engine.detectors import detect

    root = Path(project_root)
    reliability: set[str] = set()
    bugs = 0
    sec_count = 0
    sec_weight = 0
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
        bugs += sum(1 for i in issues
                    if i.category == "bug" and i.severity == "high" and not i.fix_kind)
        security = [i for i in issues if i.category == "security"]
        sec_count += len(security)
        sec_weight += sum(_SEVERITY_WEIGHT.get(i.severity, 1) for i in security)
    return reliability, bugs, sec_count, sec_weight


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
    reliability_modules, correctness_bugs, findings, weighted_findings = _scan_own_modules(project_root, profile)
    debt_modules |= reliability_modules
    debt = len(debt_modules)

    components: list[Component] = []
    fixes: list[str] = []

    def penalize(name: str, lost: int, detail: str, fix: str | None = None) -> None:
        components.append(Component(name, lost, detail))
        if lost > 0 and fix:
            fixes.append(fix)

    sec_lost = min(30, weighted_findings)
    penalize("Security", sec_lost, f"{findings} finding(s)",
             "run `apex maintain` to auto-fix eval/os.system/yaml/bare-except" if sec_lost else None)

    arch_lost = min(20, cycles * 5 + fragile * 4)
    penalize("Architecture", arch_lost, f"{cycles} import cycle(s), {fragile} fragile module(s)",
             "break import cycles and add tests to fragile hubs" if arch_lost else None)

    # Shallow-tested modules (covered only by import-smoke / type stubs) get
    # HALF credit, not full — linkage is not correctness, so a project can't
    # claim a clean Testing score on shape-only tests.
    effective_untested = untested + 0.5 * shallow
    test_lost = min(25, round(effective_untested / total_modules * 25))
    if shallow:
        detail = f"{untested} untested + {shallow} shallow-tested module(s) of ~{total_modules}"
        fix = "add tests to the untested modules and deepen the shallow (type-only) ones"
    else:
        detail = f"{untested} untested module(s) of ~{total_modules}"
        fix = "add a first test layer to the untested modules"
    penalize("Testing", test_lost, detail, fix if test_lost else None)

    debt_lost = min(15, debt * 3)
    penalize("Code debt", debt_lost, f"{debt} module(s) with modernization / mutable-default / reliability debt",
             "run `apex maintain` to modernize, fix mutable defaults, and add encodings/timeouts" if debt_lost else None)

    # Correctness: high-severity logic bugs (likely/guaranteed crashes or dead
    # code) the detector finds but that no other component reflected — so a real
    # bug now visibly costs the grade, not just a review note.
    corr_lost = min(20, correctness_bugs * 5)
    penalize("Correctness", corr_lost, f"{correctness_bugs} likely-crash / dead-code bug(s)",
             "fix the logic bugs flagged by `apex review` (frozen-dataclass mutation, "
             "return-in-finally, unreachable except, ...)" if corr_lost else None)

    score = max(0, 100 - (sec_lost + arch_lost + test_lost + debt_lost + corr_lost))
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
