"""A single, memorable project health grade (A–F) from real signals.

Every other view is a list; this is the number a person remembers. It rolls the
engine's structural signals — security findings, import cycles, fragile hubs,
test linkage, and modernization/mutable-default debt — into a 0–100 score and a
letter grade, with a breakdown of exactly what is costing points and the cheapest
ways to climb. Deterministic; built from the ProjectProfile + a security scan.
"""

from __future__ import annotations

import ast
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


def _is_unparseable_bug(issue: Any) -> bool:
    """True for the detector's SyntaxError marker (an unparseable file).

    A file Apex cannot *parse* (a truncated ``def f(`` or valid newer-grammar
    syntax — PEP 695 ``def f[T]`` / ``type X = ...`` — on an older runtime) is
    out of scope, not a logic bug. The detector reports it as a high-severity
    ``"bug"`` with a ``"SyntaxError: ..."`` message and no fix, but it is the
    *only* finding it can offer for that file. Counting it as a likely-crash /
    dead-code bug is a false accusation: there is no logic bug and no fix to
    point at. We recognise it by the detector's stable message prefix so it can
    be excluded from the Correctness bucket and its remediation.
    """
    return (
        getattr(issue, "category", None) == "bug"
        and getattr(issue, "severity", None) == "high"
        and not getattr(issue, "fix_kind", "")
        and str(getattr(issue, "message", "")).startswith("SyntaxError:")
    )


def _count_correctness_bugs(issues: list[Any]) -> int:
    """High-severity logic bugs the detector flags with no auto-fix.

    Pure-SyntaxError findings (unparseable / newer-grammar files) are excluded:
    an unparseable file is out of scope, not a likely-crash / dead-code bug.
    """
    return sum(1 for i in issues
               if i.category == "bug" and i.severity == "high" and not i.fix_kind
               and not _is_unparseable_bug(i))


def _security_weight(issues: list[Any]) -> tuple[int, int]:
    """``(finding_count, severity_weight)`` for a module's security findings."""
    security = [i for i in issues if i.category == "security"]
    w = sum(_SEVERITY_WEIGHT.get(i.severity, 1) for i in security)
    return len(security), w


# --- unimplemented-stub debt -------------------------------------------------
# An unimplemented function body (``raise NotImplementedError`` / a bare ``...``)
# is real DEVELOPMENT debt: code the project has SIGNALLED it still owes. The
# grade must see it — otherwise a project of stubs can read A+/100 and the grade
# can neither flag the work to do nor show the gain once `apex develop` lands it.
# Folded into the existing Correctness bucket (no new component), so a project
# with no such stubs grades byte-identically to before.
#
# We reuse the develop loop's own detector (`stub_synthesis._is_stub_body`) so
# "stub" means exactly what `apex develop` would try to implement, then narrow to
# the EXPLICIT unfinished markers only — a bare ``pass`` body is too often a
# legitimate no-op (plugin hooks, silenced overrides, base defaults) to charge as
# debt. Abstract / interface / override stubs are excluded by `_is_debt_stub`.

_ABSTRACT_BASES = {"ABC", "Protocol", "ABCMeta"}


