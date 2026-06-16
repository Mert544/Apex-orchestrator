"""Byte-identical characterization harness for the ``_emit_rewrites`` refactor.

Drives a wide battery of synthetic near-duplicate groups through
``plan_near_dup_extract`` and asserts the FULL serialized plan is byte-for-byte
identical between a pristine pre-refactor snapshot of the module
(``_near_dup_orig_snap_xj42``, an exact copy of ``HEAD``) and the live,
refactored module. ``_emit_rewrites`` owns helper insertion (with the anchor
rebase by net line-delta of replacements above it), per-occurrence call-site
synthesis (tail-return / live-out / bare forms), cross-file import insertion,
the strip-unused-imports gate, and the per-file parse gate; the cases below
exercise every one of those branches. Zero mismatches across every case proves
the decomposition preserves exact rewrite text, edit counts, blockers, and
determinism.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.near_dup import NearDuplicateGroup, find_near_duplicates
from app.execution import near_dup_extract as live

try:  # pragma: no cover - scratch snapshot only present during the refactor
    from app.execution import _near_dup_orig_snap_xj42 as orig
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


def _pair(body_a: str, body_b: str, *, fn_a="alpha", fn_b="beta"):
    a = f"def {fn_a}(n):\n{body_a}"
    b = f"def {fn_b}(n):\n{body_b}"
    return {"pkg/__init__.py": "", "pkg/a.py": a, "pkg/b.py": b}


# Clean single-constant hole (call site is a bare/return expr + helper insert).
_CLEAN_INT = _pair(
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n    d = c + 10\n    return d\n",
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n    d = c + 20\n    return d\n",
)

# Two holes, two files: forces the cross-file import-insertion branch in emit.
_TWO_HOLES = _pair(
    "    a = n + 1\n    b = a * 5\n    c = b + 3\n    d = c + 10\n    return d\n",
    "    a = n + 1\n    b = a * 7\n    c = b + 3\n    d = c + 20\n    return d\n",
)

_SAME_LINE = _pair(
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n    d = 10 + 20\n    return d\n",
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n    d = 30 + 40\n    return d\n",
)

_NAME_HOLES = _pair(
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n"
    "    d = c + FooGenerator\n    return d\n",
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n"
    "    d = c + BarGenerator\n    return d\n",
)

_STR_HOLES = _pair(
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n"
    "    d = str(c) + 'x'\n    return d\n",
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n"
    "    d = str(c) + 'y'\n    return d\n",
)

# Block with NO tail return: exercises live-out / bare call-line forms.
_NO_RETURN = _pair(
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n    d = c + 10\n    print(d)\n",
    "    a = n + 1\n    b = a * 2\n    c = b + 3\n    d = c + 20\n    print(d)\n",
)

# Three occurrences across two files: file b holds two copies (call-site
# replacement + edit-count), file a holds the helper insertion.
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

# Two copies in ONE file, the FIRST emit occurrence sitting BELOW the other:
# forces the anchor rebase (delta_above) in the helper-insertion branch.
_SAME_FILE_TWO = {
    "pkg/__init__.py": "",
    "pkg/a.py": (
        "def alpha(n):\n    a = n + 1\n    b = a * 2\n    c = b + 3\n"
        "    d = c + 10\n    return d\n\n\n"
        "def beta(n):\n    a = n + 1\n    b = a * 2\n    c = b + 3\n"
        "    d = c + 20\n    return d\n"
    ),
}

# Helper-using imports that get stranded: exercises strip_unused_imports gate.
_WITH_IMPORT = {
    "pkg/__init__.py": "",
    "pkg/a.py": (
        "import os\n\n\n"
        "def alpha(n):\n    a = n + 1\n    b = a * 2\n    c = b + 3\n"
        "    d = c + 10\n    return d\n"
    ),
    "pkg/b.py": (
        "import os\n\n\n"
        "def beta(n):\n    a = n + 1\n    b = a * 2\n    c = b + 3\n"
        "    d = c + 20\n    return d\n"
    ),
}

_CASES = {
    "clean_int": (_CLEAN_INT, 5),
    "two_holes": (_TWO_HOLES, 5),
    "same_line": (_SAME_LINE, 5),
    "name_holes": (_NAME_HOLES, 5),
    "str_holes": (_STR_HOLES, 5),
    "no_return": (_NO_RETURN, 5),
    "three_occ": (_THREE, 5),
    "same_file_two": (_SAME_FILE_TWO, 5),
    "with_import": (_WITH_IMPORT, 5),
}


def _build_group(tmp_path: Path, case) -> NearDuplicateGroup:
    files, min_stmts = case
    for rel, text in files.items():
        _write(tmp_path, rel, text)
    return _only_group(tmp_path, min_statements=min_stmts)


@pytest.mark.skipif(orig is None, reason="pristine snapshot module missing")
@pytest.mark.parametrize("name", sorted(_CASES))
def test_emit_byte_identical(tmp_path: Path, name: str) -> None:
    group = _build_group(tmp_path, _CASES[name])
    a = _serialize_plan(orig.plan_near_dup_extract(tmp_path, group))
    b = _serialize_plan(live.plan_near_dup_extract(tmp_path, group))
    assert a == b, f"{name}: refactored plan diverged from snapshot"
    # The clean cases must actually reach emit (ok plan, content produced).
    live_plan = live.plan_near_dup_extract(tmp_path, group)
    assert live_plan.ok and live_plan.new_contents
    # Determinism: same input twice yields identical serialization.
    b2 = _serialize_plan(live.plan_near_dup_extract(tmp_path, group))
    assert b == b2
