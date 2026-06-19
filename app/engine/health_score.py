"""A single, memorable project health grade (A–F) from real signals.

Every other view is a list; this is the number a person remembers. It rolls the
engine's structural signals — security findings, import cycles, fragile hubs,
test linkage, and modernization/mutable-default debt — into a 0–100 score and a
letter grade, with a breakdown of exactly what is costing points and the cheapest
ways to climb. Deterministic; built from the ProjectProfile + a security scan.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
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
    # One honest line about how much of a polyglot repo the grade actually
    # speaks for (Apex analyses only Python). Empty when the repo is all-Python
    # / has no out-of-scope content, so the grade reads unchanged there.
    scope_line: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score, "letter": self.letter,
            "components": [c.to_dict() for c in self.components], "fixes": self.fixes,
            # Carry the same honest scope disclosure the markdown renders, so a
            # scripted/JSON consumer (CI gate, dashboard, buyer) is never shown a
            # bare A+/100 on a repo Apex only partly analysed. Empty for an
            # all-Python repo, so the JSON is unchanged there.
            "scope_line": self.scope_line,
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

# Maintainability: cyclomatic complexity above which a single function is judged
# "hard to maintain" (branch-node count, per code_metrics.function_complexities;
# a tidy function scores 0-2, so this only fires on genuinely branchy code). The
# penalty is small-capped so a complex codebase can't dominate the grade and a
# clean one loses nothing.
_COMPLEXITY_CEILING = 12
_MAINT_CAP = 10

# Duplication: each copy-pasted block (>= 5 statements, in >= 2 places) costs one
# point, small-capped so a duplication-heavy codebase can't dominate the grade and
# a clean one loses nothing. Computed once per grade() from the dedup detector,
# which already excludes fixtures/tests.
_DUP_CAP = 10


def _scan_maintainability(
    project_root: str | Path, profile: Any,
) -> tuple[int, list[str]]:
    """Count over-ceiling-complexity functions in the project's own modules.

    Returns ``(over_threshold_count, top_files)`` where ``top_files`` is the
    up-to-3 own modules with the most functions whose cyclomatic complexity
    exceeds ``_COMPLEXITY_CEILING``, sorted by that count. Fixture/test files are
    excluded (same rule as the other components); unreadable files are skipped.
    """
    from app.tools.code_metrics import function_complexities

    root = Path(project_root)
    over = 0
    by_file: dict[str, int] = {}
    for m in (getattr(profile, "module_to_tests", {}) or {}):
        if not isinstance(m, str) or not m.endswith(".py") or _is_fixture_path(m):
            continue
        try:
            text = (root / m).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        complex_fns = sum(1 for _name, _lineno, cx in function_complexities(text)
                          if cx > _COMPLEXITY_CEILING)
        if complex_fns:
            by_file[m] = complex_fns
            over += complex_fns
    top = [f for f, _ in sorted(by_file.items(), key=lambda kv: -kv[1])[:3]]
    return over, top


def _own_modules(project_root: str | Path, profile: Any):
    """Yield ``(module, source_text)`` for each readable own .py module.

    Same selection/suppression rule as the other components: strings only,
    ``.py`` only, fixtures/tests excluded, unreadable files skipped.
    """
    root = Path(project_root)
    for m in (getattr(profile, "module_to_tests", {}) or {}):
        if not isinstance(m, str) or not m.endswith(".py") or _is_fixture_path(m):
            continue
        try:
            yield m, (root / m).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue


def _is_reliability_debt(issues: list[Any]) -> bool:
    """True when a module carries reliability debt (missing encoding/timeout)."""
    return any(i.fix_kind in ("open-encoding", "net-timeout") for i in issues)


def _count_correctness_bugs(issues: list[Any]) -> int:
    """High-severity logic bugs the detector flags with no auto-fix."""
    return sum(1 for i in issues
               if i.category == "bug" and i.severity == "high" and not i.fix_kind)


def _security_weight(issues: list[Any]) -> tuple[int, int]:
    """``(finding_count, severity_weight)`` for a module's security findings."""
    security = [i for i in issues if i.category == "security"]
    w = sum(_SEVERITY_WEIGHT.get(i.severity, 1) for i in security)
    return len(security), w


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

    reliability: set[str] = set()
    bugs = 0
    sec_count = 0
    sec_weight = 0
    sec_by_file: dict[str, int] = {}
    bug_files: list[str] = []
    for m, text in _own_modules(project_root, profile):
        issues = detect(text)
        if _is_reliability_debt(issues):
            reliability.add(m)
        file_bugs = _count_correctness_bugs(issues)
        if file_bugs:
            bug_files.append(m)
        bugs += file_bugs
        count, w = _security_weight(issues)
        if w:
            sec_by_file[m] = sec_by_file.get(m, 0) + w
        sec_count += count
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


