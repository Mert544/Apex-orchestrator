"""Tests for the durable denetçi: `apex self-audit --north-star`.

Covers (per the spec): manifest completeness + honesty tripwire, ratio math,
the commit-drift rule (via the monkeypatchable git seam), the non-git
'unavailable' path, CLI exit codes + non-north-star byte-identity, and JSON
determinism (no wall-clock keys).
"""

from __future__ import annotations

import argparse

import pytest

from app.engine import north_star_audit as nsa
from app.engine.objective_compiler import available_objectives


# --- (1) completeness + honesty tripwire -------------------------------------

def test_classify_partitions_all_live_objectives():
    buckets = nsa.classify_objectives(available_objectives())
    union = buckets["CONCRETE"] | buckets["TIDY"] | buckets["SAFETY"]
    assert union == set(available_objectives())
    # The three buckets are disjoint.
    assert not (buckets["CONCRETE"] & buckets["TIDY"])
    assert not (buckets["CONCRETE"] & buckets["SAFETY"])
    assert not (buckets["TIDY"] & buckets["SAFETY"])


def test_classify_raises_on_unknown_objective():
    names = [*available_objectives(), "totally-new-self-registered-objective"]
    with pytest.raises(ValueError, match="manifest is stale"):
        nsa.classify_objectives(names)


# --- (2) ratio math on a fixed synthetic set ---------------------------------

def test_ratio_math_on_fixed_set(monkeypatch):
    # implement-stub, wire-exports = CONCRETE; modernize, dedup = TIDY → 2/4.
    fixed = ["implement-stub", "wire-exports", "modernize", "dedup"]
    monkeypatch.setattr(nsa, "_git_subjects", lambda *a, **k: None)

    import app.engine.objective_compiler as oc
    monkeypatch.setattr(oc, "available_objectives", lambda: list(fixed))

    report = nsa.north_star_report("/tmp/whatever", 20)
    assert report["concrete_ratio"] == pytest.approx(0.5)
    assert report["total_objectives"] == 4
    assert report["bucket_counts"] == {"CONCRETE": 2, "TIDY": 2, "SAFETY": 0}


# --- (3) drift rule via the monkeypatched git seam ---------------------------

def test_drift_when_only_safety(monkeypatch):
    monkeypatch.setattr(
        nsa, "_git_subjects",
        lambda *a, **k: ["fix(safety): x", "fix(proof): y"],
    )
    window = nsa.commit_drift(".", 20)
    assert window["concrete"] == 0
    assert window["safety"] == 2
    assert window["drift"] is True


def test_no_drift_when_one_concrete_present(monkeypatch):
    monkeypatch.setattr(
        nsa, "_git_subjects",
        lambda *a, **k: ["fix(safety): x", "feat(develop): land a stub", "fix(proof): y"],
    )
    window = nsa.commit_drift(".", 20)
    assert window["concrete"] == 1
    assert window["safety"] == 2
    assert window["drift"] is False


def test_neutral_subjects_never_drift(monkeypatch):
    monkeypatch.setattr(
        nsa, "_git_subjects",
        lambda *a, **k: ["chore: bump", "docs: tweak", "no-conventional-prefix"],
    )
    window = nsa.commit_drift(".", 20)
    assert window == {"concrete": 0, "safety": 0, "neutral": 3, "total": 3, "drift": False}


# --- (4) non-git path → unavailable, no exception ----------------------------

def test_non_git_root_returns_none(tmp_path):
    assert nsa.commit_drift(str(tmp_path), 20) is None


def test_report_handles_unavailable_window(monkeypatch):
    monkeypatch.setattr(nsa, "_git_subjects", lambda *a, **k: None)
    report = nsa.north_star_report("/tmp/not-a-repo", 20)
    assert report["commit_window"] is None
    assert report["drift"] is False
    assert report["verdict"] == "PASS"
    md = nsa.render_markdown(report, "/tmp/not-a-repo")
    assert "unavailable" in md


# --- (5) CLI: exit code + non-north-star byte-identity ------------------------

def test_cli_north_star_pass(monkeypatch, capsys):
    from app import cli_ops
    monkeypatch.setattr(
        nsa, "_git_subjects",
        lambda *a, **k: ["feat(develop): land a stub"],
    )
    args = argparse.Namespace(target=".", format="markdown", north_star=True, commits=20)
    assert cli_ops.cmd_self_audit(args) == 0
    out = capsys.readouterr().out
    assert "North Star" in out
    assert "PASS" in out


def test_cli_north_star_drift_exits_nonzero(monkeypatch, capsys):
    from app import cli_ops
    monkeypatch.setattr(nsa, "_git_subjects", lambda *a, **k: ["fix(safety): x"])
    args = argparse.Namespace(target=".", format="json", north_star=True, commits=20)
    assert cli_ops.cmd_self_audit(args) == 1
    out = capsys.readouterr().out
    assert '"verdict": "DRIFT"' in out


def test_cli_non_north_star_path_unchanged(monkeypatch, capsys):
    """Without --north-star, the legacy SelfAuditAgent path runs and returns 0."""
    from app import cli_ops

    class _FakeAgent:
        def run(self, project_root):
            return {"findings": [], "missing_docstrings_count": 0,
                    "long_functions_count": 0, "todos_count": 0, "coverage_gap": {}}

    import app.agents.skills.self_audit_agent as sa_mod
    monkeypatch.setattr(sa_mod, "SelfAuditAgent", _FakeAgent)
    args = argparse.Namespace(target=".", format="markdown", north_star=False, commits=20)
    assert cli_ops.cmd_self_audit(args) == 0
    out = capsys.readouterr().out
    assert "Apex Self-Audit Report" in out
    assert "North Star" not in out


def test_cli_missing_north_star_attr_uses_legacy(monkeypatch):
    """A Namespace without north_star at all defaults to the legacy path."""
    from app import cli_ops

    class _FakeAgent:
        def run(self, project_root):
            return {}

    import app.agents.skills.self_audit_agent as sa_mod
    monkeypatch.setattr(sa_mod, "SelfAuditAgent", _FakeAgent)
    args = argparse.Namespace(target=".", format="markdown")
    assert cli_ops.cmd_self_audit(args) == 0


# --- (6) JSON determinism — no wall-clock key leaks --------------------------

def test_report_keys_are_stable_and_clockless(monkeypatch):
    monkeypatch.setattr(nsa, "_git_subjects", lambda *a, **k: ["feat(develop): x"])
    r1 = nsa.north_star_report(".", 20)
    r2 = nsa.north_star_report(".", 20)
    assert r1 == r2  # pure function of repo state
    assert set(r1.keys()) == {
        "concrete_ratio", "buckets", "bucket_counts",
        "total_objectives", "commit_window", "drift", "verdict",
    }
    flat = repr(r1).lower()
    for forbidden in ("time", "date", "clock", "timestamp", "now", "epoch"):
        assert forbidden not in flat
