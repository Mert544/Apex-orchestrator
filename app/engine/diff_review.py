"""Diff-scoped code review — Apex as a pull-request reviewer.

Where the rest of the engine reasons about a whole project, this looks only at
what *changed*: it reads the git diff, finds the added lines, runs Apex's
detectors over the changed files, and reports the issues that land on those new
lines — exactly what a human reviewer flags on a PR. Each finding notes whether
Apex can auto-fix it (via `apex maintain` / `apex evolve`) or whether it needs a
human.

Read-only and deterministic (a reviewer proposes, it never applies).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _is_fixture_path(path: str) -> bool:
    """Example/fixture/test code carries intentional flaws (a hardcoded secret
    used as test data, an `eval` in a vulnerability fixture). The grade already
    excludes it; the review's CI GATE must too, or every PR fails on a flaw the
    author deliberately put there. Mirrors ProjectProfiler._is_fixture_path."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


def blocking_high_findings(result: "ReviewResult") -> list["ReviewFinding"]:
    """High-severity findings outside fixture/test code — what a CI gate should
    actually fail on (a real risk in shipping code, never a test's own data)."""
    return [f for f in result.findings
            if f.severity == "high" and not _is_fixture_path(f.file)]


@dataclass
class ReviewFinding:
    file: str
    line: int
    category: str          # security | bug | style | docs | convention | refactor (extract/inline)
    severity: str          # high | medium | low
    message: str
    auto_fixable: bool
    fix_kind: str = ""     # detector routing key (drives the suggested fix)
    suggestion: tuple[str, str] | None = None  # (old_line, new_line) when shown

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChangeImpact:
    file: str
    function: str
    lineno: int
    caller_count: int
    callers: list[str] = field(default_factory=list)  # "module:line" strings

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "function": self.function, "lineno": self.lineno,
                "caller_count": self.caller_count, "callers": self.callers}


@dataclass
class ReviewResult:
    base: str
    files_reviewed: int
    findings: list[ReviewFinding] = field(default_factory=list)
    impacts: list[ChangeImpact] = field(default_factory=list)

    @property
    def auto_fixable_count(self) -> int:
        return sum(1 for f in self.findings if f.auto_fixable)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "files_reviewed": self.files_reviewed,
            "findings": [f.to_dict() for f in self.findings],
            "impacts": [i.to_dict() for i in self.impacts],
            "auto_fixable_count": self.auto_fixable_count,
        }


def changed_lines(project_root: str, base: str = "HEAD") -> dict[str, set[int]]:
    """Map each changed .py file → the set of added/modified line numbers."""
    try:
        out = subprocess.run(
            ["git", "diff", "--unified=0", base, "--", "*.py"],
            cwd=project_root, capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return {}
    if out.returncode != 0:
        return {}

    result: dict[str, set[int]] = {}
    current: str | None = None
    for line in out.stdout.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:].strip()
            result.setdefault(current, set())
        elif line.startswith("@@") and current is not None:
            m = _HUNK.match(line)
            if not m:
                continue
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) is not None else 1
            for ln in range(start, start + max(count, 1)):
                result[current].add(ln)
    return {f: lns for f, lns in result.items() if lns}


def _compiled_rules(project_root: str) -> list[tuple]:
    """Saved rewrite rules, pre-compiled to (name, pattern, replacement, tree).
    Unparseable / bare-metavariable patterns are silently dropped — a broken
    rule must never break the review."""
    from app.execution.pattern_rewrite import compile_pattern
    from app.execution.rewrite_rules import load_rules

    out: list[tuple] = []
    for r in load_rules(project_root):
        tree = compile_pattern(r["pattern"])
        if tree is not None:
            out.append((r["name"], r["pattern"], r.get("replacement", ""), tree))
    return out


def scan_findings(rel_path: str, source: str) -> list[ReviewFinding]:
    """All detector findings in a file (line-level), before diff filtering.

    Detection logic lives in the canonical :mod:`app.engine.detectors` module;
    this just attaches the file path.
    """
    from app.engine.detectors import detect

    return [
        ReviewFinding(rel_path, i.line, i.category, i.severity, i.message,
                      i.auto_fixable, i.fix_kind)
        for i in detect(source)
    ]


