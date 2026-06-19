"""Inline technical-debt marker census — TODO/FIXME/HACK/XXX/BUG.

Every codebase carries a back-channel of intent its authors left in plain text:
``# TODO: handle the empty case``, ``# FIXME race here``, ``# HACK works for now``.
Those markers are the cheapest, most honest signal of where the code knows it is
incomplete — but they rot silently, scattered across files and never tallied. This
analyzer sweeps the project's *own* sources and turns that back-channel into a
deterministic ledger: how many markers, of which kind, and exactly where.

Two design choices keep it precise and reproducible:

  - **Comments and strings only.** Markers are detected through ``tokenize``, so a
    ``TODO`` is counted only when it lives in a ``# comment`` or a string literal —
    never when it is (part of) an identifier. ``TODONT`` and ``my_todo_list`` are
    code, not debt notes, and word-boundary, case-sensitive matching leaves them
    alone.
  - **Deterministic by default.** With ``with_age=False`` (the default) there are no
    subprocess calls at all: same tree → same ``TodoDebt``. ``with_age=True`` opts
    into a best-effort ``git blame`` per item to age each marker; on any error or a
    non-git target it simply omits the age and never raises.

Reuses :func:`app.engine.skip_dirs.iter_source_files`, so agent worktrees, caches,
and vendored trees are excluded and the file cap stays reproducible. Stdlib-only.
"""

from __future__ import annotations

import io
import re
import subprocess
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engine.skip_dirs import (
    is_test_or_fixture_path as _is_test_or_fixture,
)
from app.engine.skip_dirs import iter_source_files

__all__ = ["MARKERS", "TodoDebt", "analyze_todo_debt"]

# Recognised debt markers, case-sensitive. Order is the canonical reporting order
# for ``by_marker`` so the output stays stable regardless of discovery order.
MARKERS: tuple[str, ...] = ("TODO", "FIXME", "HACK", "XXX", "BUG")

# Word-boundary, case-sensitive alternation. ``\b`` on both sides means ``TODONT``
# (no boundary after ``TODO``) and ``xBUG`` (no boundary before ``BUG``) never match,
# while ``TODO:`` / ``(FIXME)`` / ``HACK,`` do. Longest-first is irrelevant here since
# no marker is a prefix of another, but the alternation order is fixed for stability.
_MARKER_RE = re.compile(r"\b(" + "|".join(MARKERS) + r")\b")

# Cap on the number of itemised findings returned (the census head, not the count).
_ITEM_CAP = 20

# How many trailing characters of the surrounding line to keep as context.
_TEXT_LIMIT = 120


@dataclass
class TodoDebt:
    """A deterministic census of inline debt markers under one project root.

    ``total`` is the full count of markers found across all scanned files;
    ``by_marker`` maps each known marker to its count (every marker key present,
    zero when absent); ``items`` is the stable, capped head of individual findings,
    each ``{module, line, marker, text}`` (plus ``age_days`` when ``with_age=True``
    and a blame succeeded).
    """

    total: int = 0
    by_marker: dict[str, int] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "by_marker": dict(self.by_marker), "items": list(self.items)}


def _iter_marker_hits(source: str):
    """Yield ``(lineno, marker, text)`` for every marker inside a comment or string.

    Tokenizing restricts matches to COMMENT/STRING tokens, so markers that appear as
    code identifiers are skipped entirely. A token may span several physical lines
    (a triple-quoted string); the match is attributed to the physical line the marker
    text actually falls on, and the reported ``text`` is that line, trimmed.
    """
    lines = source.splitlines()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        token_list = list(tokens)
    except (tokenize.TokenError, IndentationError, SyntaxError, RecursionError, MemoryError):
        return
    for tok in token_list:
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        start_line = tok.start[0]
        for offset, piece in enumerate(tok.string.splitlines() or [tok.string]):
            m = _MARKER_RE.search(piece)
            if m is None:
                continue
            lineno = start_line + offset
            full = lines[lineno - 1] if 0 < lineno <= len(lines) else piece
            yield lineno, m.group(1), full.strip()[:_TEXT_LIMIT]


def _blame_age_days(root: Path, rel: str, line: int) -> int | None:
    """Best-effort days since ``rel:line`` was last touched, anchored to HEAD time.

    Anchoring the "now" to the HEAD commit time (rather than wall-clock) keeps the
    value stable for a given repo state. Any failure — non-git target, deleted line,
    timeout — yields ``None`` and never raises.
    """
    def _git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=15,
        )

    try:
        head = _git("log", "-1", "--format=%ct")
        if head.returncode != 0 or not head.stdout.strip():
            return None
        blame = _git("blame", "-L", f"{line},{line}", "--porcelain", "--", rel)
        if blame.returncode != 0:
            return None
        for text_line in blame.stdout.splitlines():
            if text_line.startswith("committer-time "):
                then = int(text_line.split()[1])
                return max(0, (int(head.stdout.strip()) - then) // 86400)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return None


def analyze_todo_debt(
    root: str | Path, max_files: int = 500, with_age: bool = False,
) -> TodoDebt:
    """Census inline debt markers in the Python sources under ``root``.

    Walks at most ``max_files`` source files (excluding worktrees, caches, and
    vendored trees via the canonical skip set), counting every TODO/FIXME/HACK/XXX/BUG
    that appears in a comment or string literal. The returned ``items`` head is sorted
    deterministically by ``(module, line, marker)`` and capped at ~20.

    With ``with_age=True`` each itemised finding is aged via a best-effort ``git
    blame``; on any failure the ``age_days`` key is simply absent. With the default
    ``with_age=False`` no subprocess is ever spawned, so the result is pure and
    reproducible.
    """
    root = Path(root)
    by_marker: dict[str, int] = {m: 0 for m in MARKERS}
    all_hits: list[tuple[str, int, str, str]] = []
    total = 0

    files = list(iter_source_files(root))[: max(0, max_files)]
    for path in files:
        rel = path.relative_to(root)
        # Exclude test/fixture trees from the project's own debt census.
        if _is_test_or_fixture(rel):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel_str = rel.as_posix()
        for lineno, marker, text in _iter_marker_hits(source):
            total += 1
            by_marker[marker] += 1
            all_hits.append((rel_str, lineno, marker, text))

    # Deterministic order, then take the stable head.
    all_hits.sort(key=lambda h: (h[0], h[1], h[2]))
    items: list[dict[str, Any]] = []
    for rel_str, lineno, marker, text in all_hits[:_ITEM_CAP]:
        item: dict[str, Any] = {
            "module": rel_str, "line": lineno, "marker": marker, "text": text,
        }
        if with_age:
            age = _blame_age_days(root, rel_str, lineno)
            if age is not None:
                item["age_days"] = age
        items.append(item)

    return TodoDebt(total=total, by_marker=by_marker, items=items)
