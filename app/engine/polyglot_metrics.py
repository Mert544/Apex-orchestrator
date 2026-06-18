"""Deterministic, language-agnostic metrics over NON-Python source — make the
"~X% outside analysis scope" remainder visible without pretending to parse it.

Apex deep-analyses Python; on a polyglot repo the TypeScript / JavaScript / YAML
/ HTML / Markdown / shell remainder is structurally outside that scope, so Apex
can't say WHERE the non-Python risk concentrates. ``app.tools.polyglot_facts``
names the biggest / most-churned such files; this module adds the per-file
*shape* signals that make a coarse risk read possible — all from cheap TEXT
heuristics, never a real parse:

  - the canonical ``app.engine.skip_dirs.is_skipped`` predicate is the ONLY skip
    set (no rolled-own exclusions), so worktree copies / caches / build output
    never leak in and this stays consistent with every other walk;
  - every metric is a pure local read: LOC (non-blank lines), a HEURISTIC nesting
    depth (max of brace-balance and leading-indent steps — NOT a parse), a
    word-boundary TODO/FIXME/HACK/XXX count, and the longest physical line;
  - churn, when a git history is available, is the file's commit count from a
    SINGLE bounded ``git log --name-only`` pass (never one subprocess per file),
    reusing the established best-effort pattern (timeout, degrade to 0, sorted);
  - ranking is deterministic everywhere: fixed integer weights, sorted output,
    a stable tiebreak on path — same repo state, same bytes out, no time/random.

The depth/size signals are explicitly HEURISTIC: they are named as such and never
claimed to be syntactic. Best-effort and total: unreadable files are skipped, a
repo with no non-Python source yields empty results, and any git failure degrades
to churn 0 — nothing here raises.

Deterministic, stdlib + git only, offline, no LLM.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from app.engine.skip_dirs import is_skipped

__all__ = [
    "scan_polyglot",
    "polyglot_hotspots",
    "polyglot_summary",
]

# Non-Python source extension -> normalised language name. A deliberately narrow,
# explicit allow-list scoped to the text-heuristic surface this module targets:
# only these extensions are scanned, so unknown / binary / data files are never
# measured. Lowercased keys; ``.suffix.lower()`` is matched against them.
_LANGUAGE_BY_EXT: dict[str, str] = {
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript",
    ".yaml": "YAML", ".yml": "YAML",
    ".html": "HTML",
    ".sh": "Shell",
    ".md": "Markdown",
}

# Language-agnostic technical-debt markers. Word-boundary, case-insensitive, so
# ``TODO`` matches but ``TODOLIST`` does not; works on any text file regardless of
# comment syntax. Precompiled and deterministic — no time/random.
_DEBT_MARKER_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)

# Sanity caps so a pathological generated/minified file can't report absurd
# numbers (and so the score stays bounded). Deterministic constants.
_DEBT_CAP = 9999
_LONGEST_LINE_CAP = 99999
_DEPTH_CAP = 999

# Indent step in spaces for the leading-indent depth heuristic. A tab counts as
# one step regardless of width. Fixed, so the reading is reproducible.
_INDENT_STEP = 2

# Coarse size bands by LOC. Lower bound is inclusive; the first band whose bound
# the LOC meets (scanned small->large) names the file. Fixed thresholds.
_SIZE_BANDS: tuple[tuple[int, str], ...] = (
    (0, "tiny"),
    (50, "small"),
    (200, "medium"),
    (500, "large"),
    (1000, "huge"),
)

# Deterministic hotspot scoring weights (fixed integers, no time/random). The
# score rewards a file for being big, deeply nested, debt-marked and actively
# churned: ``loc//50 + depth*3 + todos*2 + churn*4``. Churn is weighted highest
# because an actively-changing large file is the live risk; depth and debt are
# structural tie-shapers on top of raw size.
_W_LOC_PER = 50      # one point per 50 LOC
_W_DEPTH = 3
_W_TODOS = 2
_W_CHURN = 4

# How far back the single churn pass reads. Bounded so the subprocess stays fast
# and the result is stable for a given repo state.
_COMMIT_WINDOW = 1000


def _classify(name: str) -> str | None:
    """The normalised language for a basename, or ``None`` if not in scope.

    Pure name check on the lowercased suffix against the explicit allow-list — no
    I/O. ``app.ts`` -> ``"TypeScript"``; ``app.py`` / ``logo.png`` -> ``None``.
    """
    return _LANGUAGE_BY_EXT.get(Path(name).suffix.lower())


def _brace_depth(text: str) -> int:
    """Max running nesting depth from bracket balance — a HEURISTIC, not a parse.

    Tracks ``(`` ``[`` ``{`` as +1 and their closers as -1 over the whole text,
    reporting the high-water mark (never below 0, so stray closers don't drive it
    negative). Strings / comments are NOT understood — this is intentionally a
    cheap text signal. Pure.
    """
    depth = 0
    peak = 0
    for ch in text:
        if ch in "([{":
            depth += 1
            if depth > peak:
                peak = depth
        elif ch in ")]}":
            if depth > 0:
                depth -= 1
    return min(peak, _DEPTH_CAP)


def _indent_step(line: str) -> int:
    """Leading-indent depth of one line in steps (tabs=1 step each, else spaces).

    A tab-indented line counts one step per leading tab; a space-indented line
    counts ``leading_spaces // _INDENT_STEP``. Mixed leads count whichever
    character starts the line. Pure; blank/all-indent lines handled by caller.
    """
    stripped = line.lstrip(" \t")
    lead = line[: len(line) - len(stripped)]
    if not lead:
        return 0
    if lead[0] == "\t":
        return lead.count("\t")
    return len(lead) // _INDENT_STEP


def _indent_depth(lines: list[str]) -> int:
    """Max leading-indent depth across non-blank lines — a HEURISTIC, not a parse.

    Complements brace depth so brace-free, indent-structured languages (YAML,
    Markdown, shell here-bodies) still report nesting. Pure.
    """
    peak = 0
    for line in lines:
        if not line.strip():
            continue
        step = _indent_step(line)
        if step > peak:
            peak = step
    return min(peak, _DEPTH_CAP)


def _size_band(loc: int) -> str:
    """The coarse size band for a LOC count (see ``_SIZE_BANDS``). Pure."""
    band = _SIZE_BANDS[0][1]
    for bound, name in _SIZE_BANDS:
        if loc >= bound:
            band = name
        else:
            break
    return band


def _read_metrics(path: Path) -> dict | None:
    """All per-file text metrics from a SINGLE local read, or ``None`` if unread.

    Returns ``{loc, depth, todos, longest_line, size_band}`` where ``depth`` is
    ``max(brace_depth, indent_depth)`` — the stronger of the two HEURISTIC nesting
    signals — ``loc`` is the non-blank line count, ``todos`` is the capped debt
    count, and ``longest_line`` is the longest physical line length (capped).
    Returns ``None`` on any read error so the caller can skip the file (never
    raises). Pure aside from the one read.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    lines = text.splitlines()
    loc = sum(1 for line in lines if line.strip())
    todos = min(len(_DEBT_MARKER_RE.findall(text)), _DEBT_CAP)
    longest = min(max((len(line) for line in lines), default=0), _LONGEST_LINE_CAP)
    depth = max(_brace_depth(text), _indent_depth(lines))
    return {
        "loc": loc,
        "depth": depth,
        "todos": todos,
        "longest_line": longest,
        "size_band": _size_band(loc),
    }


def _churn_map(root_path: Path) -> dict[str, int]:
    """Commit count per root-relative path from ONE bounded ``git log`` pass.

    Reuses the established best-effort git pattern: a single
    ``git log --name-only`` invocation (never one subprocess per file), bounded to
    ``_COMMIT_WINDOW`` commits and a 15s timeout. Any failure (non-git dir,
    missing git, timeout, non-zero exit) degrades to an empty map — callers read
    churn 0 — and never raises. Deterministic: counts only, no time/random.
    """
    try:
        out = subprocess.run(
            ["git", "log", "--format=", "--name-only", "-n", str(_COMMIT_WINDOW)],
            cwd=root_path, capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return {}
    if out.returncode != 0:
        return {}
    counts: dict[str, int] = {}
    for raw in out.stdout.splitlines():
        rel = raw.strip()
        if rel:
            counts[rel] = counts.get(rel, 0) + 1
    return counts


def _iter_candidates(root_path: Path) -> list[tuple[str, str]]:
    """Every in-scope non-Python source file as ``(rel_posix, language)``, sorted.

    Walks ``root`` once, keeping files whose extension is in the allow-list and
    whose path crosses no excluded directory (``is_skipped``). Sorted by path so a
    downstream cap is reproducible. Pure aside from the directory walk.
    """
    found: list[tuple[str, str]] = []
    for path in root_path.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root_path)
        if is_skipped(rel):
            continue
        language = _classify(path.name)
        if language is None:
            continue
        found.append((rel.as_posix(), language))
    found.sort()
    return found


def scan_polyglot(root: str, max_files: int = 200) -> list[dict]:
    """Per-file text metrics for every in-scope non-Python source file under ``root``.

    For each ``.ts/.tsx/.js/.jsx/.yaml/.yml/.html/.sh/.md`` file (skipping the
    canonical excluded directories via ``is_skipped``), compute cheap deterministic
    metrics from a single local read: ``loc`` (non-blank lines), ``depth`` (the
    stronger of the brace-balance and leading-indent HEURISTICS — NOT a parse),
    ``todos`` (word-boundary TODO/FIXME/HACK/XXX count), ``longest_line``, and a
    coarse ``size_band``.

    Each result dict is ``{path, language, loc, depth, todos, longest_line,
    size_band}``. The walk is bounded: at most ``max_files`` files (the smallest
    paths first, since candidates are path-sorted before the cap) are measured.
    Results are returned sorted by ``(-loc, path)`` — biggest first, ties broken
    by path — so the output is deterministic for a given repo state.

    Pure and total: unreadable files are skipped; ``max_files <= 0`` or a missing
    root yields ``[]``; no source files yields ``[]``. Never raises.
    """
    root_path = Path(root)
    if max_files <= 0 or not root_path.exists():
        return []
    candidates = _iter_candidates(root_path)[:max_files]
    rows: list[dict] = []
    for rel, language in candidates:
        metrics = _read_metrics(root_path / rel)
        if metrics is None:
            continue
        rows.append({"path": rel, "language": language, **metrics})
    rows.sort(key=lambda row: (-row["loc"], row["path"]))
    return rows


def _hotspot_score(loc: int, depth: int, todos: int, churn: int) -> int:
    """The deterministic attention score: fixed integer weights, no time/random.

    ``loc//_W_LOC_PER + depth*_W_DEPTH + todos*_W_TODOS + churn*_W_CHURN`` — big,
    deeply-nested, debt-marked and actively-churned files score highest. Pure.
    """
    return (
        loc // _W_LOC_PER
        + depth * _W_DEPTH
        + todos * _W_TODOS
        + churn * _W_CHURN
    )


def _why(loc: int, depth: int, todos: int, churn: int) -> str:
    """A short, factual reason string naming the signals that drove the score.

    Lists only the signals that are actually present, in a fixed order, so the
    text is deterministic and never over-claims. Pure.
    """
    parts: list[str] = [f"{loc} LOC"]
    if churn:
        parts.append(f"{churn} commits")
    if depth:
        parts.append(f"nesting depth {depth} (heuristic)")
    if todos:
        parts.append(f"{todos} TODO/FIXME")
    return ", ".join(parts)


def polyglot_hotspots(root: str, top: int = 5) -> list[dict]:
    """The ``top`` non-Python source files most worth attention, ranked.

    Builds on :func:`scan_polyglot` (so the same files / metrics / skip rules
    apply), adds git churn from ONE bounded ``git log`` pass (degrading to 0 on any
    error), and scores each file deterministically via :func:`_hotspot_score`
    (``loc//50 + depth*3 + todos*2 + churn*4``). Each result is
    ``{path, loc, depth, todos, churn, score, why}``.

    Ranked by ``(-score, -loc, path)`` — highest score first, ties broken by size
    then path — and capped to ``top``. Deterministic: fixed weights, sorted
    output, no time/random.

    Pure and total: ``top <= 0`` or no source files yields ``[]``; a non-git repo
    simply gives every file churn 0. Never raises.
    """
    if top <= 0:
        return []
    rows = scan_polyglot(root)
    if not rows:
        return []
    churn = _churn_map(Path(root))
    hotspots: list[dict] = []
    for row in rows:
        path = row["path"]
        c = churn.get(path, 0)
        score = _hotspot_score(row["loc"], row["depth"], row["todos"], c)
        hotspots.append({
            "path": path,
            "loc": row["loc"],
            "depth": row["depth"],
            "todos": row["todos"],
            "churn": c,
            "score": score,
            "why": _why(row["loc"], row["depth"], row["todos"], c),
        })
    hotspots.sort(key=lambda h: (-h["score"], -h["loc"], h["path"]))
    return hotspots[:top]


def polyglot_summary(root: str, top: int = 5) -> dict:
    """The non-Python risk-surface view: per-language totals plus top hotspots.

    Returns ``{languages, totals, hotspots}`` where:

      - ``languages`` is a list of ``{language, files, loc}`` per in-scope language,
        sorted by ``(-loc, language)`` — the biggest non-Python surface first;
      - ``totals`` is ``{files, loc}`` across all in-scope non-Python source;
      - ``hotspots`` is :func:`polyglot_hotspots` (the ``top`` files worth
        attention).

    This is the concrete "what is the non-Python risk surface" answer the
    Python-only analysis structurally can't produce. Deterministic and total: no
    source files yields ``{languages: [], totals: {files: 0, loc: 0}, hotspots:
    []}``; never raises.
    """
    rows = scan_polyglot(root)
    per_lang: dict[str, dict[str, int]] = {}
    total_loc = 0
    for row in rows:
        lang = row["language"]
        bucket = per_lang.setdefault(lang, {"files": 0, "loc": 0})
        bucket["files"] += 1
        bucket["loc"] += row["loc"]
        total_loc += row["loc"]
    languages = [
        {"language": lang, "files": data["files"], "loc": data["loc"]}
        for lang, data in per_lang.items()
    ]
    languages.sort(key=lambda entry: (-entry["loc"], entry["language"]))
    return {
        "languages": languages,
        "totals": {"files": len(rows), "loc": total_loc},
        "hotspots": polyglot_hotspots(root, top=top),
    }
