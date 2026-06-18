"""Feature tests for ``app/engine/discovery_synthesis.py``.

Discovery synthesis FUSES Apex's three discovery engines (anomaly / temporal /
rule-synthesis) into one ranked, de-duplicated list of "discovery leads" with
provenance. It is read-only: it never seeds an idea or mutates planning state.

These tests pin the contract end-to-end:

  - the EXACT normalized lead shape every engine maps to;
  - the corroboration-boost arithmetic AT ITS BOUNDARY (one vs two engines,
    and the clamp to 1.0);
  - exact de-dup behaviour (same subject+kind collapses, strongest kept);
  - the exact deterministic sort order ``(-score, kind, subject)``;
  - report counts (per source, per kind, corroborated, top slice);
  - exact markdown substrings;
  - the no-git / empty-root best-effort path yields ``[]`` and never raises.

A tiny fake project is built under ``tmp_path`` (a recurring pattern + an
anomalous module); the git parts are driven by a real, tiny in-tree git repo.
Synthetic inputs; stdlib + pytest only.
"""

from __future__ import annotations

import subprocess

import pytest

from app.engine import discovery_synthesis as ds
from app.engine.discovery_synthesis import (
    ANOMALY_SOURCE,
    CORROBORATION_BOOST,
    RULE_SOURCE,
    TEMPORAL_SOURCE,
    discovery_report,
    render_discoveries_markdown,
    synthesize_discoveries,
)
from app.tools.project_profile import ProjectProfile

_LEAD_KEYS = {"kind", "subject", "score", "source", "evidence", "corroborated_by"}


# --------------------------------------------------------------------------- #
# Helpers: build a tiny project + a tiny git repo deterministically.
# --------------------------------------------------------------------------- #
def _make_project(tmp_path):
    """A minimal ``app/`` tree: a recurring ``return None`` micro-pattern."""
    app = tmp_path / "app"
    app.mkdir()
    # Three sources each carrying the SAME mineable shape (>= min_support=3),
    # identifiers abstracted away, so rule_synthesis surfaces one candidate rule.
    for name in ("a", "b", "c", "d"):
        (app / f"{name}.py").write_text(
            "def f():\n"
            "    return None\n"
            "def g():\n"
            "    return None\n",
            encoding="utf-8",
        )
    return tmp_path


def _git(tmp_path, *args):
    subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True,
                   check=True)


