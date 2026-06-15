"""Regression: the generalizable-duplication signal caps the module span.

A near-duplicate block spanning a SMALL number of modules is actionable
copy-paste ("extract one shared helper"). The SAME skeleton across MANY modules
is an intentional framework/template pattern (its shared abstraction already
exists), so Apex must NOT surface it as "generalize" — a dogfood finding (it
flagged a 31-module transform-framework template before the cap was added).

``find_near_duplicates`` matches windows of >=5 TOP-LEVEL statements and excludes
EXACT duplicates, so each block here is 6 flat statements varying by one literal.
"""

from __future__ import annotations

from pathlib import Path

from app.tools.project_profile import ProjectProfiler


def _module_with_block(n: int) -> str:
    # 6 flat (top-level) statements; one literal varies per module → near-dup.
    return (
        f"def compute_{n}(a, b):\n"
        f"    x = a + 1\n"
        f"    y = b - 2\n"
        f"    z = x * y\n"
        f"    w = z + {n}\n"
        f"    total = w - x\n"
        f"    return total\n"
    )


def _make(root: Path, count: int) -> list[dict]:
    for i in range(count):
        p = root / "app" / f"m{i}.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_module_with_block(i), encoding="utf-8")
    return ProjectProfiler(str(root)).profile().generalizable_duplications


def test_small_span_is_flagged(tmp_path: Path):
    # The near-identical block copied across 3 modules → an actionable signal.
    gd = _make(tmp_path, 3)
    assert gd, "a 3-module near-duplicate should be flagged"
    assert all(2 <= len(e["modules"]) <= 4 for e in gd)


def test_framework_wide_span_is_not_flagged(tmp_path: Path):
    # The SAME skeleton across 8 modules is a template, not copy-paste to DRY —
    # the group spans 8 modules (> cap of 4) so it must be dropped entirely.
    gd = _make(tmp_path, 8)
    assert all(len(e["modules"]) <= 4 for e in gd), gd
