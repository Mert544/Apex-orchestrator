"""Temporal / evolutionary discovery — how code patterns EMERGE and SPREAD over
a project's git history.

Apex's other git analyzers (``cross_language_coupling``, ``blast_radius``) read a
SNAPSHOT of co-change: which files move together across the whole window. This
module adds the missing *time axis*. The same bounded ``git log --name-only`` pass
is split into an OLDER half and a RECENT half of the commit window, and the two
halves are compared, so the questions it answers are about CHANGE OVER TIME:

  - ``file_evolution`` — per-file change frequency plus the co-change groups that
    have formed: files that keep changing TOGETHER, an emergent coupling that
    accretes over the window.
  - ``emerging_hotspots`` — files whose change-rate is ACCELERATING: more changes
    in the recent half than the older half. A pattern that is SPREADING, not just
    present. Each carries a ``trend`` of ``accelerating`` / ``stable`` / ``cooling``.
  - ``spreading_pairs`` — co-change pairs whose coupling STRENGTHENED across the
    window (more co-changes recently than before): seams that are tightening.

Established discipline (matching the sibling git analyzers):

  - ONE bounded ``git log`` subprocess with a timeout — never one call per file;
  - the window is capped (``_COMMIT_WINDOW``) so a fixed repo state gives a fixed,
    fast result; mega-commits (> ``_MAX_COMMIT_FILES`` files, e.g. a sweeping
    reformat or a vendored-tree import) are ignored so the signal stays about
    genuinely co-evolving files;
  - the canonical ``app.engine.skip_dirs.is_skipped`` predicate is the ONLY skip
    set, so worktree copies / caches / build output never leak in;
  - every result is deterministically sorted; the only nondeterminism is the real
    repo state. Any git failure (non-git dir, missing git, shallow/one-commit,
    timeout, non-zero exit) degrades to an empty result and NEVER raises.

Deterministic, stdlib + git only, offline, no LLM.
"""

from __future__ import annotations

import subprocess
from itertools import combinations
from pathlib import Path

from app.engine.skip_dirs import is_skipped

__all__ = [
    "file_evolution",
    "emerging_hotspots",
    "spreading_pairs",
]

# How far back to read. Bounded so the single subprocess stays fast and the
# result is stable for a given repo state.
_COMMIT_WINDOW = 1000

# A sweeping reformat / vendored-tree commit couples everything and means nothing;
# excluding huge commits keeps every signal about genuinely co-evolving files.
_MAX_COMMIT_FILES = 50

# Co-change groups / pairs need at least this many supporting commits to count, so
# a single incidental commit never manufactures an "emergent" coupling.
_MIN_COCHANGES = 2

# Source-source pairs only: the source extensions co-change is meaningful for.
_SOURCE_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
    ".rb", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".kt", ".swift",
}

_TREND_ACCELERATING = "accelerating"
_TREND_STABLE = "stable"
_TREND_COOLING = "cooling"


