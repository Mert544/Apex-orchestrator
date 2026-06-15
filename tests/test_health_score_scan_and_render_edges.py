"""Error-path and render corners for app.engine.health_score.

The two big suites cover the happy grade() paths to ~96%; this file pins the
remaining defensive corners that a real run rarely reaches:

  * Both scan helpers' ``except OSError: continue`` branch — a module listed in
    the profile whose file cannot be read (deleted/unreadable) is skipped, not
    crashed on. Exercised by calling the helpers directly with a fake profile.
  * ``render_grade_markdown`` for a clean grade (the "Clean bill of health" else)
    and for a grade carrying a non-empty ``scope_line`` (polyglot repo).
  * ``load_grade_snapshot`` returning None on a structurally-invalid snapshot
    (valid JSON, but not a score-bearing dict).

Deterministic and hermetic: SimpleNamespace profiles, hand-built HealthScores,
and a tmp_path snapshot file. No wall-clock assertions. Style mirrors the
sibling health-score suites.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.engine.health_score import (
    Component,
    HealthScore,
    _scan_maintainability,
    _scan_own_modules,
    load_grade_snapshot,
    render_grade_markdown,
)


def test_scan_maintainability_skips_unreadable_module():
    # The profile lists a .py module that does not exist on disk; read_text raises
    # FileNotFoundError (an OSError subclass) and the file is skipped, not fatal.
    profile = SimpleNamespace(module_to_tests={"app/ghost.py": []})
    over, top = _scan_maintainability("/tmp/apex-nonexistent-root-xyz", profile)
    assert over == 0
    assert top == []


def test_scan_own_modules_skips_unreadable_module():
    # Same OSError-skip contract for the single grade-source scan: an unreadable
    # listed module contributes nothing rather than raising.
    profile = SimpleNamespace(module_to_tests={"app/ghost.py": []})
    reliability, bugs, sec_count, sec_weight, top_sec, top_bug = _scan_own_modules(
        "/tmp/apex-nonexistent-root-xyz", profile
    )
    assert reliability == set()
    assert bugs == 0
    assert sec_count == 0
    assert sec_weight == 0
    assert top_sec == []
    assert top_bug == []


def test_render_markdown_clean_bill_of_health_when_no_fixes():
    # A grade with no fixes hits the else branch: the encouraging clean-bill line,
    # not a "Cheapest ways to climb" section.
    h = HealthScore(score=100, letter="A+",
                    components=[Component("Security", 0, "0 finding(s)")],
                    fixes=[])
    md = render_grade_markdown(h)
    assert "Clean bill of health" in md
    assert "Cheapest ways to climb" not in md


def test_render_markdown_includes_scope_line_when_present():
    # A polyglot repo carries a non-empty scope_line; the render emits it as an
    # italic honesty note. An all-Python grade leaves it empty (covered elsewhere).
    h = HealthScore(score=88, letter="B+",
                    components=[Component("Security", 0, "0 finding(s)")],
                    fixes=[],
                    scope_line="Graded the 12 Python files; 3 Go files were out of scope.")
    md = render_grade_markdown(h)
    assert "Graded the 12 Python files; 3 Go files were out of scope." in md
    assert "_Graded the 12 Python files" in md  # rendered as an italic line


def test_load_snapshot_returns_none_on_dict_without_score(tmp_path: Path):
    # Valid JSON, but the dict carries no "score" key -> the structural guard
    # rejects it (rather than handing back a half-built snapshot downstream).
    snap = tmp_path / ".apex" / "grade-snapshot.json"
    snap.parent.mkdir(parents=True)
    snap.write_text(json.dumps({"date": "2026-01-01", "letter": "A"}), encoding="utf-8")
    assert load_grade_snapshot(str(tmp_path)) is None


def test_load_snapshot_returns_none_on_non_dict_json(tmp_path: Path):
    # Valid JSON that is not a dict at all (e.g. a list) is also rejected.
    snap = tmp_path / ".apex" / "grade-snapshot.json"
    snap.parent.mkdir(parents=True)
    snap.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert load_grade_snapshot(str(tmp_path)) is None
