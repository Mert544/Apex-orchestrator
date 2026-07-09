"""The develop loop's learned-avoid closed loop — opt-in ``avoid_aware``.

Closes the SKIP half of the sense→decide loop for the develop pathway: today
``apex develop --risk-aware`` only REORDERS moves by rollback risk (low-risk
first) but never refuses one, unlike the maintain path's closed loop
(``idea_action_bridge._learned_skip``). This mirrors that SAME evidence-backed
avoid-guard (``counterfactual_learning.should_avoid`` over
``failure_signatures``) into the develop compiler, reusing the EXISTING
``skip_targets`` channel :func:`_apply_one_move` already honors (the covered-only
re-skip plumbing) rather than adding a parallel mechanism.

Pins: opt-in (default off, byte-identical), honest (no ``.apex`` history means
no evidence means no skip even when armed), and that an unflagged move still
lands alongside a flagged one that is skipped.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.objective_compiler import (
    CompileResult,
    Move,
    _arm_avoid_skip,
    _avoid_flagged_targets,
    _initial_skip_targets,
    compile_objective,
)
from app.engine.proof_of_fix import SCHEMA


def _mv(operator: str, module: str) -> Move:
    return Move(operator=operator, target=f"{module}:x", description="",
                build_plan=lambda: None)


def _history(root: Path, fixes: list[dict]) -> None:
    (root / ".apex").mkdir(parents=True, exist_ok=True)
    (root / ".apex" / "proof-of-fix.json").write_text(
        json.dumps({"schema": SCHEMA, "generated_at": "2026-01-01", "fixes": fixes}),
        encoding="utf-8")


def _fix(action: str, module: str, outcome: str) -> dict:
    return {"outcome": outcome, "finding": {"action": action, "target": module},
            "changed_files": [module]}


def _result() -> CompileResult:
    return CompileResult(objective="x", fitness_start=1.0, fitness_end=1.0)


# --------------------------------------------------------------------------- #
# Unit level: the new helpers directly, mirroring test_develop_risk_aware_eyml #
# --------------------------------------------------------------------------- #

def test_avoid_flagged_targets_flags_evidence_backed_move(tmp_path):
    _history(tmp_path, [
        *[_fix("risky", "app/bad.py", "rolled_back") for _ in range(5)],
        *[_fix("safe", "app/good.py", "applied") for _ in range(5)],
    ])
    moves = [_mv("risky", "app/bad.py"), _mv("safe", "app/good.py")]
    assert _avoid_flagged_targets(moves, str(tmp_path)) == {"app/bad.py:x"}


def test_avoid_flagged_targets_is_empty_without_history(tmp_path):
    moves = [_mv("risky", "app/bad.py"), _mv("safe", "app/good.py")]
    # no .apex -> no evidence -> nothing flagged, even for a move that would
    # otherwise qualify once evidence exists.
    assert _avoid_flagged_targets(moves, str(tmp_path)) == set()


def test_arm_avoid_skip_populates_skip_targets_and_records_reason(tmp_path):
    _history(tmp_path, [
        *[_fix("risky", "app/bad.py", "rolled_back") for _ in range(5)],
        *[_fix("safe", "app/good.py", "applied") for _ in range(5)],
    ])
    moves = [_mv("risky", "app/bad.py"), _mv("safe", "app/good.py")]
    skip_targets: set = set()
    result = _result()
    _arm_avoid_skip(result, skip_targets, moves, str(tmp_path), avoid_aware=True)
    assert skip_targets == {"app/bad.py:x"}
    assert len(result.avoided) == 1
    assert "app/bad.py:x" in result.avoided[0]


def test_arm_avoid_skip_does_not_re_announce_on_a_later_pass(tmp_path):
    _history(tmp_path, [
        *[_fix("risky", "app/bad.py", "rolled_back") for _ in range(5)],
    ])
    moves = [_mv("risky", "app/bad.py")]
    skip_targets: set = set()
    result = _result()
    _arm_avoid_skip(result, skip_targets, moves, str(tmp_path), avoid_aware=True)
    _arm_avoid_skip(result, skip_targets, moves, str(tmp_path), avoid_aware=True)
    assert len(result.avoided) == 1  # announced once, not once per pass


def test_arm_avoid_skip_is_noop_when_flag_off(tmp_path):
    _history(tmp_path, [
        *[_fix("risky", "app/bad.py", "rolled_back") for _ in range(5)],
    ])
    moves = [_mv("risky", "app/bad.py")]
    skip_targets: set = set()
    result = _result()
    _arm_avoid_skip(result, skip_targets, moves, str(tmp_path), avoid_aware=False)
    assert skip_targets == set()
    assert result.avoided == []


def test_arm_avoid_skip_is_noop_when_skip_targets_none(tmp_path):
    _history(tmp_path, [
        *[_fix("risky", "app/bad.py", "rolled_back") for _ in range(5)],
    ])
    moves = [_mv("risky", "app/bad.py")]
    result = _result()
    # Never raises, and leaves the (unarmed) channel exactly as it was.
    _arm_avoid_skip(result, None, moves, str(tmp_path), avoid_aware=True)
    assert result.avoided == []


def test_initial_skip_targets_arms_on_either_gate():
    assert _initial_skip_targets(covered_only=False, avoid_aware=False) is None
    assert _initial_skip_targets(covered_only=True, avoid_aware=False) == set()
    assert _initial_skip_targets(covered_only=False, avoid_aware=True) == set()
    assert _initial_skip_targets(covered_only=True, avoid_aware=True) == set()


# --------------------------------------------------------------------------- #
# Engine level: compile_objective(avoid_aware=...) end to end                  #
# --------------------------------------------------------------------------- #
# ``flagged.py`` is nested 3 levels deep (module_traits' "deep" trait); ``safe.py``
# is shallow (falls to the "generic" trait) — different trait buckets, so the
# fabricated history can flag ONE without touching the other (the avoid-guard
# groups by (action, trait), not by literal path — the same grouping the
# maintain path's closed loop already relies on).
_NONE_CHECK = "def f(x):\n    return x == None\n"


def _flagged_and_safe(root: Path) -> None:
    (root / "pkg" / "a" / "b").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "a" / "b" / "flagged.py").write_text(_NONE_CHECK, encoding="utf-8")
    (root / "pkg" / "safe.py").write_text(_NONE_CHECK, encoding="utf-8")


def _rolled_back_modernize_on_deep_module(root: Path) -> None:
    _history(root, [
        _fix("modernize", "pkg/a/b/flagged.py", "rolled_back") for _ in range(5)
    ])


def test_avoid_aware_skips_the_flagged_move(tmp_path):
    _flagged_and_safe(tmp_path)
    _rolled_back_modernize_on_deep_module(tmp_path)
    r = compile_objective(str(tmp_path), objective="modernize", apply=True,
                          verify=False, avoid_aware=True)
    landed = {s.target for s in r.steps}
    assert "pkg/safe.py:modernize" in landed          # the unflagged move still lands
    assert "pkg/a/b/flagged.py:modernize" not in landed  # the flagged one is refused
    assert any("flagged.py" in a for a in r.avoided)
    # The file is untouched — the avoid-guard skipped it BEFORE any write.
    assert (tmp_path / "pkg" / "a" / "b" / "flagged.py").read_text() == _NONE_CHECK
    assert "is None" in (tmp_path / "pkg" / "safe.py").read_text()


def test_avoid_aware_off_lands_both_byte_identical(tmp_path):
    # Same fixture + same damning history, but the flag is OFF (the default) ->
    # nothing is skipped, both moves land exactly as they always have.
    _flagged_and_safe(tmp_path)
    _rolled_back_modernize_on_deep_module(tmp_path)
    r = compile_objective(str(tmp_path), objective="modernize", apply=True,
                          verify=False)
    landed = {s.target for s in r.steps}
    assert {"pkg/safe.py:modernize", "pkg/a/b/flagged.py:modernize"} <= landed
    assert r.avoided == []
    assert "avoided" not in r.to_dict()


def test_avoid_aware_on_with_no_history_lands_both(tmp_path):
    # Honest: with the flag ON but NO .apex proof history at all, there is no
    # evidence to act on, so nothing is skipped — both moves land.
    _flagged_and_safe(tmp_path)
    r = compile_objective(str(tmp_path), objective="modernize", apply=True,
                          verify=False, avoid_aware=True)
    landed = {s.target for s in r.steps}
    assert {"pkg/safe.py:modernize", "pkg/a/b/flagged.py:modernize"} <= landed
    assert r.avoided == []
