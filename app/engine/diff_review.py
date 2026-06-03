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


@dataclass
class ReviewFinding:
    file: str
    line: int
    category: str          # security | bug | style | docs
    severity: str          # high | medium | low
    message: str
    auto_fixable: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewResult:
    base: str
    files_reviewed: int
    findings: list[ReviewFinding] = field(default_factory=list)

    @property
    def auto_fixable_count(self) -> int:
        return sum(1 for f in self.findings if f.auto_fixable)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "files_reviewed": self.files_reviewed,
            "findings": [f.to_dict() for f in self.findings],
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


def scan_findings(rel_path: str, source: str) -> list[ReviewFinding]:
    """All detector findings in a file (line-level), before diff filtering.

    Detection logic lives in the canonical :mod:`app.engine.detectors` module;
    this just attaches the file path.
    """
    from app.engine.detectors import detect

    return [
        ReviewFinding(rel_path, i.line, i.category, i.severity, i.message, i.auto_fixable)
        for i in detect(source)
    ]


def review(project_root: str, base: str = "HEAD") -> ReviewResult:
    """Review only the lines changed since ``base``."""
    changes = changed_lines(project_root, base)
    findings: list[ReviewFinding] = []
    for rel, lines in sorted(changes.items()):
        path = Path(project_root) / rel
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for f in scan_findings(rel, source):
            if f.line in lines:
                findings.append(f)
    # Most serious first, then by file/line for stable output.
    sev_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (sev_rank.get(f.severity, 3), f.file, f.line))
    return ReviewResult(base=base, files_reviewed=len(changes), findings=findings)


def render_review_markdown(result: ReviewResult) -> str:
    """Render the diff review as a PR-style comment."""
    lines = [f"# Apex review — changes since `{result.base}`", ""]
    if result.files_reviewed == 0:
        lines += ["_No changed Python files to review._", ""]
        return "\n".join(lines)
    if not result.findings:
        lines += [f"Reviewed {result.files_reviewed} changed file(s). "
                  "**No issues found in the changed lines** 🎉", ""]
        return "\n".join(lines)

    lines.append(
        f"Reviewed {result.files_reviewed} changed file(s) · "
        f"**{len(result.findings)} issue(s)** "
        f"({result.auto_fixable_count} auto-fixable by `apex maintain`)."
    )
    lines.append("")
    icon = {"high": "🔴", "medium": "🟠", "low": "🔵"}
    for f in result.findings:
        fix = " · _Apex can auto-fix_" if f.auto_fixable else " · _needs a human_"
        lines.append(
            f"- {icon.get(f.severity, '⚪')} `{f.file}:{f.line}` "
            f"**[{f.category}]** {f.message}{fix}"
        )
    lines.append("")
    return "\n".join(lines)
