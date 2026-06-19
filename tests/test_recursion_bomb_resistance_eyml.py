"""A single pathological file must never crash Apex's analysis pipeline.

A red-team audit found a CRITICAL crash family: ``ast.parse`` raises
``RecursionError`` (a ``RuntimeError`` subclass, NOT a ``SyntaxError``) on a
deeply-nested expression, and the pipeline's parse guards caught only
``SyntaxError`` — so one trivial ``.py`` file (``x = 1+1+...+1`` with tens of
thousands of terms) crashed ``ProjectProfiler.profile``, ``IdeaPermutationEngine.run``,
the apply gate, and verification end-to-end. Apex claims to be robust and offline;
a weaponizable one-file crash breaks that.

The fix widened the parse guards across the pipeline to also skip
``RecursionError`` / ``MemoryError`` (treating an un-parseable monster like a
syntax error). These tests pin that: the bomb file is ignored, the rest of the
tree is still analyzed, and nothing raises.

Deterministic; stdlib-only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# A deeply-nested expression that overflows ast.parse's recursion (well past the
# default limit) on a single line — the minimal weaponized input.
_BOMB = "x = " + "1+" * 40000 + "1\n"


@pytest.fixture
def bombed_tree(tmp_path: Path) -> Path:
    (tmp_path / "bomb.py").write_text(_BOMB, encoding="utf-8")
    (tmp_path / "ok.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_bomb.py").write_text(_BOMB, encoding="utf-8")  # a bomb TEST file too
    return tmp_path


def test_profile_survives_a_recursion_bomb(bombed_tree: Path):
    from app.tools.project_profile import ProjectProfiler

    profile = ProjectProfiler(str(bombed_tree)).profile()
    # It did not crash, and the healthy file is still in scope.
    assert profile is not None
    assert int(getattr(profile, "python_file_count", 0)) >= 1


def test_ideate_run_survives_a_recursion_bomb(bombed_tree: Path):
    from app.engine.idea_permutation import IdeaPermutationEngine

    report = IdeaPermutationEngine(project_root=str(bombed_tree)).run()
    assert report is not None  # produced a tree instead of crashing


def test_verification_survives_a_bomb_test_file(bombed_tree: Path):
    from app.engine.verification_strength import (
        assess_strength,
        module_referenced_by_suite,
    )

    # A hostile test file must not crash coverage detection — it contributes no
    # coverage (treated as unparseable), it does not raise.
    assert module_referenced_by_suite(str(bombed_tree), "ok.py") in (True, False)
    strength = assess_strength(
        str(bombed_tree), ["ok.py"],
        {"ok.py": "def add(a, b):\n    return a + b\n"},
        {"ok.py": "def add(a, b):\n    return a - b\n"})
    assert strength["level"] in ("none", "module", "function", "test-change")


def test_apply_on_a_bomb_target_does_not_crash(bombed_tree: Path):
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import ActionStep

    step = ActionStep(branch_path="x.0", title="t", operator="root",
                      subject="bomb.py", action_type="organize_imports",
                      target="bomb.py", executable=True)
    out = IdeaActionBridge().apply_step(step, str(bombed_tree), mode="autonomous")
    # The transform can't parse it, so it simply does not apply — no crash.
    assert out["applied"] is False


def test_detectors_skip_the_bomb(bombed_tree: Path):
    from app.engine.detectors import security_labels

    assert security_labels((bombed_tree / "bomb.py").read_text()) == []
