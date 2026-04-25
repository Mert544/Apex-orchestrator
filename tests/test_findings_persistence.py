from __future__ import annotations

from pathlib import Path

import pytest

from app.memory.findings_persistence import FindingsPersistence, ClaimStatus


class TestFindingsPersistenceJson:
    def test_record_and_retrieve(self, tmp_path: Path):
        store = FindingsPersistence(tmp_path, backend="json")
        result = store.record_findings(
            "run-1",
            [{"claim": "missing auth", "branch": "x.a", "confidence": 0.8}],
        )
        assert result["recorded"] == 1
        assert result["total_tracked"] == 1

        open_claims = store.get_open_claims()
        assert len(open_claims) == 1
        assert open_claims[0]["claim"] == "missing auth"

    def test_persistent_findings_require_min_runs(self, tmp_path: Path):
        store = FindingsPersistence(tmp_path, backend="json")
        store.record_findings("run-1", [{"claim": "missing auth", "confidence": 0.8}])
        store.record_findings("run-2", [{"claim": "missing auth", "confidence": 0.8}])

        persistent = store.get_persistent_findings(min_runs=2)
        assert len(persistent) == 1
        assert persistent[0]["run_count"] == 2

    def test_resolved_findings(self, tmp_path: Path):
        store = FindingsPersistence(tmp_path, backend="json")
        store.record_findings("run-1", [{"claim": "missing auth", "confidence": 0.8}])
        store.update_claim_status("missing auth", ClaimStatus.RESOLVED)

        resolved = store.get_resolved_findings()
        assert len(resolved) == 1
        assert resolved[0]["status"] == ClaimStatus.RESOLVED

    def test_recall_prompt(self, tmp_path: Path):
        store = FindingsPersistence(tmp_path, backend="json")
        store.record_findings("run-1", [{"claim": "missing auth", "confidence": 0.8}])
        prompt = store.build_recall_prompt()
        assert "Previously identified issues" in prompt
        assert "missing auth" in prompt

    def test_export_import_roundtrip(self, tmp_path: Path):
        store = FindingsPersistence(tmp_path, backend="json")
        store.record_findings("run-1", [{"claim": "missing auth", "confidence": 0.8}])
        exported = store.export_state()

        store2 = FindingsPersistence(tmp_path / "other", backend="json")
        store2.import_state(exported)
        assert len(store2.get_open_claims()) == 1

    def test_eviction_limit(self, tmp_path: Path):
        store = FindingsPersistence(tmp_path, backend="json", max_claims=3)
        for i in range(5):
            store.record_findings(f"run-{i}", [{"claim": f"issue-{i}", "confidence": 0.5}])
        state = store._backend.load()
        assert len(state["claim_tracker"]) <= 3

    def test_context_manager(self, tmp_path: Path):
        with FindingsPersistence(tmp_path, backend="json") as store:
            store.record_findings("run-1", [{"claim": "x", "confidence": 0.5}])
        # Should close cleanly

    def test_empty_findings(self, tmp_path: Path):
        store = FindingsPersistence(tmp_path, backend="json")
        result = store.record_findings("run-1", [])
        assert result["recorded"] == 0
        assert store.build_recall_prompt().startswith("No previously")


class TestFindingsPersistenceShelve:
    def test_basic_shelve_operations(self, tmp_path: Path):
        store = FindingsPersistence(tmp_path, backend="shelve")
        store.record_findings(
            "run-1",
            [{"claim": "missing auth", "branch": "x.a", "confidence": 0.8}],
        )
        open_claims = store.get_open_claims()
        assert len(open_claims) == 1
        store.close()

    def test_shelve_persistent_findings(self, tmp_path: Path):
        store = FindingsPersistence(tmp_path, backend="shelve")
        store.record_findings("run-1", [{"claim": "missing auth", "confidence": 0.8}])
        store.record_findings("run-2", [{"claim": "missing auth", "confidence": 0.8}])

        persistent = store.get_persistent_findings(min_runs=2)
        assert len(persistent) == 1
        store.close()

    def test_shelve_resolved(self, tmp_path: Path):
        store = FindingsPersistence(tmp_path, backend="shelve")
        store.record_findings("run-1", [{"claim": "missing auth", "confidence": 0.8}])
        store.update_claim_status("missing auth", ClaimStatus.RESOLVED)

        resolved = store.get_resolved_findings()
        assert len(resolved) == 1
        store.close()

    def test_shelve_context_manager(self, tmp_path: Path):
        with FindingsPersistence(tmp_path, backend="shelve") as store:
            store.record_findings("run-1", [{"claim": "x", "confidence": 0.5}])


class TestFindingsPersistenceCommon:
    def test_invalid_backend_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Unsupported backend"):
            FindingsPersistence(tmp_path, backend="redis")

    def test_claim_status_values(self):
        assert ClaimStatus.OPEN == "open"
        assert ClaimStatus.RESOLVED == "resolved"
        assert ClaimStatus.POTENTIALLY_RESOLVED == "potentially_resolved"