# A scored bucket: the Component to record plus the fix to surface when it costs
# points (None = no fix). Each per-bucket scorer is a pure function of already-
# extracted metrics, so the penalty math lives in one named place per area.
_Bucket = tuple[Component, str | None]


@dataclass
class _GradeMetrics:
    """All the raw signals the per-bucket scorers read, extracted once.

    A pure projection of the (light) ProjectProfile plus the single detect() pass
    and the duplication scan — so the scorers never touch the profile or the disk.
    """
    cycles: int
    fragile: int
    untested: int
    shallow: int
    total_modules: int
    arch_top: list[str]
    untested_list: list[str]
    debt_modules: set[str]
    correctness_bugs: int
    findings: int
    weighted_findings: int
    top_sec_files: list[str]
    top_bug_files: list[str]
    over_complex: int
    maint_top: list[str]
    dup_block_count: int
    dup_top: list[str]


def _modernization_debt_modules(profile: Any) -> set[str]:
    """Non-fixture modules carrying modernization or mutable-default debt."""
    return {
        str(m) for m in (
            (getattr(profile, "modernizable_modules", []) or [])
            + (getattr(profile, "mutable_default_modules", []) or [])
        )
        if not _is_fixture_path(str(m))
    }


def _arch_top_offenders(profile: Any) -> list[str]:
    """Top architecture offenders: cycle members, else fragile modules (cap 3)."""
    cycle_mods = sorted({m for cyc in (getattr(profile, "import_cycles", []) or [])
                         for m in cyc})[:3]
    arch_top = cycle_mods or sorted(getattr(profile, "fragile_modules", []) or [])[:3]
    return [str(m) for m in arch_top]


def _collect_metrics(project_root: str | Path, profile: Any) -> _GradeMetrics:
    """Project the profile + detect/dedup scans into the scorers' input metrics."""
    debt_modules = _modernization_debt_modules(profile)
    # ONE detect() pass over the project's own code is the single source for the
    # grade (same detector + suppression rules as `apex review`): it yields the
    # severity-weighted Security count, the reliability debt (folded into
    # code-debt), and the Correctness logic-bug count. Grade path only, so the
    # cost stays out of the common profiler call.
    (reliability_modules, correctness_bugs, findings,
     weighted_findings, top_sec_files, top_bug_files) = _scan_own_modules(project_root, profile)
    debt_modules |= reliability_modules

    over_complex, maint_top = _scan_maintainability(project_root, profile)
    dup_block_count, dup_top = _scan_duplication(project_root)

    return _GradeMetrics(
        cycles=len(getattr(profile, "import_cycles", []) or []),
        fragile=len(getattr(profile, "fragile_modules", []) or []),
        untested=len(getattr(profile, "untested_modules", []) or []),
        shallow=len(getattr(profile, "shallow_tested_modules", []) or []),
        total_modules=max(1, len(getattr(profile, "module_to_tests", {}) or {})),
        arch_top=_arch_top_offenders(profile),
        untested_list=[str(m) for m in
                       sorted(getattr(profile, "untested_modules", []) or [])[:3]],
        debt_modules=debt_modules,
        correctness_bugs=correctness_bugs,
        findings=findings,
        weighted_findings=weighted_findings,
        top_sec_files=top_sec_files,
        top_bug_files=top_bug_files,
        over_complex=over_complex,
        maint_top=maint_top,
        dup_block_count=dup_block_count,
        dup_top=dup_top,
    )


