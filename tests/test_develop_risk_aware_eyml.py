"""The develop loop's learned-risk nervous signal — ``--risk-aware``.

Closes the sense→decide loop for the develop pathway: the same rollback-risk the
maintain path already acts on now orders develop moves too (low-risk first). Pins
that it is opt-in, byte-identical off / without history, and demotes a
historically-rolled-back move when the evidence exists.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.objective_compiler import Move, _ordered_candidates, _risk_ordered
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


def test_risk_ordered_demotes_a_rolled_back_move(tmp_path):
    _history(tmp_path, [
        *[_fix("risky", "app/bad.py", "rolled_back") for _ in range(5)],
        *[_fix("safe", "app/good.py", "applied") for _ in range(5)],
    ])
    moves = [_mv("risky", "app/bad.py"), _mv("safe", "app/good.py")]
    ordered = _risk_ordered(moves, str(tmp_path))
    assert [m.operator for m in ordered] == ["safe", "risky"]  # low-risk first


def test_risk_ordered_is_a_noop_without_history(tmp_path):
    moves = [_mv("risky", "app/bad.py"), _mv("safe", "app/good.py")]
    # no .apex -> every move scores the neutral baseline -> stable no-op
    assert _risk_ordered(moves, str(tmp_path)) == moves


def test_ordered_candidates_off_is_byte_identical(tmp_path):
    made = [_mv("a", "app/x.py"), _mv("b", "app/y.py")]

    def generate(_root):
        return list(made)

    off = _ordered_candidates(generate, str(tmp_path), None, None, "",
                              value_aware=False, risk_aware=False)
    # default order preserved (no memory, no value, no risk) — same objects, order
    assert [m.operator for m in off] == ["a", "b"]


def test_ordered_candidates_risk_aware_reorders_with_history(tmp_path):
    _history(tmp_path, [
        *[_fix("risky", "app/bad.py", "rolled_back") for _ in range(5)],
        *[_fix("safe", "app/good.py", "applied") for _ in range(5)],
    ])
    made = [_mv("risky", "app/bad.py"), _mv("safe", "app/good.py")]

    def generate(_root):
        return list(made)

    ordered = _ordered_candidates(generate, str(tmp_path), None, None, "",
                                  value_aware=False, risk_aware=True)
    assert [m.operator for m in ordered] == ["safe", "risky"]