# Pure single-line rewrites — safe to show as an inline before/after suggestion
# (no import injection or multi-line surgery). Maps fix_kind -> a transform call.
def _line_suggestion(rel: str, source: str, finding: ReviewFinding) -> tuple[str, str] | None:
    """The (old_line, new_line) a clean single-line fix would make at this
    finding's line, or None when the fix isn't a tidy one-liner (eval/os.system
    add imports; flag-only fixes annotate) — those stay 'auto-fixable' without a
    shown diff."""
    from app.execution.semantic.transforms import (
        collection_literal, fstring, modernize, open_encoding, identity_literal,
        negated_comparison, raise_from,
    )
    from app.execution.semantic.transforms import security as security_transforms

    fk = finding.fix_kind
    try:
        if fk == "open-encoding":
            res = open_encoding.apply(rel, source, "open encoding")
        elif fk == "none-comparison":
            res = modernize.apply(rel, source, "modernize none-comparison")
        elif fk == "identity-literal":
            res = identity_literal.apply(rel, source, "identity-literal")
        elif fk == "negated-comparison":
            res = negated_comparison.apply(rel, source, "negated-comparison")
        elif fk == "raise-from":
            res = raise_from.apply(rel, source, "raise-from")
        elif fk == "fstring-no-placeholder":
            res = fstring.apply(rel, source, "fstring no placeholder")
        elif fk == "collection-literal":
            res = collection_literal.apply(rel, source, "collection literal")
        elif fk in ("bare except", "base-exception"):
            res = security_transforms.apply(rel, source, f"fix {fk}")
        else:
            return None
    except Exception:
        return None
    if not res or not res.patch_requests:
        return None
    new = res.patch_requests[0].get("new_content", "")
    old_lines = source.splitlines()
    new_lines = new.splitlines()
    if len(old_lines) != len(new_lines):
        return None  # an import was added or lines shifted — not a tidy one-liner
    idx = finding.line - 1
    if 0 <= idx < len(old_lines) and old_lines[idx] != new_lines[idx]:
        return (old_lines[idx].strip(), new_lines[idx].strip())
    # fall back to the single differing line, if exactly one changed
    diffs = [i for i in range(len(old_lines)) if old_lines[i] != new_lines[i]]
    if len(diffs) == 1:
        i = diffs[0]
        return (old_lines[i].strip(), new_lines[i].strip())
    return None


def _rule_findings(project_root: str, rel: str, source: str,
                   lines: set[int], compiled: list[tuple]) -> list[ReviewFinding]:
    """Violations of the project's saved rewrite rules on the changed lines.

    A saved rule encodes a team convention ("we don't write `len(x) == 0`").
    When a PR introduces a line the rule's pattern matches, that's the
    convention slipping back in — flagged here, auto-fixable by the exact
    `apex rewrite --rule NAME` that defines it. The review now enforces YOUR
    standards, not only Apex's built-in detectors."""
    from app.execution.pattern_rewrite import match_lines

    out: list[ReviewFinding] = []
    for name, pattern, replacement, tree in compiled:
        for ln in match_lines(source, tree):
            if ln in lines:
                out.append(ReviewFinding(
                    file=rel, line=ln, category="convention", severity="medium",
                    message=(f"rule `{name}`: `{pattern}` → `{replacement}` "
                             "(team convention re-entered)"),
                    auto_fixable=True, fix_kind=f"rule:{name}"))
    return out


def _extraction_findings(rel: str, source: str, lines: set[int]) -> list[ReviewFinding]:
    """Long functions on the diff with a clean seam to extract.

    When a PR adds (or grows) a function long enough to have an extractable
    block, the reviewer points at the exact seam and hands you the runnable
    ``apex extract`` command — the same suggestion the roadmap surfaces, now on
    the changed lines. Read-only and non-auto-fixable: extraction is a judgment
    call (which seam, what name), so the reviewer proposes, never applies."""
    from app.execution.extract_method import suggest_extractions

    out: list[ReviewFinding] = []
    for s in suggest_extractions(source):
        touched = [ln for ln in lines if s["start"] <= ln <= s["end"]]
        if not touched:
            continue  # the PR didn't touch this seam — not on the diff
        cmd = f"apex extract {rel} {s['start']} {s['end']} {s['name']}"
        out.append(ReviewFinding(
            file=rel, line=min(touched), category="refactor", severity="low",
            message=(f"`{s['function']}()` has a {s['lines_saved']}-line extractable "
                     f"block (lines {s['start']}-{s['end']}) — `{cmd}`"),
            auto_fixable=False, fix_kind="extract"))
    return out