def _is_explicit_unimpl(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when ``node``'s body is an EXPLICIT unimplemented marker.

    A lone ``raise NotImplementedError`` / ``raise NotImplementedError(...)`` or a
    bare ``...`` (a leading docstring is ignored). A bare ``pass`` is NOT explicit
    here — it is too often a legitimate no-op to charge as development debt.
    """
    body = list(node.body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(getattr(body[0], "value", None), ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return stmt.value.value is Ellipsis
    if isinstance(stmt, ast.Raise):
        exc = stmt.exc
        if isinstance(exc, ast.Call):
            exc = exc.func
        return isinstance(exc, ast.Name) and exc.id == "NotImplementedError"
    return False


def _is_abstract_decorated(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when any decorator is named ``*abstractmethod`` (abc/typing)."""
    return any("abstractmethod" in ast.unparse(d) for d in node.decorator_list)


def _class_is_interface(cls: ast.ClassDef) -> bool:
    """True when ``cls`` declares an ABC / Protocol / ABCMeta base or metaclass."""
    for base in cls.bases:
        if ast.unparse(base).split(".")[-1] in _ABSTRACT_BASES:
            return True
    for kw in cls.keywords:
        if kw.arg == "metaclass" and ast.unparse(kw.value).split(".")[-1] in _ABSTRACT_BASES:
            return True
    return False


def _subclassed_base_names(trees: list[ast.AST]) -> set[str]:
    """Every class name used as a base anywhere in the scanned project.

    A stub method on such a base class is a template / interface hook a subclass
    fills (e.g. ``Agent._execute``), not unfinished concrete work — so it is
    excluded from stub debt. Project-wide so a base and its subclass may live in
    different modules. Pure function of the file set, so it stays deterministic.
    """
    names: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    names.add(ast.unparse(base).split(".")[-1])
    return names


def _count_unimplemented_stubs(tree: ast.AST, subclassed: set[str]) -> int:
    """Count NON-abstract, unimplemented (NotImplementedError/``...``) stubs.

    Excluded (legitimate, not debt): ``@abstractmethod`` methods; any method whose
    enclosing class is a genuine ABC/Protocol interface, or is itself subclassed in
    the project (a template base whose stub methods are intended override points the
    subclasses fill). Module-level function stubs and stubs on concrete leaf classes
    count.

    A class is exempt ONLY when it is a real interface/ABC OR is subclassed
    in-project. Merely HAVING a base class does NOT exempt it: a concrete subclass
    (``class Impl(Base):`` that is itself instantiated, never abstract, never
    subclassed) whose own body is ``raise NotImplementedError`` is real, unfinished,
    implementable debt — exactly the work ``implement-stub`` exists to land — so it
    MUST count, otherwise the grade under-reports debt and hides those contributions.
    """
    debt = 0
    in_class: set[int] = set()
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        interface = _class_is_interface(cls) or cls.name in subclassed
        for item in cls.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            in_class.add(id(item))
            if interface or _is_abstract_decorated(item):
                continue
            if _is_explicit_unimpl(item):
                debt += 1
    for item in getattr(tree, "body", []):
        if (isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and id(item) not in in_class
                and not _is_abstract_decorated(item)
                and _is_explicit_unimpl(item)):
            debt += 1
    return debt


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


def _scan_stub_debt(project_root: str | Path, profile: Any) -> tuple[int, list[str]]:
    """The project's NON-abstract unimplemented-stub debt (folded into Correctness).

    Returns ``(total_stub_count, top_stub_files)`` — the up-to-3 own modules with
    the most unimplemented stubs. A separate pass from :func:`_scan_own_modules`
    so that function's byte-behaviour is unchanged; called only on the grade path.
    Abstract / interface / override stubs and bare ``pass`` bodies are excluded
    (see :func:`_count_unimplemented_stubs`), so a legitimate ABC isn't charged
    and a project with no real stubs scores byte-identically to before.
    """
    trees: dict[str, ast.AST] = {}
    for m, text in _own_modules(project_root, profile):
        if m.endswith(".pyi"):
            continue  # type-stub file: every body is an intentional stub
        try:
            trees[m] = ast.parse(text)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            continue
    subclassed = _subclassed_base_names(list(trees.values()))
    total = 0
    by_file: dict[str, int] = {}
    for m, tree in trees.items():
        stubs = _count_unimplemented_stubs(tree, subclassed)
        if stubs:
            by_file[m] = stubs
            total += stubs
    top = [f for f, _ in sorted(by_file.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
    return total, top


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
    # Unimplemented-stub debt, folded into the Correctness bucket. Defaulted and
    # placed LAST so existing _GradeMetrics(...) callers/tests that omit it keep
    # working and a no-stub project scores byte-identically to before the fix.
    stub_debt: int = 0
    top_stub_files: list[str] = field(default_factory=list)


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


def _untested_penalty_count(profile: Any) -> int:
    """The TRUE untested-module count for the grade penalty.

    The profile's ``untested_modules`` list is truncated to 5 offenders for
    DISPLAY (consumed by the seeder / idea-gen / dashboards), so its ``len`` is
    not the real total. ``untested_count`` carries the full pre-truncation count;
    prefer it, falling back to the (capped) list length only when the field is
    absent (e.g. older/partial profiles).
    """
    count = getattr(profile, "untested_count", None)
    if count:
        return int(count)
    return len(getattr(profile, "untested_modules", []) or [])


def _shallow_penalty_count(profile: Any) -> int:
    """The TRUE shallow-tested count for the Testing grade penalty.

    ``shallow_tested_modules`` is truncated to 5 offenders for DISPLAY, so its
    ``len`` understates the real total. ``shallow_tested_count`` carries the full
    pre-truncation count; prefer it, falling back to the capped list length only
    when the field is absent (older/partial profiles).
    """
    count = getattr(profile, "shallow_tested_count", None)
    if count:
        return int(count)
    return len(getattr(profile, "shallow_tested_modules", []) or [])


def _fragile_penalty_count(profile: Any) -> int:
    """The fragile-module count for the Architecture grade penalty.

    The Architecture penalty counts ONLY the UNTESTED fragile hubs, not the shallow
    ones. A clean develop improvement (e.g. ``dataclassify``) can shrink a module's
    assertable surface so it flips non-shallow -> shallow; if the penalty counted
    shallow hubs, that verified improvement would newly flag the module as fragile
    and RAISE the fragility penalty (the field-test A-91 -> B+87 regression). So we
    prefer ``fragile_untested_count`` — and honor an explicit ``0`` (the common
    case) via ``is not None``, NOT truthiness. Shallow-but-tested hubs stay in
    ``fragile_count``/``fragile_modules`` (discovery) and keep costing TESTING.

    Older/partial profiles without the untested-only field fall back to the
    pre-fix behaviour: ``fragile_count`` (truncated-to-3 ``fragile_modules`` carries
    only the display offenders), then the capped list length.
    """
    count = getattr(profile, "fragile_untested_count", None)
    if count is not None:  # honor an explicit 0 (the common case)
        return int(count)
    count = getattr(profile, "fragile_count", None)
    if count:
        return int(count)
    return len(getattr(profile, "fragile_modules", []) or [])


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
    # Unimplemented-stub debt (NotImplementedError / ``...`` bodies the project
    # still owes), also folded into the Correctness bucket. A separate pass, so a
    # no-stub project (stub_debt == 0) is byte-identical to the pre-fix grade.
    stub_debt, top_stub_files = _scan_stub_debt(project_root, profile)

    over_complex, maint_top = _scan_maintainability(project_root, profile)
    dup_block_count, dup_top = _scan_duplication(project_root)

    return _GradeMetrics(
        cycles=len(getattr(profile, "import_cycles", []) or []),
        fragile=_fragile_penalty_count(profile),
        untested=_untested_penalty_count(profile),
        shallow=_shallow_penalty_count(profile),
        total_modules=max(1, len(getattr(profile, "module_to_tests", {}) or {})),
        arch_top=_arch_top_offenders(profile),
        untested_list=[str(m) for m in
                       sorted(getattr(profile, "untested_modules", []) or [])[:3]],
        debt_modules=debt_modules,
        correctness_bugs=correctness_bugs,
        stub_debt=stub_debt,
        findings=findings,
        weighted_findings=weighted_findings,
        top_sec_files=top_sec_files,
        top_bug_files=top_bug_files,
        top_stub_files=top_stub_files,
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
    # visibly costs the grade, not just a review note. Folded in alongside is
    # unimplemented-STUB debt (NotImplementedError / ``...`` bodies a project
    # still owes): a stub is invalid-behaviour-in-waiting, so it belongs in
    # Correctness, and now a project of stubs can no longer read A+/100 — the
    # grade flags the develop work to do and rises once `apex develop` lands it.
    # Each stub costs 3 points (a bug costs 5), both inside the same 20-cap.
    lost = min(20, m.correctness_bugs * 5 + m.stub_debt * 3)
    # When there are no stubs the detail/top_files/fix are byte-identical to the
    # pre-stub-debt grade, so a stub-free project's snapshot is unchanged.
    if m.stub_debt:
        detail = (f"{m.correctness_bugs} likely-crash / dead-code bug(s), "
                  f"{m.stub_debt} unimplemented stub(s)")
        top_files = list(dict.fromkeys(list(m.top_bug_files) + list(m.top_stub_files)))[:3]
        fix = ("implement the unimplemented stubs (`apex develop`) and fix the logic "
               "bugs flagged by `apex review`")
    else:
        detail = f"{m.correctness_bugs} likely-crash / dead-code bug(s)"
        top_files = list(m.top_bug_files)
        fix = ("fix the logic bugs flagged by `apex review` (frozen-dataclass mutation, "
               "return-in-finally, unreachable except, ...)")
    return (
        Component("Correctness", lost, detail, top_files),
        fix if lost else None,
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


def grade(project_root: str | Path, profile: Any | None = None) -> HealthScore:
    """Compute the project's health grade from its real structure.

    An already-built ``profile`` may be injected (a full profile is a superset
    of the light one grade reads, so the grade is byte-identical) to avoid
    re-scanning when a caller — e.g. the pulse snapshot — shares one profile
    across sections. When omitted, the light profile is built as before.
    """
    from app.tools.project_profile import ProjectProfiler, render_analysis_scope_line

    # Light profile: skips the four slow git/doc subprocess scans (churn, debt
    # age, security-exposure age, doc drift) the grade never reads — so grading
    # (and `apex ascend`, which re-grades before+after every round) is ~200x
    # faster on a large repo with a byte-identical grade. See ProjectProfiler.profile.
    if profile is None:
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
