from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.memory.findings_persistence import (
    ClaimStatus,
    FindingsPersistence,
    _BaseBackend,
    _JsonBackend,
    _ShelveBackend,
)


def test_unsupported_backend_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsupported backend"):
        FindingsPersistence(tmp_path, backend="sqlite")


def test_base_backend_abstract_methods_raise():
    # The ABC methods are abstract; calling them on a bare subclass raises.
    class Bare(_BaseBackend):
        def load(self):  # type: ignore[override]
            return super().load()

        def save(self, state):  # type: ignore[override]
            return super().save(state)

        def close(self):  # type: ignore[override]
            return super().close()

    bare = Bare()
    with pytest.raises(NotImplementedError):
        bare.load()
    with pytest.raises(NotImplementedError):
        bare.save({})
    with pytest.raises(NotImplementedError):
        bare.close()


def test_json_backend_default_when_missing(tmp_path: Path):
    backend = _JsonBackend(tmp_path / "findings.json")
    state = backend.load()
    assert state["claim_tracker"] == []
    backend.close()  # no-op for json


def test_json_backend_recovers_from_corrupt_file(tmp_path: Path):
    path = tmp_path / "findings.json"
    path.write_text("not json{", encoding="utf-8")
    backend = _JsonBackend(path)
    state = backend.load()
    assert state["claim_tracker"] == []


def test_json_backend_recovers_from_non_dict(tmp_path: Path):
    path = tmp_path / "findings.json"
    path.write_text(json.dumps([1, 2]), encoding="utf-8")
    backend = _JsonBackend(path)
    assert backend.load()["runs"] == []


def test_shelve_backend_roundtrip_and_default(tmp_path: Path):
    backend = _ShelveBackend(tmp_path / "findings_db")
    # Fresh shelve has no "state" key -> default.
    assert backend.load()["claim_tracker"] == []
    backend.save({"schema_version": 1, "claim_tracker": [{"claim": "x"}], "runs": []})
    reloaded = backend.load()
    assert reloaded["claim_tracker"] == [{"claim": "x"}]
    backend.close()
    # close is idempotent (second call hits the early return).
    backend.close()


def test_shelve_backend_reopens_after_close(tmp_path: Path):
    db_path = tmp_path / "findings_db"
    backend = _ShelveBackend(db_path)
    backend.save({"schema_version": 1, "claim_tracker": [{"claim": "persisted"}], "runs": []})
    backend.close()
    # New backend instance reads persisted data from disk.
    backend2 = _ShelveBackend(db_path)
    assert backend2.load()["claim_tracker"] == [{"claim": "persisted"}]
    backend2.close()


def test_findings_shelve_backend_end_to_end(tmp_path: Path):
    with FindingsPersistence(tmp_path, backend="shelve") as store:
        store.record_findings(
            "run-1", [{"claim": "eval usage", "branch": "x.a", "confidence": 0.9}]
        )
        store.record_findings(
            "run-2", [{"claim": "eval usage", "branch": "x.a", "confidence": 0.9}]
        )
        persistent = store.get_persistent_findings(min_runs=2)
        assert len(persistent) == 1
        assert persistent[0]["run_count"] == 2


def test_record_findings_skips_blank_claims(tmp_path: Path):
    store = FindingsPersistence(tmp_path, backend="json")
    result = store.record_findings(
        "run-1",
        [
            {"claim": "real finding", "branch": "x.a", "confidence": 0.8},
            {"claim": "", "branch": "x.b", "confidence": 0.5},
            {"branch": "x.c"},
        ],
    )
    # Only the non-blank claim is tracked.
    assert result["total_tracked"] == 1


def test_resolved_findings_collected(tmp_path: Path):
    store = FindingsPersistence(tmp_path, backend="json")
    store.record_findings("run-1", [{"claim": "old issue", "branch": "x.a", "confidence": 0.7}])
    store.update_claim_status("old issue", ClaimStatus.RESOLVED)
    resolved = store.get_resolved_findings()
    assert len(resolved) == 1
    assert resolved[0]["claim"] == "old issue"


def test_update_claim_status_noop_when_absent(tmp_path: Path):
    store = FindingsPersistence(tmp_path, backend="json")
    store.record_findings("run-1", [{"claim": "kept", "branch": "x.a", "confidence": 0.7}])
    store.update_claim_status("missing", ClaimStatus.RESOLVED)
    assert store.get_open_claims()[0]["status"] == ClaimStatus.OPEN


def test_export_state_writes_file(tmp_path: Path):
    store = FindingsPersistence(tmp_path, backend="json")
    store.record_findings("run-1", [{"claim": "exported", "branch": "x.a", "confidence": 0.7}])
    out = tmp_path / "backup.json"
    raw = store.export_state(out)
    assert out.exists()
    parsed = json.loads(raw)
    assert parsed["claim_tracker"][0]["claim"] == "exported"


def test_export_state_returns_string_without_path(tmp_path: Path):
    store = FindingsPersistence(tmp_path, backend="json")
    raw = store.export_state()
    assert isinstance(raw, str)
    assert "claim_tracker" in raw


def test_import_state_roundtrip(tmp_path: Path):
    store = FindingsPersistence(tmp_path, backend="json")
    payload = json.dumps(
        {
            "schema_version": 1,
            "claim_tracker": [
                {"claim": "imported", "status": ClaimStatus.OPEN, "first_seen_run": "run-1"}
            ],
            "runs": [],
        }
    )
    store.import_state(payload)
    assert store.get_open_claims()[0]["claim"] == "imported"


def test_import_state_rejects_non_dict(tmp_path: Path):
    store = FindingsPersistence(tmp_path, backend="json")
    with pytest.raises(ValueError, match="Invalid state JSON"):
        store.import_state(json.dumps([1, 2, 3]))


def test_build_recall_prompt_empty_and_populated(tmp_path: Path):
    store = FindingsPersistence(tmp_path, backend="json")
    assert store.build_recall_prompt() == "No previously identified open issues on record."
    store.record_findings("run-1", [{"claim": "guard missing", "branch": "x.a", "confidence": 0.9}])
    prompt = store.build_recall_prompt()
    assert "guard missing" in prompt
    assert "Previously identified issues:" in prompt


def test_shelve_backend_load_recovers_when_open_fails(tmp_path: Path, monkeypatch):
    backend = _ShelveBackend(tmp_path / "findings_db")

    import app.memory.findings_persistence as fp

    def boom(*args, **kwargs):
        raise OSError("cannot open shelve")

    monkeypatch.setattr(fp.shelve, "open", boom)
    # _ensure_open raises -> except branch -> default state.
    assert backend.load()["claim_tracker"] == []


def test_find_confidence_helper_edges():
    findings = [{"claim": "X", "confidence": 0.42}]
    assert FindingsPersistence._find_confidence(findings, "x") == 0.42
    assert FindingsPersistence._find_confidence(findings, "absent") == 0.0