def _inline_findings(project_root: str,
                     changed: dict[str, set[int]]) -> list[ReviewFinding]:
    """Tiny single-use helpers on the diff that ``apex inline`` would fold away.

    The mirror image of :func:`_extraction_findings`: where extraction points at
    a function long enough to split, this points at one small enough to dissolve
    into its lone caller. Runs the project-level :func:`suggest_inlines` ONCE,
    then keeps only the helpers whose definition line landed on the diff (the
    helper was added or touched by THIS change) — an untouched helper elsewhere
    stays quiet, the same discipline the extraction findings keep. Read-only and
    non-auto-fixable: inlining is a judgment call, so the reviewer proposes the
    runnable ``apex inline FUNC`` command, never applies it."""
    from app.execution.inline_function import suggest_inlines

    out: list[ReviewFinding] = []
    for s in suggest_inlines(project_root):
        rel = s["module"]
        if _is_fixture_path(rel):
            continue
        lines = changed.get(rel)
        if not lines or s["line"] not in lines:
            continue  # the helper's def isn't on the diff — not this change's call
        fn = s["function"]
        n = s["call_sites"]
        sites = f"{n} call site" if n == 1 else f"{n} call sites"
        out.append(ReviewFinding(
            file=rel, line=s["line"], category="refactor", severity="low",
            message=(f"`{fn}()` is a single-use helper ({sites}) — `apex inline {fn}`"),
            auto_fixable=False, fix_kind="inline"))
    return out


def _duplication_findings(project_root: str,
                          changed: dict[str, set[int]]) -> list[ReviewFinding]:
    """Copy-pasted blocks the diff introduces or sits on.

    Duplication is a project-level signal (a block is "duplicated" only relative
    to its OTHER copies elsewhere in the tree), so :func:`find_duplicates` runs
    ONCE over the whole project — like :func:`_inline_findings`. For each
    duplicated block, the reviewer keeps only the occurrence whose location lands
    on the diff (a changed file AND a changed line): the PR either just added a
    copy or is editing one that already had siblings. A duplicate sitting
    entirely outside the change stays quiet — that's not this PR's problem to
    flag. Read-only and non-auto-fixable: extracting a shared helper is a
    judgment call (which copies, what name), so the reviewer proposes, never
    applies."""
    from app.engine.dedup import find_duplicates

    out: list[ReviewFinding] = []
    for block in find_duplicates(project_root):
        # Split each "module:lineno" once; keep the ones on the diff.
        parsed: list[tuple[str, int]] = []
        for occ in block.occurrences:
            mod, _, lineno = occ.rpartition(":")
            if not mod or not lineno.isdigit():
                continue
            parsed.append((mod, int(lineno)))
        for mod, lineno in parsed:
            if _is_fixture_path(mod):
                continue
            lines = changed.get(mod)
            if not lines or lineno not in lines:
                continue  # this copy isn't on the diff — not this change's clone
            others = [f"`{m}:{ln}`" for m, ln in parsed if (m, ln) != (mod, lineno)]
            if not others:
                continue  # no sibling copy left to point at
            other_locations = ", ".join(others)
            out.append(ReviewFinding(
                file=mod, line=lineno, category="refactor", severity="low",
                message=(f"this {block.lines}-statement block is duplicated at "
                         f"{other_locations} — consider extracting a shared helper"),
                auto_fixable=False, fix_kind="duplication"))
    return out


def review(project_root: str, base: str = "HEAD") -> ReviewResult:
    """Review only the lines changed since ``base``."""
    changes = changed_lines(project_root, base)
    findings: list[ReviewFinding] = []
    sources: dict[str, str] = {}
    compiled = _compiled_rules(project_root)
    for rel, lines in sorted(changes.items()):
        path = Path(project_root) / rel
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        sources[rel] = source
        for f in scan_findings(rel, source):
            if f.line in lines:
                if f.auto_fixable:
                    f.suggestion = _line_suggestion(rel, source, f)
                findings.append(f)
        if compiled:
            findings.extend(_rule_findings(project_root, rel, source, lines, compiled))
        if not _is_fixture_path(rel):
            findings.extend(_extraction_findings(rel, source, lines))
    # Inlining is project-level (single-use across the whole tree), so it runs
    # ONCE over the full changed map rather than per file.
    findings.extend(_inline_findings(project_root, changes))
    # Duplication is likewise project-level (a block is a clone only relative to
    # its other copies), so it too runs ONCE over the full changed map.
    findings.extend(_duplication_findings(project_root, changes))
    # Most serious first, then by file/line for stable output.
    sev_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (sev_rank.get(f.severity, 3), f.file, f.line))
    impacts = _change_impacts(project_root, changes, sources)
    return ReviewResult(base=base, files_reviewed=len(changes), findings=findings, impacts=impacts)


