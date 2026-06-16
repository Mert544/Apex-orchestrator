"""Characterization pin for ``plan_near_dup_extract``.

This locks the WHOLE serialized plan (ok flag, helper name, blockers,
edits-by-file, and every byte of ``new_contents``/``originals``) for a battery
of representative inputs — one clean param-helper extraction and the blocker
shapes. It exists so the consolidation refactor that split the monolithic
``plan_near_dup_extract`` into cohesive private helpers can be proven to produce
BYTE-IDENTICAL plans: change any logic, threshold, or ordering and the pinned
text below diverges. Determinism is also asserted (re-running on the same input
yields the identical serialization).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.near_dup import NearDuplicateGroup, find_near_duplicates
from app.execution.near_dup_extract import plan_near_dup_extract


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _serialize_plan(plan) -> str:
    """A total, stable rendering of every field a consumer reads off a plan."""
    parts = [
        f"ok={plan.ok}",
        f"old={plan.old!r}",
        f"new={plan.new!r}",
        f"defined_in={getattr(plan, 'defined_in', None)!r}",
        f"blockers={list(plan.blockers)!r}",
        f"edits_by_file={dict(sorted((plan.edits_by_file or {}).items()))!r}",
    ]
    for rel in sorted(plan.new_contents or {}):
        parts.append(f"--- new_contents[{rel}] ---")
        parts.append((plan.new_contents or {})[rel])
    for rel in sorted(getattr(plan, "originals", {}) or {}):
        parts.append(f"--- originals[{rel}] ---")
        parts.append((getattr(plan, "originals", {}) or {})[rel])
    return "\n".join(parts)


_A = (
    "def alpha(n):\n    a = n + 1\n    b = a * 2\n"
    "    c = b + 3\n    d = c + 10\n    return d\n"
)
_B = (
    "def beta(n):\n    a = n + 1\n    b = a * 2\n"
    "    c = b + 3\n    d = c + 20\n    return d\n"
)


def _only_group(root: Path) -> NearDuplicateGroup:
    groups = find_near_duplicates(root, min_statements=5, min_occurrences=2)
    assert len(groups) == 1, f"expected one group, got {groups}"
    return groups[0]


_CLEAN_GOLDEN = """\
ok=True
old='near_dup'
new='_shared_1'
defined_in='pkg/a.py'
blockers=[]
edits_by_file={'pkg/a.py': 1, 'pkg/b.py': 2}
--- new_contents[pkg/a.py] ---
def _shared_1(n, p0):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + p0
    return d


def alpha(n):
    return _shared_1(n, 10)

--- new_contents[pkg/b.py] ---
from pkg.a import _shared_1
def beta(n):
    return _shared_1(n, 20)

--- originals[pkg/a.py] ---
def alpha(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 10
    return d

--- originals[pkg/b.py] ---
def beta(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 20
    return d
"""


def test_clean_param_helper_plan_byte_identical(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/a.py", _A)
    _write(tmp_path, "pkg/b.py", _B)

    plan = plan_near_dup_extract(tmp_path, _only_group(tmp_path))
    assert _serialize_plan(plan) == _CLEAN_GOLDEN


def test_clean_plan_is_deterministic(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/a.py", _A)
    _write(tmp_path, "pkg/b.py", _B)

    group = _only_group(tmp_path)
    first = _serialize_plan(plan_near_dup_extract(tmp_path, group))
    second = _serialize_plan(plan_near_dup_extract(tmp_path, group))
    assert first == second == _CLEAN_GOLDEN


def _base_group(tmp_path: Path) -> NearDuplicateGroup:
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/a.py", _A)
    _write(tmp_path, "pkg/b.py", _B)
    return _only_group(tmp_path)


def test_blocker_shapes_pin_exact_messages(tmp_path: Path) -> None:
    """Every malformed/empty group blocks with empty ``new_contents`` and the
    EXACT pinned message — the refactor must not reorder or reword a gate."""
    g = _base_group(tmp_path)

    cases = {
        "empty": (
            NearDuplicateGroup(occurrences=[], lines=0, diff_count=0,
                               differences=[]),
            "a shared helper needs at least two occurrences",
        ),
        "single": (
            NearDuplicateGroup(occurrences=g.occurrences[:1], lines=g.lines,
                               diff_count=g.diff_count,
                               differences=[c[:1] for c in g.differences]),
            "a shared helper needs at least two occurrences",
        ),
        "no_stmts": (
            NearDuplicateGroup(occurrences=g.occurrences, lines=0,
                               diff_count=g.diff_count,
                               differences=g.differences),
            "block has no statements to extract",
        ),
        "zerodiff": (
            NearDuplicateGroup(occurrences=g.occurrences, lines=g.lines,
                               diff_count=0, differences=[]),
            "a near-duplicate has >= 1 differing position — a zero-diff group "
            "is an exact duplicate (dedup_extract's job), nothing to "
            "parameterize",
        ),
        "count_disagree": (
            NearDuplicateGroup(occurrences=g.occurrences, lines=g.lines,
                               diff_count=5, differences=g.differences),
            "malformed group: diff_count disagrees with the differences "
            "columns",
        ),
        "nonparallel": (
            NearDuplicateGroup(occurrences=g.occurrences, lines=g.lines,
                               diff_count=g.diff_count, differences=[["10"]]),
            "malformed group: a differences column is not parallel to the "
            "occurrences",
        ),
        "bad_occ": (
            NearDuplicateGroup(occurrences=["not-a-location", "pkg/b.py:1"],
                               lines=g.lines, diff_count=g.diff_count,
                               differences=g.differences),
            "malformed occurrence location(s)",
        ),
    }

    for name, (group, message) in cases.items():
        plan = plan_near_dup_extract(tmp_path, group)
        assert not plan.ok, f"{name} should block"
        assert plan.blockers == [message], name
        assert not plan.new_contents, name
