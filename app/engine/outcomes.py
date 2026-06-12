"""Outcome rubrics — the organism verifies its own work against YOUR bar.

Inspired by Claude Managed Agents' *Outcomes* (a separate grader, blind to
the worker's reasoning, re-reads the artifact against a rubric and either
passes it or returns a per-criterion gap list) — translated to the Apex
paradigm: the grader here reads only the organism's **artifacts** (the grade,
the proof-of-fix record, saved briefs, the live profile). It cannot see how
the work was done, only what is true now — the separation of context that
keeps a worker from rationalizing its own mediocre output, achieved not by
a second context window but by construction. Deterministic, zero tokens.

The rubric lives in ``.apex/outcomes.json``:

    {"criteria": [
        {"type": "grade_min", "value": 90},
        {"type": "max_security_modules", "value": 0},
        {"type": "no_rollbacks"},
        {"type": "no_blind_applies"},
        {"type": "brief_resolved", "value": "x.o"}
    ]}

``apex outcomes`` evaluates it and exits non-zero on a gap — a drop-in CI
gate for "is the project meeting the bar we wrote down?".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RUBRIC_REL = ".apex/outcomes.json"

STARTER_RUBRIC: dict[str, Any] = {
    "criteria": [
        {"type": "grade_min", "value": 90},
        {"type": "max_security_modules", "value": 0},
        {"type": "no_rollbacks"},
        {"type": "no_blind_applies"},
    ]
}


@dataclass
class CriterionResult:
    type: str
    passed: bool
    detail: str            # what is true
    gap: str = ""          # what to change (only when failed)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "passed": self.passed,
                "detail": self.detail, "gap": self.gap}


@dataclass
class OutcomeReport:
    passed: bool = True
    criteria: list[CriterionResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed,
                "criteria": [c.to_dict() for c in self.criteria]}


def load_rubric(project_root: str | Path) -> dict[str, Any] | None:
    path = Path(project_root) / RUBRIC_REL
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def init_rubric(project_root: str | Path) -> Path:
    path = Path(project_root) / RUBRIC_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(STARTER_RUBRIC, indent=2), encoding="utf-8")
    return path


# --- the blind graders: each reads ARTIFACTS only -----------------------------

def _grade_min(root: Path, value: Any) -> CriterionResult:
    from app.engine.health_score import grade

    h = grade(root)
    ok = h.score >= int(value)
    return CriterionResult(
        "grade_min", ok, f"grade {h.letter} ({h.score}); bar is {value}",
        "" if ok else f"raise the grade by {int(value) - h.score} point(s) — "
                      "run `apex grade` for the cheapest fixes")


def _max_security_modules(root: Path, value: Any) -> CriterionResult:
    from app.tools.project_profile import ProjectProfiler

    n = len(ProjectProfiler(root).profile().security_finding_modules)
    ok = n <= int(value)
    return CriterionResult(
        "max_security_modules", ok,
        f"{n} module(s) carry security findings; bar is <= {value}",
        "" if ok else "run `apex maintain` — eval/os.system/bare-except fixes "
                      "are tier-gated and test-verified")


def _last_proof(root: Path) -> dict[str, Any] | None:
    path = root / ".apex" / "proof-of-fix.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _no_rollbacks(root: Path, _value: Any) -> CriterionResult:
    proof = _last_proof(root)
    if proof is None:
        return CriterionResult("no_rollbacks", True,
                               "no maintenance pass recorded yet — vacuously met")
    n = int(proof.get("totals", {}).get("rolled_back", 0) or 0)
    return CriterionResult(
        "no_rollbacks", n == 0,
        f"last pass rolled back {n} fix(es)",
        "" if n == 0 else "inspect verification.failing_tests in "
                          ".apex/proof-of-fix.json — the culprits are named")


def _no_blind_applies(root: Path, _value: Any) -> CriterionResult:
    proof = _last_proof(root)
    if proof is None:
        return CriterionResult("no_blind_applies", True,
                               "no maintenance pass recorded yet — vacuously met")
    blind = [
        f["finding"].get("target", "?") for f in proof.get("fixes", [])
        if f.get("outcome") == "applied"
        and ((f.get("verification") or {}).get("strength") or {}).get("level") == "none"
    ]
    ok = not blind
    return CriterionResult(
        "no_blind_applies", ok,
        ("every applied fix had covering tests" if ok
         else f"{len(blind)} fix(es) applied with NO covering test: {', '.join(blind[:3])}"),
        "" if ok else "the test-first shield should have covered these — "
                      "check why no characterization test could be generated")


def _brief_resolved(root: Path, value: Any) -> CriterionResult:
    from app.engine.idea_brief import check_brief

    branch = str(value)
    check = check_brief(root, branch)
    if check is None:
        return CriterionResult(
            "brief_resolved", False, f"no saved brief at `{branch}`",
            f"save it first: apex brief {branch} --save")
    done, total = len(check["resolved"]), check["measured_total"]
    ok = total > 0 and not check["open"]
    return CriterionResult(
        "brief_resolved", ok, f"brief `{branch}`: {done}/{total} measured item(s) resolved",
        "" if ok else "open items remain — `apex brief "
                      f"{branch} --check` names them with today's lines")


def _edges(root: Path) -> list[tuple[str, str]]:
    from app.tools.project_profile import ProjectProfiler

    return [(str(a).replace("\\", "/"), str(b).replace("\\", "/"))
            for a, b in (ProjectProfiler(root).profile().dependency_edges or [])]


def _arch_forbidden(root: Path, value: Any) -> CriterionResult:
    """Fitness function: modules under `from` must not import modules under
    `to` (the import-linter "forbidden" contract, on our own edge data)."""
    src_p, dst_p = str(value.get("from", "")), str(value.get("to", ""))
    bad = [f"{a} → {b}" for a, b in _edges(root)
           if a.startswith(src_p) and b.startswith(dst_p)]
    ok = not bad
    return CriterionResult(
        "arch_forbidden", ok,
        (f"no `{src_p}` → `{dst_p}` imports" if ok
         else f"{len(bad)} forbidden import(s): {'; '.join(bad[:3])}"),
        "" if ok else "invert the dependency or extract a neutral module "
                      "(`apex move` rewrites the imports project-wide)")


def _arch_layers(root: Path, value: Any) -> CriterionResult:
    """Fitness function: ordered layers, highest first — a lower layer must
    never import a higher one (the import-linter "layers" contract)."""
    layers = [str(p) for p in (value or [])]
    rank = {p: i for i, p in enumerate(layers)}  # 0 = highest

    def layer_of(module: str) -> int | None:
        for prefix, i in rank.items():
            if module.startswith(prefix):
                return i
        return None

    bad = []
    for a, b in _edges(root):
        la, lb = layer_of(a), layer_of(b)
        if la is not None and lb is not None and la > lb:  # lower imports higher
            bad.append(f"{a} (layer {la}) → {b} (layer {lb})")
    ok = not bad
    return CriterionResult(
        "arch_layers", ok,
        (f"layering holds across {len(layers)} layer(s)" if ok
         else f"{len(bad)} upward import(s): {'; '.join(bad[:3])}"),
        "" if ok else "a lower layer reaches upward — move the shared piece "
                      "down or invert the dependency")


def _arch_independence(root: Path, value: Any) -> CriterionResult:
    """Fitness function: these sibling packages must not import each other
    (the import-linter "independence" contract)."""
    groups = [str(p) for p in (value or [])]
    bad = []
    for a, b in _edges(root):
        ga = next((g for g in groups if a.startswith(g)), None)
        gb = next((g for g in groups if b.startswith(g)), None)
        if ga and gb and ga != gb:
            bad.append(f"{a} → {b}")
    ok = not bad
    return CriterionResult(
        "arch_independence", ok,
        (f"{len(groups)} package(s) are mutually independent" if ok
         else f"{len(bad)} cross-import(s): {'; '.join(bad[:3])}"),
        "" if ok else "siblings are entangled — extract the shared piece into "
                      "a module both may import")


def _no_import_cycles(root: Path, _value: Any) -> CriterionResult:
    from app.tools.project_profile import ProjectProfiler

    cycles = ProjectProfiler(root).profile().import_cycles or []
    ok = not cycles
    return CriterionResult(
        "no_import_cycles", ok,
        ("the import graph is acyclic" if ok
         else f"{len(cycles)} cycle(s), e.g. {' → '.join(cycles[0])}"),
        "" if ok else "extract the shared piece into a neutral module both "
                      "sides import (exactly how apex fixed its own)")


_GRADERS = {
    "arch_forbidden": _arch_forbidden,
    "arch_layers": _arch_layers,
    "arch_independence": _arch_independence,
    "no_import_cycles": _no_import_cycles,
    "grade_min": _grade_min,
    "max_security_modules": _max_security_modules,
    "no_rollbacks": _no_rollbacks,
    "no_blind_applies": _no_blind_applies,
    "brief_resolved": _brief_resolved,
}


def evaluate(project_root: str | Path,
             rubric: dict[str, Any] | None = None) -> OutcomeReport | None:
    """Grade the project against the rubric. None when no rubric exists."""
    root = Path(project_root)
    rubric = rubric if rubric is not None else load_rubric(root)
    if rubric is None:
        return None
    report = OutcomeReport()
    for criterion in rubric.get("criteria", []) or []:
        ctype = criterion.get("type", "")
        grader = _GRADERS.get(ctype)
        if grader is None:
            report.criteria.append(CriterionResult(
                ctype or "?", False, "unknown criterion type",
                f"supported: {', '.join(sorted(_GRADERS))}"))
            report.passed = False
            continue
        try:
            result = grader(root, criterion.get("value"))
        except Exception as exc:
            result = CriterionResult(ctype, False, f"grader error: {exc}",
                                     "fix the rubric entry or the project state")
        report.criteria.append(result)
        report.passed = report.passed and result.passed
    return report


def render_outcomes_markdown(report: OutcomeReport) -> str:
    verdict = "✅ **PASSED**" if report.passed else "❌ **GAPS REMAIN**"
    lines = [f"# Outcomes — the artifact graded against your rubric: {verdict}", ""]
    for c in report.criteria:
        mark = "✅" if c.passed else "❌"
        lines.append(f"- {mark} `{c.type}` — {c.detail}")
        if c.gap:
            lines.append(f"    ↳ gap: {c.gap}")
    lines += ["", "_The grader reads artifacts only — it cannot see how the "
              "work was done, only what is true now._", ""]
    return "\n".join(lines)
