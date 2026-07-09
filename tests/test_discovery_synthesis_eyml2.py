"""Discovery synthesis — per-engine normalizers + I/O edges (eyml2 wave).

The first wave pinned the end-to-end fusion; this wave drives the individual
``_*_leads`` normalizers and the best-effort I/O helpers through their error and
skip branches DIRECTLY (engine edges stubbed, a tiny real tree for
``_gather_sources``). Deterministic, offline, stdlib + pytest only.
"""

from __future__ import annotations

import pytest

from app.engine import discovery_synthesis as ds
from app.engine.discovery_synthesis import (
    ANOMALY_SOURCE,
    RULE_SOURCE,
    TEMPORAL_SOURCE,
)


# --- tiny numeric / string helpers ----------------------------------------- #
def test_clamp_negative_is_zero():
    assert ds._clamp(-0.5) == 0.0


def test_pair_subject_is_canonical_regardless_of_order():
    assert ds._pair_subject("b", "a") == "a | b"
    assert ds._pair_subject("a", "b") == ds._pair_subject("b", "a")


# --- _build_profile: best-effort degrade to None --------------------------- #
def test_build_profile_degrades_to_none_on_error(monkeypatch):
    class _Boom:
        def __init__(self, root):
            pass

        def profile(self):
            raise RuntimeError("scan failed")

    import app.tools.project_profile as pp
    monkeypatch.setattr(pp, "ProjectProfiler", _Boom)
    assert ds._build_profile("anywhere") is None


# --- _gather_sources: skip set + unreadable entry -------------------------- #
def test_gather_sources_skips_dirs_and_unreadable_entries(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "ok.py").write_text("x = 1\n", encoding="utf-8")
    # A DIRECTORY named like a module: rglob matches it, read_text raises OSError.
    (app / "weird.py").mkdir()
    # A file inside a skipped directory: dropped by is_skipped.
    skipped = app / "node_modules"
    skipped.mkdir()
    (skipped / "vendor.py").write_text("y = 2\n", encoding="utf-8")

    sources = ds._gather_sources(str(tmp_path))
    assert list(sources) == ["app/ok.py"]


def test_gather_sources_missing_app_dir_is_empty(tmp_path):
    assert ds._gather_sources(str(tmp_path)) == {}


def test_gather_sources_non_path_root_degrades_to_empty():
    # A root that cannot even be turned into a Path (None) trips the outer
    # best-effort guard rather than raising.
    assert ds._gather_sources(None) == {}


# --- _anomaly_leads -------------------------------------------------------- #
def test_anomaly_leads_none_profile_is_empty():
    assert ds._anomaly_leads(None) == []


def test_anomaly_leads_engine_error_is_empty(monkeypatch):
    def _boom(profile):
        raise RuntimeError("anomaly engine failed")

    monkeypatch.setattr(ds.anomaly_discovery, "find_anomalies", _boom)
    assert ds._anomaly_leads(object()) == []


def test_anomaly_leads_skips_blank_module_and_normalizes(monkeypatch):
    monkeypatch.setattr(ds.anomaly_discovery, "find_anomalies", lambda profile: [
        {"module": "", "deviation": 0.9, "why": "ignored"},
        {"module": "app/m.py", "deviation": 0.5, "why": "off-pattern"},
    ])
    leads = ds._anomaly_leads(object())
    assert len(leads) == 1
    lead = leads[0]
    assert lead["subject"] == "app/m.py"
    assert lead["kind"] == "anomaly"
    assert lead["source"] == ANOMALY_SOURCE
    assert lead["score"] == 0.5
    assert lead["evidence"] == "off-pattern"


# --- _hotspot_leads -------------------------------------------------------- #
def test_hotspot_leads_engine_error_is_empty(monkeypatch):
    def _boom(root):
        raise RuntimeError("temporal engine failed")

    monkeypatch.setattr(ds.temporal_discovery, "emerging_hotspots", _boom)
    assert ds._hotspot_leads("root") == []


def test_hotspot_leads_skips_blank_module_and_normalizes(monkeypatch):
    monkeypatch.setattr(ds.temporal_discovery, "emerging_hotspots", lambda root: [
        {"module": "", "recent": 9, "older": 0},
        {"module": "app/hot.py", "recent": 5, "older": 1},
    ])
    leads = ds._hotspot_leads("root")
    assert len(leads) == 1
    lead = leads[0]
    assert lead["subject"] == "app/hot.py"
    assert lead["kind"] == "emerging-hotspot"
    assert lead["source"] == TEMPORAL_SOURCE
    assert lead["score"] == 0.4  # (5 - 1) / 10.0


# --- _pair_leads ----------------------------------------------------------- #
def test_pair_leads_engine_error_is_empty(monkeypatch):
    def _boom(root):
        raise RuntimeError("pair engine failed")

    monkeypatch.setattr(ds.temporal_discovery, "spreading_pairs", _boom)
    assert ds._pair_leads("root") == []


def test_pair_leads_skips_incomplete_pair_and_normalizes(monkeypatch):
    monkeypatch.setattr(ds.temporal_discovery, "spreading_pairs", lambda root: [
        {"a": "", "b": "app/x.py", "recent": 9, "older": 0, "cochanges": 9},
        {"a": "app/z.py", "b": "app/y.py", "recent": 8, "older": 2, "cochanges": 3},
    ])
    leads = ds._pair_leads("root")
    assert len(leads) == 1
    lead = leads[0]
    assert lead["subject"] == "app/y.py | app/z.py"
    assert lead["kind"] == "spreading-pair"
    assert lead["source"] == TEMPORAL_SOURCE
    assert lead["score"] == 0.6  # (8 - 2) / 10.0
    assert "3 total" in lead["evidence"]


# --- _rule_leads ----------------------------------------------------------- #
def test_rule_leads_empty_sources_is_empty():
    assert ds._rule_leads({}) == []


def test_rule_leads_engine_error_is_empty(monkeypatch):
    def _boom(sources):
        raise RuntimeError("rule engine failed")

    monkeypatch.setattr(ds.rule_synthesis, "propose_rules", _boom)
    assert ds._rule_leads({"a.py": "x = 1\n"}) == []


def test_rule_leads_skips_blank_shape_and_normalizes(monkeypatch):
    monkeypatch.setattr(ds.rule_synthesis, "propose_rules", lambda sources: [
        {"shape": "", "support": 9},
        {"shape": "Return[C:int]", "support": 6},
    ])
    leads = ds._rule_leads({"a.py": "x = 1\n"})
    assert len(leads) == 1
    lead = leads[0]
    assert lead["subject"] == "Return[C:int]"
    assert lead["kind"] == "candidate-rule"
    assert lead["source"] == RULE_SOURCE
    assert lead["score"] == 0.5  # 6 / 12.0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
