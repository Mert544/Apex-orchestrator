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


# --- (3b) develop-CORE capability scopes count as concrete -------------------
#
# The develop core ships under finer scopes than the broad `develop` umbrella
# (`stub-synthesis`, `implement-stub`, `wire-exports`, `type-hints`, ...). Each
# LANDS code (or directly gates a landed fill), so a feat/fix under it is
# concrete development — not "neutral". This is the fidelity fix the denetçi
# flagged on itself (windows of real landing work read as concrete=1, neutral=19).

@pytest.mark.parametrize(
    "subject",
    [
        "feat(stub-synthesis): mine indirect witnesses",
        "fix(stub-synthesis): honor src/ source roots",
        "fix(implement-stub): node-scope the apply gate",
        "feat(implement-stub): widen template space",
        "fix(tdd-implement): land from a failing test",
        "fix(stub): refuse thin multi-arg contracts",
        "fix(wire-exports): stop folding detail imports into __all__",
        "fix(type-hints): drop unsound param-from-default inference",
        "fix(infer-type-hints): land a return annotation",
        "fix(dataclassify): preserve class docstring",
        "feat(strengthen-tests): land an assertion witness",
        "fix(cover-gaps): land a test for an untested branch",
        "fix(usage-doc): pin PYTHONHASHSEED for determinism",
        "feat(generate-usage-doc): land USAGE.md",
        "fix(develop-session): scope tidy gating to impacted tests",
        "feat(percent-to-fstring): convert %-specs to f-strings",
        "fix(format-to-fstring): land a str.format rewrite",
        "fix(fstring-convert): land an implicit-concat f-string",
        "fix(test-shield): decline hash-seed-flaky value oracles",
        "fix(test_shield): emit hash-seed-stable canonical literal",
    ],
)
def test_develop_core_scopes_are_concrete(subject):
    assert nsa._classify_subject(subject) == "concrete"


@pytest.mark.parametrize(
    "subject",
    [
        # Autonomous-39: the idea->action bridge LANDS a former design_task move
        # through the verified-with-rollback compiler — a genuine concrete landing.
        "feat(bridge): land generalizable-duplication autonomously as extract-shared-helper",
        # The dream core's own scope for the `apex dream --land` landing chain — the
        # same LANDS-code capability already credited under `dream-develop`.
        "feat(dream): route landable confluence discoveries to executable objectives",
        "feat(dream): value-rank the confluence landing order",
        "fix(dream): wire dream --land landings into proof-of-fix",
    ],
)
def test_autonomous_landing_and_dream_chain_scopes_are_concrete(subject):
    # Fidelity, NOT inflation: these scopes LAND code via the verified-with-rollback
    # compiler. feat/fix(bridge) is rare (1 of the last 200 commits) and 5/6
    # feat/fix(dream) advance the landing chain, so crediting them corrects a
    # mis-bucketing of genuine landing rather than padding the concrete count.
    assert nsa._classify_subject(subject) == "concrete"


def test_develop_core_window_is_not_misbucketed_as_neutral(monkeypatch):
    # A window of real develop-core landing commits — the exact shape the denetçi
    # mis-reported as concrete=1 before the fix.
    subjects = [
        "fix(wire-exports): stop folding detail imports into __all__",
        "fix(stub-synthesis): mine indirect tests and witnesses",
        "fix(usage-doc): pin PYTHONHASHSEED so landed USAGE.md is deterministic",
        "fix(dataclassify): preserve class docstring",
        "fix(type-hints): drop unsound param-from-default inference",
        "fix(implement-stub): node-scope the apply gate",
        "feat(percent-to-fstring): convert %-specs to f-strings",
        "docs(rnd): market positioning package",  # honest neutral, not concrete
    ]
    monkeypatch.setattr(nsa, "_git_subjects", lambda *a, **k: subjects)
    window = nsa.commit_drift(".", 20)
    assert window["concrete"] == 7
    assert window["neutral"] == 1  # only the docs commit
    assert window["safety"] == 0
    assert window["drift"] is False


# --- (3c) the fix is HONEST, not inflationary --------------------------------
#
# Pure-meta / housekeeping scopes must STAY non-concrete or the metric becomes a
# way to inflate the concrete ratio rather than a faithful reading of reality.

@pytest.mark.parametrize(
    "subject",
    [
        "docs(rnd): research package",
        "docs: tweak readme",
        "ci: fetch full git history",
        "test(grade): characterization baseline",
        "test(cli): add a case",
        "chore: bump deps",
        "refactor(implement-stub): split a helper for complexity",  # type gate
        "perf(implement-stub): cheap in-process fitness scan",       # type gate
        "build(deps): pin pydantic",
        "feat(self-audit): denetçi reverse tripwire",  # auditor machinery, not landing
    ],
)
def test_housekeeping_and_meta_scopes_are_not_concrete(subject):
    assert nsa._classify_subject(subject) != "concrete"


def test_grade_scope_stays_safety_not_concrete():
    # `grade` is a trust-foundation scope — a feat/fix under it is SAFETY, never
    # concrete, so the fix can't quietly re-credit safety machinery as landing.
    assert nsa._classify_subject("fix(grade): count concrete-subclass stub debt") == "safety"


@pytest.mark.parametrize(
    "subject",
    [
        "fix(safety): harden the rollback",
        "fix(proof): tighten the proof carrier",
        "fix(shield): value-oracle stability",
        "fix(scope): scope_verify seam",
        "fix(architecture): hub fragility penalty",
        "fix(intelligence): auditor pass",
        "fix(fix-risk): risk gate",
    ],
)
def test_safety_scopes_stay_safety(subject):
    assert nsa._classify_subject(subject) == "safety"


def test_concrete_and_safety_scope_sets_are_disjoint():
    # No scope may live in both sets, or `_classify_subject`'s precedence (concrete
    # checked first) could mis-credit a safety commit as concrete.
    assert not (nsa._CONCRETE_SCOPES & nsa._SAFETY_SCOPES)


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
