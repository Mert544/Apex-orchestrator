"""Language-agnostic facts layer — make Apex's "X% out of analysis scope" line
ACTIONABLE.

``project_profile`` already reports, honestly, that on a polyglot repo Apex's
Python-only analysis covers a subset (``out_of_scope_ratio``,
``language_breakdown``). But it stops at counts: it says nothing CONCRETE about
that out-of-scope remainder, so on a JS/HTML-heavy repo Apex silently abandons
the non-Python part of the very project it claims to develop.

This module closes that gap one factual step: it names the biggest / most-churned
NON-Python source files — the place the non-Python risk actually concentrates —
without pretending to deep-analyse them. It is deliberately neutral and pure:

  - the canonical ``app.engine.skip_dirs.is_skipped`` predicate is the ONLY skip
    set (no rolled-own exclusions), so it stays consistent with every other walk;
  - LOC is non-blank line count (read locally);
  - churn is git commit count, computed in a SINGLE ``git log`` pass (never one
    subprocess per file), degrading to 0 on any error (non-git dir, timeout, …)
    rather than raising;
  - ranking is deterministic: ``(-churn, -loc, path)`` — same input, same output,
    no time/random anywhere.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.engine.skip_dirs import is_skipped

__all__ = ["FileFact", "scan_polyglot_facts", "render_polyglot_attention"]

# Non-Python source extension -> normalised language name. Mirrors the
# extension/language map ``ProjectProfiler._SCOPE_LANGUAGE_BY_EXT`` uses for the
# scope breakdown, minus the Python entries (those are the IN-scope subset and
# never appear here). An explicit allow-list: only these extensions are treated
# as deep-analysable-elsewhere source worth naming.
_LANGUAGE_BY_EXT: dict[str, str] = {
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C", ".h": "C",
    ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".hpp": "C++", ".hh": "C++",
    ".cs": "C#",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".swift": "Swift",
    ".sh": "Shell", ".bash": "Shell",
    ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "CSS", ".sass": "CSS",
    ".sql": "SQL",
    ".vue": "Vue",
}

# Python is the IN-scope subset Apex already deep-analyses — never named here.
_PYTHON_EXTENSIONS = {".py", ".pyi"}

# Explicit deny set: lockfiles / generated manifests whose extension might map to
# a language but whose CONTENT is machine-written, so naming them as "files worth
# attention" would be noise. Matched on the full lowercased basename.
_DENY_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock",
    "cargo.lock", "gemfile.lock", "poetry.lock",
}


@dataclass(frozen=True)
class FileFact:
    """One non-Python source file Apex can name but not deep-analyse yet."""

    path: str
    language: str
    loc: int
    churn: int


def _non_blank_loc(path: Path) -> int:
    """Non-blank line count. Degrades to 0 on any read error (never raises)."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    return sum(1 for line in text.splitlines() if line.strip())


def _git_churn(root: Path, candidates: set[str]) -> dict[str, int]:
    """Commit count per ``root``-relative path, from a SINGLE ``git log`` pass.

    One ``git log --name-only`` invocation lists every file touched per commit;
    we tally how many commits touch each candidate path. Never one subprocess
    per file. Any failure (non-git dir, missing git, timeout, non-zero exit)
    degrades to an empty mapping — callers then read churn 0 — and never raises.
    """
    if not candidates:
        return {}
    try:
        out = subprocess.run(
            ["git", "log", "--format=", "--name-only"],
            cwd=root, capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return {}
    if out.returncode != 0:
        return {}
    counts: dict[str, int] = {}
    for raw in out.stdout.splitlines():
        rel = raw.strip()
        if rel and rel in candidates:
            counts[rel] = counts.get(rel, 0) + 1
    return counts


def scan_polyglot_facts(root: str, *, limit: int = 5) -> list[FileFact]:
    """The top ``limit`` non-Python source files worth attention, ranked.

    Walk ``root`` (skipping the canonical excluded directories via
    ``is_skipped`` — never a rolled-own skip set), keep every NON-Python source
    file whose extension is in the explicit language allow-list and whose
    basename is not a denied lockfile/manifest, then rank deterministically by
    ``(-churn, -loc, path)`` and return the strongest ``limit``.

    Pure and total: LOC is read locally; churn comes from one git pass that
    degrades to 0 on any error; the result is identical for a given repo state.
    """
    root_path = Path(root)
    if limit <= 0 or not root_path.exists():
        return []

    candidates: list[tuple[str, str, int]] = []  # (rel_posix, language, loc)
    for path in root_path.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root_path)
        if is_skipped(rel):
            continue
        ext = path.suffix.lower()
        if ext in _PYTHON_EXTENSIONS:
            continue
        language = _LANGUAGE_BY_EXT.get(ext)
        if language is None:
            continue
        if path.name.lower() in _DENY_NAMES:
            continue
        candidates.append((rel.as_posix(), language, _non_blank_loc(path)))

    if not candidates:
        return []

    churn_by_path = _git_churn(root_path, {rel for rel, _lang, _loc in candidates})
    facts = [
        FileFact(path=rel, language=language, loc=loc,
                 churn=churn_by_path.get(rel, 0))
        for rel, language, loc in candidates
    ]
    facts.sort(key=lambda f: (-f.churn, -f.loc, f.path))
    return facts[:limit]


def render_polyglot_attention(facts: list[FileFact]) -> str:
    """A short, calm clause naming the out-of-scope files worth attention.

    Empty string when there are none, so callers can append it unconditionally
    and an all-Python repo's output stays byte-identical.
    """
    if not facts:
        return ""
    parts = []
    for fact in facts:
        commit_word = "commit" if fact.churn == 1 else "commits"
        parts.append(f"`{fact.path}` ({fact.loc} LOC, {fact.churn} {commit_word})")
    return (
        "Largest / most-active files outside analysis scope: "
        + ", ".join(parts)
        + " — Apex can't deep-analyse these yet, but they're where the "
        "non-Python risk concentrates."
    )
