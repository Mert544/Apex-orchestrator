"""The living manifesto — ``app/engine/manifesto`` + ``apex manifesto``.

Pins that Apex synthesises its scattered proof-carrying experience into ONE
deterministic, evidence-backed constitution: AVOID / FRAGILE / TRUST / proven
idioms, each read from an existing learner.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.engine.manifesto import derive_manifesto, render_manifesto_markdown
from app.engine.native_proof_memory import record_native_landing
from app.engine.proof_of_fix import SCHEMA


def _proof(root: Path, fixes: list[dict]) -> None:
    apex = root / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / "proof-of-fix.json").write_text(
        json.dumps({"schema": SCHEMA, "generated_at": "2026-01-01", "fixes": fixes}),
        encoding="utf-8")


def _fix(action: str, module: str, outcome: str) -> dict:
    return {"outcome": outcome,
            "finding": {"action": action, "target": module},
            "changed_files": [module]}


@pytest.fixture()
def learned_project(tmp_path: Path) -> Path:
    _proof(tmp_path, [
        *[_fix("risky-x", "app/bad.py", "rolled_back") for _ in range(4)],
        _fix("risky-x", "app/bad.py", "applied"),
        *[_fix("safe-y", "app/good.py", "applied") for _ in range(6)],
    ])
    record_native_landing(tmp_path, ["2:p0 + p1"])
    return tmp_path


def test_empty_project_legislates_nothing(tmp_path):
    m = derive_manifesto(tmp_path)
    assert m == {"avoid": [], "trust": [], "fragile": [], "proven_idioms": []}
    assert "legislated no laws" in render_manifesto_markdown(m)


def test_avoid_law_from_rollbacks(learned_project):
    avoid = derive_manifesto(learned_project)["avoid"]
    assert any("risky-x" in line and "roll" in line.lower() for line in avoid)


def test_fragile_module_law(learned_project):
    fragile = derive_manifesto(learned_project)["fragile"]
    assert fragile[0]["module"] == "app/bad.py"
    assert fragile[0]["rollbacks"] == 4
    assert fragile[0]["reliability"] < 0.5


def test_trust_law_for_reliable_action(learned_project):
    trust = derive_manifesto(learned_project)["trust"]
    assert any(r["action"] == "safe-y" and r["score"] >= 0.8 for r in trust)
    # the rolled-back action is NOT trusted
    assert all(r["action"] != "risky-x" for r in trust)


def test_proven_idiom_law_from_native_experience(learned_project):
    idioms = derive_manifesto(learned_project)["proven_idioms"]
    assert idioms and idioms[0]["shape"] == "2:p0 + p1"


def test_is_deterministic(learned_project):
    assert derive_manifesto(learned_project) == derive_manifesto(learned_project)


def test_markdown_states_all_four_law_kinds(learned_project):
    md = render_manifesto_markdown(derive_manifesto(learned_project))
    assert "AVOID" in md and "FRAGILE" in md and "TRUST" in md and "PROVEN" in md
    assert "app/bad.py" in md
    assert "p0 + p1 (2-arg)" in md  # arity-qualified key rendered readably


def test_cli_manifesto_json_and_text(learned_project, capsys):
    import argparse

    from app.cli_insight import cmd_manifesto
    rc = cmd_manifesto(argparse.Namespace(target=str(learned_project), json=True))
    assert rc == 0
    assert '"fragile"' in capsys.readouterr().out

    rc = cmd_manifesto(argparse.Namespace(target=str(learned_project), json=False))
    assert rc == 0
    assert "manifesto" in capsys.readouterr().out.lower()
