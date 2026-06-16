"""Byte-identical characterization harness for the ``_splice_first`` and
``_locate_diff_columns`` refactor.

Drives a wide battery of synthetic near-duplicate groups (clean lifts that
exercise ``_splice_first``, structural-mismatch / segment-disagreement /
multi-line / non-value-hole shapes that exercise ``_locate_diff_columns`` and
its splice gate) through ``plan_near_dup_extract`` and asserts the FULL
serialized plan is byte-for-byte identical between the pristine pre-refactor
snapshot (``_near_dup_extract_orig_scratch_eyml1y``) and the live, refactored
module. Zero mismatches across every case proves the two decomposed helpers
preserve exact behaviour, determinism, and every blocker message.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.near_dup import NearDuplicateGroup, find_near_duplicates
from app.execution import near_dup_extract as live

try:  # pragma: no cover - scratch snapshot only present during the refactor
    from app.execution import _near_dup_extract_orig_scratch_eyml1y as orig
except Exception:  # pragma: no cover
    orig = None


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _serialize_plan(plan) -> str:
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


def _only_group(root: Path, *, min_statements: int) -> NearDuplicateGroup:
    groups = find_near_duplicates(
        root, min_statements=min_statements, min_occurrences=2)
    assert len(groups) == 1, f"expected one group, got {groups}"
    return groups[0]


# ── Source-pair factories. Each yields (files, min_statements). ──

def _pair(body_a: str, body_b: str, *, fn_a="alpha", fn_b="beta"):
    a = f"def {fn_a}(n):\n{body_a}"
    b = f"def {fn_b}(n):\n{body_b}"
    return {"pkg/__init__.py": "", "pkg/a.py": a, "pkg/b.py": b}


# Clean single-constant hole (exercises _splice_first happy path).
_CLEAN_INT = _pair(
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n    d = c + 10\n    return d\n",
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n    d = c + 20\n    return d\n",
)

# Two differing constant holes on different lines.
_TWO_HOLES = _pair(
    "    a = n + 1\n    b = a * 5\n    c = b + 3\n    d = c + 10\n    return d\n",
    "    a = n + 1\n    b = a * 7\n    c = b + 3\n    d = c + 20\n    return d\n",
)

# Two differing holes on the SAME line (right-to-left splice path).
_SAME_LINE = _pair(
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n    d = 10 + 20\n    return d\n",
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n    d = 30 + 40\n    return d\n",
)

# Differing LOADED NAME holes (value-leaf names; descriptive param naming).
_NAME_HOLES = _pair(
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n"
    "    d = c + FooGenerator\n    return d\n",
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n"
    "    d = c + BarGenerator\n    return d\n",
)

# String-constant holes.
_STR_HOLES = _pair(
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n"
    "    d = str(c) + 'x'\n    return d\n",
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n"
    "    d = str(c) + 'y'\n    return d\n",
)

# Three occurrences across two files.
_THREE = {
    "pkg/__init__.py": "",
    "pkg/a.py": (
        "def alpha(n):\n    a = n + 1\n    b = a * 2\n    c = b + 3\n"
        "    d = c + 10\n    return d\n"
    ),
    "pkg/b.py": (
        "def beta(n):\n    a = n + 1\n    b = a * 2\n    c = b + 3\n"
        "    d = c + 20\n    return d\n\n\n"
        "def gamma(n):\n    a = n + 1\n    b = a * 2\n    c = b + 3\n"
        "    d = c + 30\n    return d\n"
    ),
}

_CLEAN_CASES = {
    "clean_int": (_CLEAN_INT, 5),
    "two_holes": (_TWO_HOLES, 5),
    "same_line": (_SAME_LINE, 5),
    "name_holes": (_NAME_HOLES, 5),
    "str_holes": (_STR_HOLES, 5),
    "three_occ": (_THREE, 5),
}


def _build_clean_group(tmp_path: Path, case) -> NearDuplicateGroup:
    files, min_stmts = case
    for rel, text in files.items():
        _write(tmp_path, rel, text)
    return _only_group(tmp_path, min_statements=min_stmts)


@pytest.mark.skipif(orig is None, reason="pristine snapshot module missing")
@pytest.mark.parametrize("name", sorted(_CLEAN_CASES))
def test_clean_cases_byte_identical(tmp_path: Path, name: str) -> None:
    group = _build_clean_group(tmp_path, _CLEAN_CASES[name])
    a = _serialize_plan(orig.plan_near_dup_extract(tmp_path, group))
    b = _serialize_plan(live.plan_near_dup_extract(tmp_path, group))
    assert a == b, f"{name}: refactored plan diverged from snapshot"
    # Determinism: same input twice yields identical serialization.
    b2 = _serialize_plan(live.plan_near_dup_extract(tmp_path, group))
    assert b == b2


# ── Blocker / gate shapes that drive the located-column logic. ──

def _mangled_groups(g: NearDuplicateGroup):
    """Groups crafted to hit the structural gates inside the two targets."""
    return {
        # count_disagree → _locate_diff_columns re-derive vs report mismatch.
        "count_mismatch": NearDuplicateGroup(
            occurrences=g.occurrences, lines=g.lines,
            diff_count=g.diff_count + 1,
            differences=g.differences + [["10", "20"]]),
        # differences segments disagree with re-derived ones.
        "seg_disagree": NearDuplicateGroup(
            occurrences=g.occurrences, lines=g.lines,
            diff_count=g.diff_count,
            differences=[["999", "888"]]),
    }


@pytest.mark.skipif(orig is None, reason="pristine snapshot module missing")
@pytest.mark.parametrize("name", ["count_mismatch", "seg_disagree"])
def test_locate_gate_blockers_byte_identical(tmp_path: Path, name: str) -> None:
    for rel, text in _CLEAN_INT.items():
        _write(tmp_path, rel, text)
    g = _only_group(tmp_path, min_statements=5)
    group = _mangled_groups(g)[name]
    a = _serialize_plan(orig.plan_near_dup_extract(tmp_path, group))
    b = _serialize_plan(live.plan_near_dup_extract(tmp_path, group))
    assert a == b, f"{name}: refactored plan diverged from snapshot"


# Multi-line literal hole (triple-quoted string spanning rows) →
# _splice_first multi-line blocker.
_MULTILINE = _pair(
    '    a = n + 1\n    b = a * 2\n    c = b + 3\n'
    '    d = c + """\nAAA\n"""\n    return d\n',
    '    a = n + 1\n    b = a * 2\n    c = b + 3\n'
    '    d = c + """\nBBB\n"""\n    return d\n',
)


@pytest.mark.skipif(orig is None, reason="pristine snapshot module missing")
def test_multiline_hole_byte_identical(tmp_path: Path) -> None:
    for rel, text in _MULTILINE.items():
        _write(tmp_path, rel, text)
    group = _only_group(tmp_path, min_statements=5)
    plan = live.plan_near_dup_extract(tmp_path, group)
    assert not plan.ok and any("multiple lines" in m for m in plan.blockers)
    a = _serialize_plan(orig.plan_near_dup_extract(tmp_path, group))
    b = _serialize_plan(plan)
    assert a == b


# Non-value hole: differing position is an ATTRIBUTE / store target — should be
# blocked by the value-hole gate (and never reach a bad splice).
_ATTR_HOLE = _pair(
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n"
    "    obj.foo = c\n    return obj.foo\n",
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n"
    "    obj.bar = c\n    return obj.bar\n",
)


@pytest.mark.skipif(orig is None, reason="pristine snapshot module missing")
def test_attr_hole_byte_identical(tmp_path: Path) -> None:
    for rel, text in _ATTR_HOLE.items():
        _write(tmp_path, rel, text)
    groups = find_near_duplicates(
        tmp_path, min_statements=5, min_occurrences=2)
    # Whether or not the detector groups these, compare plans for each.
    for group in groups or []:
        a = _serialize_plan(orig.plan_near_dup_extract(tmp_path, group))
        b = _serialize_plan(live.plan_near_dup_extract(tmp_path, group))
        assert a == b
