from __future__ import annotations

from pathlib import Path

from app.memory.bridge import CentralMemoryBridge


def test_bridge_records_and_retrieves(tmp_path: Path):
    bridge = CentralMemoryBridge(str(tmp_path), backend="json")
    bridge.record_run(
        "run-1",
        claims=[{"claim": "missing auth", "branch": "x.a", "confidence": 0.8}],
        findings=[{"claim": "eval() usage", "confidence": 0.9}],
    )
    open_claims = bridge.get_open_claims()
    assert len(open_claims) == 2
    bridge.close()


def test_bridge_dedupes_same_claim(tmp_path: Path):
    bridge = CentralMemoryBridge(str(tmp_path), backend="json")
    bridge.record_run(
        "run-1",
        claims=[{"claim": "missing auth", "confidence": 0.8}],
        findings=[{"claim": "missing auth", "confidence": 0.9}],
    )
    open_claims = bridge.get_open_claims()
    # Same claim from both stores should dedupe
    assert len(open_claims) == 1
    bridge.close()


def test_bridge_learning(tmp_path: Path):
    bridge = CentralMemoryBridge(str(tmp_path), backend="json")
    bridge.record_learning("security", "eval", success=True)
    bridge.record_learning("security", "eval", success=True)
    tips = bridge.get_learning_tips("security")
    assert "eval" in tips
    assert tips["eval"]["success_rate"] == 1.0
    bridge.close()


def test_bridge_persistent_claims(tmp_path: Path):
    bridge = CentralMemoryBridge(str(tmp_path), backend="json")
    bridge.record_run("run-1", claims=[{"claim": "x", "confidence": 0.5}], findings=[])
    bridge.record_run("run-2", claims=[{"claim": "x", "confidence": 0.5}], findings=[])
    persistent = bridge.get_persistent_claims(min_runs=2)
    assert len(persistent) == 1
    assert persistent[0]["claim"] == "x"
    bridge.close()


def test_bridge_recall_prompt(tmp_path: Path):
    bridge = CentralMemoryBridge(str(tmp_path), backend="json")
    bridge.record_run("run-1", claims=[{"claim": "auth issue", "confidence": 0.8}], findings=[])
    prompt = bridge.build_recall_prompt()
    assert "auth issue" in prompt
    bridge.close()


def test_bridge_context_manager(tmp_path: Path):
    with CentralMemoryBridge(str(tmp_path), backend="json") as bridge:
        bridge.record_run("run-1", claims=[{"claim": "x", "confidence": 0.5}], findings=[])
        assert len(bridge.get_open_claims()) == 1