def _read_git_log(root_path: Path) -> str | None:
    """Run the single ``git log --name-only`` pass, returning stdout or ``None``.

    Total: any git failure (missing git, timeout, non-zero exit) returns ``None``
    rather than raising. Pure aside from the one bounded subprocess.
    """
    try:
        out = subprocess.run(
            ["git", "log", "--format=@commit@%H", "--name-only",
             "-n", str(_COMMIT_WINDOW)],
            cwd=root_path, capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return out.stdout


def _load_commits(root: str, max_commits: int = _COMMIT_WINDOW) -> list[list[str]] | None:
    """The bounded, parsed commit list for ``root`` — or ``None`` when unreadable.

    The single read+parse path every public function shares: validate the root,
    run the one ``git log`` pass, parse it into newest-first per-commit source-file
    lists, and truncate to ``max_commits``. Returns ``None`` (not ``[]``) for a
    non-git / missing / failed read so callers can distinguish "no repo" from "no
    qualifying commits" if they ever need to. Total: never raises.
    """
    if max_commits <= 0:
        return None
    root_path = Path(root)
    if not root_path.exists():
        return None
    stdout = _read_git_log(root_path)
    if stdout is None:
        return None
    return _parse_commits(stdout)[:max_commits]


def _is_source(rel: str) -> bool:
    """True for a recognised source file that survives the canonical skip set.

    Pure name check only — no I/O.
    """
    if is_skipped(rel):
        return False
    return Path(rel).suffix.lower() in _SOURCE_EXTENSIONS


def _parse_commits(stdout: str) -> list[list[str]]:
    """Group ``git log`` output into one sorted list of source paths per commit.

    A "@commit@<sha>" marker opens each commit; later non-empty lines are its
    changed paths (non-source / skipped paths dropped). The returned commit order
    is git's own newest-first order. Mega-commits (> ``_MAX_COMMIT_FILES`` source
    files) and commits with no surviving source file are dropped; single-file
    commits are KEPT (they count toward change frequency, and simply contribute no
    co-change pair). Pure.
    """
    commits: list[list[str]] = []
    current: list[str] = []
    started = False

    def _flush() -> None:
        if started and 1 <= len(current) <= _MAX_COMMIT_FILES:
            commits.append(sorted(current))

    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith("@commit@"):
            _flush()
            current, started = [], True
        elif line and _is_source(line):
            current.append(line)
    _flush()
    return commits


def _split_halves(commits: list[list[str]]) -> tuple[list[list[str]], list[list[str]]]:
    """Split newest-first commits into ``(recent, older)`` halves.

    Commits come newest-first, so the first half is RECENT and the second is
    OLDER. An odd count gives the recent half the extra commit (its ``trend``
    threshold still requires a STRICT majority, so this never fabricates a trend).
    Pure.
    """
    half = len(commits) // 2
    recent = commits[:half] if half else []
    older = commits[half:] if half else []
    return recent, older


def _count_files(commits: list[list[str]]) -> dict[str, int]:
    """Per-file change count across ``commits`` (how many commits touched it). Pure."""
    counts: dict[str, int] = {}
    for files in commits:
        for rel in files:
            counts[rel] = counts.get(rel, 0) + 1
    return counts


def _count_pairs(commits: list[list[str]]) -> dict[tuple[str, str], int]:
    """Per-pair co-change count across ``commits``.

    Each commit's files are already sorted, so every ``combinations`` pair is in
    canonical ``(a, b)`` order with ``a < b``. Pure.
    """
    pairs: dict[tuple[str, str], int] = {}
    for files in commits:
        for pair in combinations(files, 2):
            pairs[pair] = pairs.get(pair, 0) + 1
    return pairs


def _trend(recent: int, older: int) -> str:
    """Classify a recent-vs-older count into accelerating / stable / cooling.

    Strict majority either way decides direction; an exact tie is ``stable``. Pure
    and fixed-threshold, so the verdict is deterministic. Pure.
    """
    if recent > older:
        return _TREND_ACCELERATING
    if recent < older:
        return _TREND_COOLING
    return _TREND_STABLE


def file_evolution(root: str, max_commits: int = _COMMIT_WINDOW) -> dict:
    """Per-file change frequency and the emergent co-change groups in git history.

    ONE ``git log --name-only`` pass (bounded to ``max_commits``, capped at
    ``_COMMIT_WINDOW``) groups each commit's changed source files. Returns::

        {
          "commits": <int commits analysed>,
          "frequency": [{"module": str, "changes": int}, ...],   # sorted
          "cochange_groups": [{"a": str, "b": str, "cochanges": int}, ...],
        }

    ``frequency`` is sorted by ``(-changes, module)``; ``cochange_groups`` lists
    pairs with ``cochanges >= _MIN_COCHANGES``, sorted by ``(-cochanges, a, b)``.

    Pure and total: any git failure / non-git dir / shallow repo degrades to an
    empty (but well-formed) dict and never raises; identical for a given repo state.
    """
    empty = {"commits": 0, "frequency": [], "cochange_groups": []}
    commits = _load_commits(root, max_commits)
    if not commits:
        return empty

    freq = _count_files(commits)
    frequency = sorted(
        ({"module": mod, "changes": n} for mod, n in freq.items()),
        key=lambda row: (-row["changes"], row["module"]),
    )

    pairs = _count_pairs(commits)
    groups = sorted(
        ({"a": a, "b": b, "cochanges": n}
         for (a, b), n in pairs.items() if n >= _MIN_COCHANGES),
        key=lambda row: (-row["cochanges"], row["a"], row["b"]),
    )

    return {
        "commits": len(commits),
        "frequency": frequency,
        "cochange_groups": groups,
    }


def emerging_hotspots(root: str) -> list[dict]:
    """Files whose change-rate is ACCELERATING across the window.

    The commit window is split into a RECENT half and an OLDER half (newest-first).
    For each file we compare its change count in each half::

        recent > older  -> "accelerating"   (spreading)
        recent == older -> "stable"
        recent < older  -> "cooling"

    Only files that ARE accelerating are returned — patterns that are spreading,
    not merely present. Each entry is
    ``{"module", "recent", "older", "trend": "accelerating"}``, sorted by
    ``(-(recent - older), -recent, module)`` so the fastest-spreading file leads.

    Pure and total: a non-git / one-commit / shallow repo (no two halves to
    compare) degrades to ``[]`` and never raises; deterministic for a repo state.
    """
    commits = _load_commits(root)
    if not commits:
        return []
    recent_commits, older_commits = _split_halves(commits)
    if not recent_commits or not older_commits:
        return []

    recent = _count_files(recent_commits)
    older = _count_files(older_commits)

    rows: list[dict] = []
    for mod in recent:
        r = recent[mod]
        o = older.get(mod, 0)
        if _trend(r, o) == _TREND_ACCELERATING:
            rows.append({"module": mod, "recent": r, "older": o,
                         "trend": _TREND_ACCELERATING})

    rows.sort(key=lambda row: (-(row["recent"] - row["older"]),
                               -row["recent"], row["module"]))
    return rows


def spreading_pairs(root: str, top: int = 5) -> list[dict]:
    """Co-change pairs whose coupling STRENGTHENED across the window.

    The window is split into recent / older halves (newest-first). For each pair
    that co-changes anywhere we compare its co-change count in each half and keep
    only pairs that strengthened (more co-changes recently than before) AND clear
    ``_MIN_COCHANGES`` overall — emergent seams that are tightening over time.

    Each entry is ``{"a", "b", "recent", "older", "cochanges",
    "trend": "accelerating"}``, sorted by ``(-(recent - older), -cochanges, a, b)``
    and capped at ``top``.

    Pure and total: a non-git / one-commit / shallow repo degrades to ``[]`` and
    never raises; deterministic for a given repo state.
    """
    if top <= 0:
        return []
    commits = _load_commits(root)
    if not commits:
        return []
    recent_commits, older_commits = _split_halves(commits)
    if not recent_commits or not older_commits:
        return []

    recent = _count_pairs(recent_commits)
    older = _count_pairs(older_commits)

    rows: list[dict] = []
    for pair, r in recent.items():
        o = older.get(pair, 0)
        total = r + o
        if r > o and total >= _MIN_COCHANGES:
            rows.append({"a": pair[0], "b": pair[1], "recent": r, "older": o,
                         "cochanges": total, "trend": _TREND_ACCELERATING})

    rows.sort(key=lambda row: (-(row["recent"] - row["older"]),
                               -row["cochanges"], row["a"], row["b"]))
    return rows[:top]