def _make_git_repo(tmp_path):
    """Init a tiny repo with an OLDER then a RECENT commit touching a hotspot.

    ``app/hot.py`` is touched in BOTH commits but more in the recent half, so it
    emerges as an accelerating hotspot; a co-changing pair tightens too.
    """
    _make_project(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    app = tmp_path / "app"
    # Older commit.
    (app / "hot.py").write_text("x = 1\n", encoding="utf-8")
    (app / "side.py").write_text("y = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "older")
    # Recent commit touching the same files again (accelerating).
    (app / "hot.py").write_text("x = 2\n", encoding="utf-8")
    (app / "side.py").write_text("y = 2\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "recent")
    return tmp_path


# --------------------------------------------------------------------------- #
# Normalized lead shape — every lead from every engine is uniform.
# --------------------------------------------------------------------------- #
def test_every_lead_has_the_uniform_shape(tmp_path):
    _make_git_repo(tmp_path)
    leads = synthesize_discoveries(str(tmp_path))
    assert leads, "the fake project must surface at least one lead"
    for lead in leads:
        assert set(lead) == _LEAD_KEYS
        assert isinstance(lead["kind"], str) and lead["kind"]
        assert isinstance(lead["subject"], str) and lead["subject"]
        assert isinstance(lead["source"], str) and lead["source"]
        assert isinstance(lead["evidence"], str) and lead["evidence"]
        assert 0.0 <= lead["score"] <= 1.0
        # rounded to fixed precision
        assert lead["score"] == round(lead["score"], ds.ROUND_NDIGITS)
        assert lead["corroborated_by"] >= 1


def test_rule_synthesis_lead_is_normalized(tmp_path):
    _make_project(tmp_path)  # no git → only the rule engine produces leads
    leads = synthesize_discoveries(str(tmp_path))
    rule_leads = [lead for lead in leads if lead["source"] == RULE_SOURCE]
    assert rule_leads, "the recurring return-None pattern must mine a candidate rule"
    lead = rule_leads[0]
    assert lead["kind"] == "candidate-rule"
    assert "recurs across" in lead["evidence"] and "recommend-only" in lead["evidence"]


# --------------------------------------------------------------------------- #
# Corroboration boost — exact arithmetic at the boundary, with a clamp.
# --------------------------------------------------------------------------- #
def test_corroboration_boost_exact_arithmetic(monkeypatch):
    # One subject ("mod") is named by TWO engines (anomaly + temporal); another
    # ("solo") by ONE. We stub each engine edge so the math is exact.
    monkeypatch.setattr(ds, "_build_profile", lambda root: object())
    monkeypatch.setattr(ds, "_gather_sources", lambda root: {})
    monkeypatch.setattr(ds, "_anomaly_leads", lambda profile: [
        {"kind": "anomaly", "subject": "mod", "score": 0.4,
         "source": ANOMALY_SOURCE, "evidence": "x."},
        {"kind": "anomaly", "subject": "solo", "score": 0.5,
         "source": ANOMALY_SOURCE, "evidence": "y."},
    ])
    monkeypatch.setattr(ds, "_hotspot_leads", lambda root: [
        {"kind": "emerging-hotspot", "subject": "mod", "score": 0.4,
         "source": TEMPORAL_SOURCE, "evidence": "z."},
    ])
    monkeypatch.setattr(ds, "_pair_leads", lambda root: [])
    monkeypatch.setattr(ds, "_rule_leads", lambda sources: [])

    leads = synthesize_discoveries("ignored")
    by_subj = {(lead["subject"], lead["kind"]): lead for lead in leads}

    # "mod" is corroborated by 2 engines → factor 1 + 0.25*(2-1) = 1.25.
    assert CORROBORATION_BOOST == 0.25
    mod_anom = by_subj[("mod", "anomaly")]
    assert mod_anom["corroborated_by"] == 2
    assert mod_anom["score"] == round(0.4 * 1.25, ds.ROUND_NDIGITS)  # 0.5
    mod_hot = by_subj[("mod", "emerging-hotspot")]
    assert mod_hot["corroborated_by"] == 2
    assert mod_hot["score"] == round(0.4 * 1.25, ds.ROUND_NDIGITS)

    # "solo" is named by ONE engine → unchanged.
    solo = by_subj[("solo", "anomaly")]
    assert solo["corroborated_by"] == 1
    assert solo["score"] == round(0.5, ds.ROUND_NDIGITS)


def test_corroboration_boost_clamps_to_one(monkeypatch):
    # A subject named by two engines with a high base score must clamp at 1.0,
    # never exceed it (0.9 * 1.25 = 1.125 -> 1.0).
    monkeypatch.setattr(ds, "_build_profile", lambda root: object())
    monkeypatch.setattr(ds, "_gather_sources", lambda root: {})
    monkeypatch.setattr(ds, "_anomaly_leads", lambda profile: [
        {"kind": "anomaly", "subject": "big", "score": 0.9,
         "source": ANOMALY_SOURCE, "evidence": "x."},
    ])
    monkeypatch.setattr(ds, "_hotspot_leads", lambda root: [
        {"kind": "emerging-hotspot", "subject": "big", "score": 0.9,
         "source": TEMPORAL_SOURCE, "evidence": "z."},
    ])
    monkeypatch.setattr(ds, "_pair_leads", lambda root: [])
    monkeypatch.setattr(ds, "_rule_leads", lambda sources: [])

    leads = synthesize_discoveries("ignored")
    for lead in leads:
        assert lead["corroborated_by"] == 2
        assert lead["score"] == 1.0


# --------------------------------------------------------------------------- #
# De-dup — same (subject, kind) collapses, strongest kept; distinct engines on
# the same subject do NOT count as corroboration when re-reported under one kind.
# --------------------------------------------------------------------------- #
def test_dedup_keeps_strongest_for_same_subject_kind(monkeypatch):
    monkeypatch.setattr(ds, "_build_profile", lambda root: object())
    monkeypatch.setattr(ds, "_gather_sources", lambda root: {})
    monkeypatch.setattr(ds, "_anomaly_leads", lambda profile: [
        {"kind": "anomaly", "subject": "dup", "score": 0.3,
         "source": ANOMALY_SOURCE, "evidence": "weak."},
        {"kind": "anomaly", "subject": "dup", "score": 0.7,
         "source": ANOMALY_SOURCE, "evidence": "strong."},
    ])
    monkeypatch.setattr(ds, "_hotspot_leads", lambda root: [])
    monkeypatch.setattr(ds, "_pair_leads", lambda root: [])
    monkeypatch.setattr(ds, "_rule_leads", lambda sources: [])

    leads = synthesize_discoveries("ignored")
    dup = [lead for lead in leads if lead["subject"] == "dup"]
    assert len(dup) == 1, "same (subject, kind) must collapse to one lead"
    assert dup[0]["score"] == 0.7
    assert dup[0]["evidence"] == "strong."
    # Both leads came from ONE engine → no cross-engine corroboration.
    assert dup[0]["corroborated_by"] == 1


# --------------------------------------------------------------------------- #
# Deterministic sort order — (-score, kind, subject).
# --------------------------------------------------------------------------- #
def test_sort_order_is_score_then_kind_then_subject(monkeypatch):
    monkeypatch.setattr(ds, "_build_profile", lambda root: object())
    monkeypatch.setattr(ds, "_gather_sources", lambda root: {})
    monkeypatch.setattr(ds, "_anomaly_leads", lambda profile: [
        {"kind": "anomaly", "subject": "zzz", "score": 0.5,
         "source": ANOMALY_SOURCE, "evidence": "a."},
        {"kind": "anomaly", "subject": "aaa", "score": 0.5,
         "source": ANOMALY_SOURCE, "evidence": "b."},
    ])
    monkeypatch.setattr(ds, "_hotspot_leads", lambda root: [
        {"kind": "emerging-hotspot", "subject": "mmm", "score": 0.5,
         "source": TEMPORAL_SOURCE, "evidence": "c."},
        {"kind": "emerging-hotspot", "subject": "nnn", "score": 0.9,
         "source": TEMPORAL_SOURCE, "evidence": "d."},
    ])
    monkeypatch.setattr(ds, "_pair_leads", lambda root: [])
    monkeypatch.setattr(ds, "_rule_leads", lambda sources: [])

    leads = synthesize_discoveries("ignored")
    order = [(lead["kind"], lead["subject"]) for lead in leads]
    # 0.9 hotspot first; then the three 0.5 leads by (kind, subject):
    # anomaly/aaa, anomaly/zzz, emerging-hotspot/mmm.
    assert order == [
        ("emerging-hotspot", "nnn"),
        ("anomaly", "aaa"),
        ("anomaly", "zzz"),
        ("emerging-hotspot", "mmm"),
    ]
    assert leads == sorted(leads, key=ds._sort_key)


def test_deterministic_repeated_runs_identical(tmp_path):
    _make_git_repo(tmp_path)
    assert synthesize_discoveries(str(tmp_path)) == synthesize_discoveries(str(tmp_path))


# --------------------------------------------------------------------------- #
# Report — counts per source, per kind, corroborated, top slice.
# --------------------------------------------------------------------------- #
def test_report_counts_match_leads(monkeypatch):
    monkeypatch.setattr(ds, "_build_profile", lambda root: object())
    monkeypatch.setattr(ds, "_gather_sources", lambda root: {})
    monkeypatch.setattr(ds, "_anomaly_leads", lambda profile: [
        {"kind": "anomaly", "subject": "mod", "score": 0.4,
         "source": ANOMALY_SOURCE, "evidence": "a."},
    ])
    monkeypatch.setattr(ds, "_hotspot_leads", lambda root: [
        {"kind": "emerging-hotspot", "subject": "mod", "score": 0.4,
         "source": TEMPORAL_SOURCE, "evidence": "b."},
        {"kind": "emerging-hotspot", "subject": "lone", "score": 0.2,
         "source": TEMPORAL_SOURCE, "evidence": "c."},
    ])
    monkeypatch.setattr(ds, "_pair_leads", lambda root: [])
    monkeypatch.setattr(ds, "_rule_leads", lambda sources: [])

    report = discovery_report("ignored")
    assert report["total"] == 3
    # Only "mod" is named by >1 engine → its TWO leads are corroborated.
    assert report["corroborated"] == 2
    assert report["by_source"] == {ANOMALY_SOURCE: 1, TEMPORAL_SOURCE: 2}
    assert report["by_kind"] == {"anomaly": 1, "emerging-hotspot": 2}
    assert report["top"] == synthesize_discoveries("ignored")[:10]
    # by_source / by_kind are sorted dicts.
    assert list(report["by_source"]) == sorted(report["by_source"])
    assert list(report["by_kind"]) == sorted(report["by_kind"])


# --------------------------------------------------------------------------- #
# Markdown — exact substrings, pure formatting over the report.
# --------------------------------------------------------------------------- #
def test_markdown_contains_expected_substrings(tmp_path):
    _make_git_repo(tmp_path)
    md = render_discoveries_markdown(str(tmp_path))
    assert md.startswith("# Discovery synthesis — fused, ranked discovery leads")
    assert "## By source" in md
    assert "## By kind" in md
    assert "## Top 10 leads" in md
    assert "corroborated by >1 engine" in md


def test_markdown_empty_root_is_well_formed():
    md = render_discoveries_markdown("/tmp/__discovery_no_such_root__")
    assert md.startswith("# Discovery synthesis")
    assert "- _none_" in md
    assert "- _no discovery leads found_" in md


# --------------------------------------------------------------------------- #
# Best-effort / totality — no-git, empty, and missing roots yield [] safely.
# --------------------------------------------------------------------------- #
def test_no_git_root_yields_no_temporal_leads(tmp_path):
    # A project tree with sources but NO git repo: temporal engines degrade to []
    # (best-effort), so no temporal-source leads appear, but rule leads still do.
    _make_project(tmp_path)
    leads = synthesize_discoveries(str(tmp_path))
    assert all(lead["source"] != TEMPORAL_SOURCE for lead in leads)
    assert any(lead["source"] == RULE_SOURCE for lead in leads)


def test_missing_root_is_empty_and_never_raises():
    assert synthesize_discoveries("/tmp/__discovery_missing_root__") == []
    report = discovery_report("/tmp/__discovery_missing_root__")
    assert report == {
        "total": 0, "corroborated": 0,
        "by_source": {}, "by_kind": {}, "top": [],
    }


def test_explicit_profile_is_used_without_rebuild(tmp_path, monkeypatch):
    # When a profile is supplied, _build_profile must NOT be called.
    def _boom(root):  # pragma: no cover - asserts it isn't invoked
        raise AssertionError("_build_profile must not run when profile is given")

    monkeypatch.setattr(ds, "_build_profile", _boom)
    _make_project(tmp_path)
    profile = ProjectProfile(
        root=str(tmp_path),
        security_finding_modules=["app/a.py", "app/b.py", "app/c.py", "app/d.py"],
        untested_modules=["app/a.py", "app/b.py", "app/c.py", "app/d.py"],
        debt_marker_modules=["app/odd.py"],
        symbol_hubs=["app/odd.py"],
        mutable_default_modules=["app/odd.py"],
    )
    leads = synthesize_discoveries(str(tmp_path), profile=profile)
    anomaly_leads = [lead for lead in leads if lead["source"] == ANOMALY_SOURCE]
    assert anomaly_leads, "the supplied profile's anomaly must surface"
    assert any(lead["subject"] == "app/odd.py" for lead in anomaly_leads)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