def _scan_duplication(project_root: str | Path) -> tuple[int, list[str]]:
    """Count duplicated blocks and the up-to-3 modules with the most copies.

    Copy-pasted blocks are a top maintainability hazard (a bug fixed in one copy
    is silently left in the rest). The detector walks the whole project — so it's
    called ONCE here; it already excludes fixtures/tests.
    """
    from app.engine.dedup import find_duplicates

    dup_blocks = find_duplicates(project_root)
    dup_by_file: dict[str, int] = {}
    for block in dup_blocks:
        for occ in block.occurrences:
            module = occ.rsplit(":", 1)[0]  # occurrences are "module:lineno"
            dup_by_file[module] = dup_by_file.get(module, 0) + 1
    dup_top = [f for f, _ in sorted(dup_by_file.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
    return len(dup_blocks), dup_top


def _score_security(m: _GradeMetrics) -> _Bucket:
    lost = min(30, m.weighted_findings)
    return (
        Component("Security", lost, f"{m.findings} finding(s)", list(m.top_sec_files)),
        "run `apex maintain` to auto-fix eval/os.system/yaml/bare-except" if lost else None,
    )


def _score_architecture(m: _GradeMetrics) -> _Bucket:
    lost = min(20, m.cycles * 5 + m.fragile * 4)
    return (
        Component("Architecture", lost,
                  f"{m.cycles} import cycle(s), {m.fragile} fragile module(s)",
                  list(m.arch_top)),
        "break import cycles and add tests to fragile hubs" if lost else None,
    )


def _score_testing(m: _GradeMetrics) -> _Bucket:
    # Shallow-tested modules (covered only by import-smoke / type stubs) get HALF
    # credit, not full — linkage is not correctness, so a project can't claim a
    # clean Testing score on shape-only tests.
    effective_untested = m.untested + 0.5 * m.shallow
    lost = min(25, round(effective_untested / m.total_modules * 25))
    if m.shallow:
        detail = (f"{m.untested} untested + {m.shallow} shallow-tested "
                  f"module(s) of ~{m.total_modules}")
        fix = "add tests to the untested modules and deepen the shallow (type-only) ones"
    else:
        detail = f"{m.untested} untested module(s) of ~{m.total_modules}"
        fix = "add a first test layer to the untested modules"
    return (
        Component("Testing", lost, detail, list(m.untested_list)),
        fix if lost else None,
    )


def _score_code_debt(m: _GradeMetrics) -> _Bucket:
    debt = len(m.debt_modules)
    lost = min(15, debt * 3)
    return (
        Component(
            "Code debt", lost,
            f"{debt} module(s) with modernization / mutable-default / reliability debt",
            sorted(m.debt_modules)[:3],
        ),
        "run `apex maintain` to modernize, fix mutable defaults, and add encodings/timeouts"
        if lost else None,
    )


def _score_correctness(m: _GradeMetrics) -> _Bucket:
    # High-severity logic bugs (likely/guaranteed crashes or dead code) the
    # detector finds but that no other component reflected — so a real bug now
    # visibly costs the grade, not just a review note.
    lost = min(20, m.correctness_bugs * 5)
    return (
        Component("Correctness", lost,
                  f"{m.correctness_bugs} likely-crash / dead-code bug(s)",
                  list(m.top_bug_files)),
        ("fix the logic bugs flagged by `apex review` (frozen-dataclass mutation, "
         "return-in-finally, unreachable except, ...)") if lost else None,
    )


def _score_maintainability(m: _GradeMetrics) -> _Bucket:
    # The project's most complex / branch-heavy functions cost a small, capped
    # amount — a clean codebase loses nothing, a sprawling one can't dominate the
    # grade. Each over-ceiling function is 2 points up to _MAINT_CAP.
    lost = min(_MAINT_CAP, m.over_complex * 2)
    return (
        Component("Maintainability", lost,
                  f"{m.over_complex} function(s) over complexity {_COMPLEXITY_CEILING}",
                  list(m.maint_top)),
        ("extract helpers from the most complex functions — "
         "see `apex develop --objective shrink-functions`") if lost else None,
    )


def _score_duplication(m: _GradeMetrics) -> _Bucket:
    # Each duplicated block costs one point up to a small cap — a clean codebase
    # loses nothing.
    lost = min(_DUP_CAP, m.dup_block_count)
    return (
        Component("Duplication", lost, f"{m.dup_block_count} duplicated block(s)",
                  list(m.dup_top)),
        "extract the duplicated blocks into shared helpers" if lost else None,
    )


# The grade's buckets, in their fixed display/score order. Adding or reordering a
# bucket happens HERE; the scoring loop below is generic.
_SCORERS = (
    _score_security, _score_architecture, _score_testing, _score_code_debt,
    _score_correctness, _score_maintainability, _score_duplication,
)


def _assemble(metrics: _GradeMetrics) -> tuple[int, list[Component], list[str]]:
    """Run every bucket scorer and fold the results into score/components/fixes."""
    components: list[Component] = []
    fixes: list[str] = []
    penalty = 0
    for scorer in _SCORERS:
        component, fix = scorer(metrics)
        components.append(component)
        penalty += component.points_lost
        if component.points_lost > 0 and fix:
            fixes.append(fix)
    return max(0, 100 - penalty), components, fixes


def grade(project_root: str | Path) -> HealthScore:
    """Compute the project's health grade from its real structure."""
    from app.tools.project_profile import ProjectProfiler, render_analysis_scope_line

    # Light profile: skips the four slow git/doc subprocess scans (churn, debt
    # age, security-exposure age, doc drift) the grade never reads — so grading
    # (and `apex ascend`, which re-grades before+after every round) is ~200x
    # faster on a large repo with a byte-identical grade. See ProjectProfiler.profile.
    profile = ProjectProfiler(str(project_root)).profile(light=True)

    metrics = _collect_metrics(project_root, profile)
    score, components, fixes = _assemble(metrics)
    # Honest scope line — only non-empty on a polyglot repo with out-of-scope
    # content, so an all-Python project's grade output is unchanged.
    scope_line = render_analysis_scope_line(profile)
    return HealthScore(score=score, letter=_letter(score), components=components,
                       fixes=fixes, scope_line=scope_line)


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
    # Honest analysis-scope line — present only on a polyglot repo with content
    # outside Apex's Python analysis, so an all-Python project's grade reads
    # unchanged. Stated as a strength: exactly what the grade did and did NOT cover.
    if h.scope_line:
        lines.append(f"_{h.scope_line}_")
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