def _change_impacts(project_root: str, changes: dict[str, set[int]],
                    sources: dict[str, str]) -> list[ChangeImpact]:
    """For each changed function, how far its change could ripple (direct callers)."""
    import ast

    from app.engine.call_graph import CallGraph

    graph = CallGraph.build(project_root)
    impacts: list[ChangeImpact] = []
    for rel, lines in sorted(changes.items()):
        source = sources.get(rel)
        if not source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            end = getattr(node, "end_lineno", node.lineno)
            if not any(node.lineno <= ln <= end for ln in lines):
                continue  # this function wasn't touched
            callers = [c for c in graph.direct_callers(node.name)
                       if not (c.module == rel and c.lineno == node.lineno)]
            if callers:
                impacts.append(ChangeImpact(
                    file=rel, function=node.name, lineno=node.lineno,
                    caller_count=len(callers),
                    callers=[f"{c.module}:{c.lineno}" for c in callers[:8]],
                ))
    impacts.sort(key=lambda i: (-i.caller_count, i.file, i.lineno))
    return impacts


def render_review_markdown(result: ReviewResult, limit: int = 0) -> str:
    """Render the diff review as a PR-style comment.

    ``limit`` caps how many findings are listed (highest-severity first,
    already sorted) — a wide diff against a long-running base can produce
    thousands of findings whose rendered comment would blow past a PR
    comment's 65 536-char ceiling, so the CI workflow passes a bound and
    the rest are summarized in a footer. ``0`` = unlimited (the terminal)."""
    lines = [f"# Apex review — changes since `{result.base}`", ""]
    if result.files_reviewed == 0:
        lines += ["_No changed Python files to review._", ""]
        return "\n".join(lines)
    if not result.findings:
        lines += [f"Reviewed {result.files_reviewed} changed file(s). "
                  "**No issues found in the changed lines** 🎉", ""]
    else:
        shown = result.findings[:limit] if limit and limit > 0 else result.findings
        hidden = len(result.findings) - len(shown)
        lines.append(
            f"Reviewed {result.files_reviewed} changed file(s) · "
            f"**{len(result.findings)} issue(s)** "
            f"({result.auto_fixable_count} auto-fixable by `apex maintain`)."
        )
        lines.append("")
        icon = {"high": "🔴", "medium": "🟠", "low": "🔵"}
        for f in shown:
            if f.suggestion:
                fix = " · _suggested fix below_"
            elif f.fix_kind.startswith("rule:"):
                fix = f" · _fix: `apex rewrite --rule {f.fix_kind[5:]}`_"
            elif f.fix_kind == "extract":
                fix = " · _refactor: run the command above_"
            elif f.fix_kind == "inline":
                fix = " · _refactor: run the command above_"
            elif f.fix_kind == "duplication":
                fix = " · _refactor: extract a shared helper_"
            elif f.auto_fixable:
                fix = " · _Apex can auto-fix_"
            else:
                fix = " · _needs a human_"
            lines.append(
                f"- {icon.get(f.severity, '⚪')} `{f.file}:{f.line}` "
                f"**[{f.category}]** {f.message}{fix}"
            )
            if f.suggestion:
                old, new = f.suggestion
                # A reviewer that *proposes the patch*, not just flags the issue.
                lines += ["", "  ```diff", f"  - {old}", f"  + {new}", "  ```", ""]
        if hidden > 0:
            lines.append(f"- … and **{hidden} more** finding(s) — run "
                         "`apex review` locally, or see the full SARIF artifact.")
        lines.append("")

    if result.impacts:
        lines.append("## 🔗 Change impact (review the call sites too)")
        for im in result.impacts:
            shown = ", ".join(f"`{c}`" for c in im.callers)
            more = f" (+{im.caller_count - len(im.callers)} more)" if im.caller_count > len(im.callers) else ""
            lines.append(
                f"- `{im.file}:{im.lineno}` **{im.function}()** is called by "
                f"**{im.caller_count}** function(s): {shown}{more}"
            )
        lines.append("")
    return "\n".join(lines)
