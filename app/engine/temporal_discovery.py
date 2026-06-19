"""Temporal / evolutionary discovery — how code patterns EMERGE and SPREAD over
a project's git history.

Apex's other git analyzers (``cross_language_coupling``, ``blast_radius``) read a
SNAPSHOT of co-change: which files move together across the whole window. This
module adds the missing *time axis*. The same bounded ``git log --name-only`` pass
is read into a per-commit list and the two ends of the window are compared, so the
questions it answers are about CHANGE OVER TIME:

  - ``file_evolution`` — per-file change frequency plus the co-change groups that
    have formed: files that keep changing TOGETHER, an emergent coupling that
    accretes over the window.
  - ``emerging_hotspots`` — files whose change-rate is ACCELERATING: a pattern that
    is SPREADING, not just present. Each carries a ``trend`` of ``accelerating`` /
    ``stable`` / ``cooling``.
  - ``spreading_pairs`` — co-change pairs whose coupling STRENGTHENED across the
    window: seams that are tightening.

Acceleration signal — half-split by default, opt-in TIME-DECAY.
---------------------------------------------------------------
By default ``emerging_hotspots`` / ``spreading_pairs`` split the window into an
OLDER half and a RECENT half (newest-first) and compare raw counts — the original,
unchanged behaviour, so existing callers and idea sets never shift.

That hard boundary is sensitive to data SHAPE: a file whose changes all fall
inside one contiguous burst, or that sits right on the median commit, can read as
"stable" even though its activity is plainly clustered toward the recent end —
real acceleration the split misses (flagged by an intelligence red-team). Passing
``decay=True`` opts into a TIME-DECAY signal that fixes this: every commit's
contribution is weighted by its ORDER in the newest-first log (NOT wall-clock
time, so the verdict stays deterministic and offline): the newest commit weighs
``_DECAY_BASE**0 == 1``, the next ``_DECAY_BASE**1``, and so on (see
``_decay_weights``). A subject's acceleration is its weighted activity MINUS the
weighted activity an evenly-spread subject with the same number of changes would
earn (``_acceleration``); recent-clustered > 0, evenly-spread ~= 0, old-clustered
< 0. There is no median boundary to straddle, so a bursty/contiguous history is
scored on the same smooth curve as any other. The raw recent/older half counts
are still REPORTED for continuity, plus a rounded ``accel`` field.

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

# Time-decay constant. Each commit's contribution to "recent activity" is scaled
# by ``_DECAY_BASE ** position`` where ``position`` is the commit's 0-based index
# in the NEWEST-FIRST log (0 == newest). 0.9 gives the newest commit ~2.6x the
# weight of one 10 commits back and decays smoothly to ~0 over the window, so a
# file is judged on WHERE in the sequence its changes fall, with no hard boundary
# to straddle. Fixed (no wall-clock, no random) => deterministic and offline.
_DECAY_BASE = 0.9

# Acceleration verdicts use a small epsilon so floating-point dust around an
# evenly-spread file (acceleration ~= 0) reads as "stable" rather than flapping
# between accelerating/cooling. Fixed => deterministic.
_ACCEL_EPSILON = 1e-9


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


def _decay_weights(n: int) -> list[float]:
    """Recency weight for each of ``n`` newest-first commits.

    Commit ``i`` (``i == 0`` is the newest) earns ``_DECAY_BASE ** i``, so weight
    falls off smoothly from 1.0 at the recent end toward 0 at the old end. Returns
    ``[]`` for ``n <= 0``. Pure and fixed-constant => deterministic.
    """
    return [_DECAY_BASE ** i for i in range(max(n, 0))]


def _weighted_activity(
    commits: list[list[str]], weights: list[float],
) -> dict[str, float]:
    """Sum each file's recency weights across ``commits`` (newest-first).

    ``commits[i]`` is paired with ``weights[i]``; a file that changes in a recent
    commit accrues more than the same change made long ago. Pure.
    """
    activity: dict[str, float] = {}
    for files, w in zip(commits, weights):
        for rel in files:
            activity[rel] = activity.get(rel, 0.0) + w
    return activity


def _weighted_pair_activity(
    commits: list[list[str]], weights: list[float],
) -> dict[tuple[str, str], float]:
    """Sum each co-change pair's recency weights across ``commits`` (newest-first).

    Each commit's files are pre-sorted, so every ``combinations`` pair is canonical
    ``(a, b)`` with ``a < b``. Pure.
    """
    activity: dict[tuple[str, str], float] = {}
    for files, w in zip(commits, weights):
        for pair in combinations(files, 2):
            activity[pair] = activity.get(pair, 0.0) + w
    return activity


def _acceleration(weighted: float, count: int, mean_weight: float) -> float:
    """How much a subject's recency-weighted activity beats an even baseline.

    ``count`` changes spread EVENLY across the window would earn
    ``count * mean_weight`` (the mean per-commit weight). The excess over that
    baseline is the acceleration: > 0 when changes cluster RECENT, ~= 0 when
    evenly spread, < 0 when clustered OLD. Independent of any median boundary, so
    a contiguous burst is scored on the same smooth curve. Pure.
    """
    return weighted - count * mean_weight


def _accel_trend(accel: float) -> str:
    """Classify an acceleration value into accelerating / stable / cooling.

    A strictly positive excess (beyond ``_ACCEL_EPSILON`` float dust) is
    accelerating, strictly negative is cooling, and the even-spread neighbourhood
    is stable. Pure, fixed-epsilon => deterministic.
    """
    if accel > _ACCEL_EPSILON:
        return _TREND_ACCELERATING
    if accel < -_ACCEL_EPSILON:
        return _TREND_COOLING
    return _TREND_STABLE


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


def emerging_hotspots(root: str, decay: bool = False) -> list[dict]:
    """Files whose change-rate is ACCELERATING across the window.

    Two signals, selected by ``decay`` (default OFF so existing callers and idea
    sets never shift):

    * ``decay=False`` — the historical HARD HALF-SPLIT. The window is split into a
      RECENT half and an OLDER half (newest-first); a file accelerates iff its
      recent change count strictly exceeds its older count. Each entry is
      ``{"module", "recent", "older", "trend": "accelerating"}``, sorted by
      ``(-(recent - older), -recent, module)``.

    * ``decay=True`` — the TIME-DECAY signal that is robust to bursty / contiguous
      histories (the data-shape case the hard split missed). Each commit is
      weighted by its RECENCY (its order in the newest-first log; see
      ``_decay_weights``). A file's ``accel`` is its recency-weighted activity
      minus the activity an evenly-spread file with the same change count would
      earn (``_acceleration``): positive when its changes cluster toward the RECENT
      end, ~= 0 when evenly spread, negative when clustered old. There is no median
      boundary to straddle, so a file whose changes sit inside one contiguous burst
      near the recent end is still seen as accelerating even when its raw
      recent/older halves tie. Each entry adds an ``accel`` field and rows sort by
      ``(-accel, -recent, module)``. ``recent``/``older`` are still the raw
      half-split counts (reported for continuity).

    Pure and total: a non-git / one-commit / shallow repo (no two halves to
    compare) degrades to ``[]`` and never raises; deterministic for a repo state.
    """
    commits = _load_commits(root)
    if not commits:
        return []

    if not decay:
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

    if len(commits) < 2:
        return []
    weights = _decay_weights(len(commits))
    mean_weight = sum(weights) / len(commits)
    weighted = _weighted_activity(commits, weights)
    counts = _count_files(commits)
    recent_half, older_half = _split_halves(commits)
    recent_counts = _count_files(recent_half)
    older_counts = _count_files(older_half)

    decay_rows: list[dict] = []
    for mod, w in weighted.items():
        accel = _acceleration(w, counts[mod], mean_weight)
        if _accel_trend(accel) == _TREND_ACCELERATING:
            decay_rows.append({
                "module": mod,
                "recent": recent_counts.get(mod, 0),
                "older": older_counts.get(mod, 0),
                "accel": round(accel, 6),
                "trend": _TREND_ACCELERATING,
            })
    decay_rows.sort(key=lambda row: (-row["accel"], -row["recent"], row["module"]))
    return decay_rows


def spreading_pairs(root: str, top: int = 5, decay: bool = False) -> list[dict]:
    """Co-change pairs whose coupling STRENGTHENED across the window.

    Two signals, selected by ``decay`` (default OFF so existing callers and idea
    sets never shift):

    * ``decay=False`` — the historical HARD HALF-SPLIT. The window is split into
      recent / older halves (newest-first); a pair is kept iff it co-changed more
      recently than before (``recent > older``) AND clears ``_MIN_COCHANGES``
      total. Each entry is ``{"a", "b", "recent", "older", "cochanges",
      "trend": "accelerating"}``, sorted by ``(-(recent - older), -cochanges, a,
      b)`` and capped at ``top``.

    * ``decay=True`` — the TIME-DECAY signal. Each commit is weighted by its
      RECENCY (see ``_decay_weights``); a pair's ``accel`` is its recency-weighted
      co-change activity minus the activity an evenly-spread pair with the same
      total would earn (``_acceleration``): positive when its co-changes cluster
      toward the RECENT end. Pairs that are accelerating AND clear ``_MIN_COCHANGES``
      total are kept. No median boundary, so a seam tightening inside one
      contiguous burst still surfaces. Each entry adds an ``accel`` field and rows
      sort by ``(-accel, -cochanges, a, b)``, capped at ``top``.

    Pure and total: a non-git / one-commit / shallow repo degrades to ``[]`` and
    never raises; deterministic for a given repo state.
    """
    if top <= 0:
        return []
    commits = _load_commits(root)
    if not commits:
        return []

    if not decay:
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

    if len(commits) < 2:
        return []
    weights = _decay_weights(len(commits))
    mean_weight = sum(weights) / len(commits)
    weighted = _weighted_pair_activity(commits, weights)
    counts = _count_pairs(commits)
    recent_half, older_half = _split_halves(commits)
    recent_counts = _count_pairs(recent_half)
    older_counts = _count_pairs(older_half)

    decay_rows: list[dict] = []
    for pair, w in weighted.items():
        total = counts[pair]
        accel = _acceleration(w, total, mean_weight)
        if _accel_trend(accel) == _TREND_ACCELERATING and total >= _MIN_COCHANGES:
            decay_rows.append({
                "a": pair[0], "b": pair[1],
                "recent": recent_counts.get(pair, 0),
                "older": older_counts.get(pair, 0),
                "cochanges": total,
                "accel": round(accel, 6),
                "trend": _TREND_ACCELERATING,
            })
    decay_rows.sort(key=lambda row: (-row["accel"], -row["cochanges"],
                                     row["a"], row["b"]))
    return decay_rows[:top]
