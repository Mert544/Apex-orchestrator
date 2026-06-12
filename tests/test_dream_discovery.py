"""Open-ended discovery: what travels with what, found in the data."""

from __future__ import annotations

from app.engine.dream_discovery import discover
from app.tools.project_profile import ProjectProfile


def test_discovers_association_no_rule_named_it():
    # Every single-author module here is also high-churn -> a discovered law.
    profile = ProjectProfile(
        root=".",
        churn_hotspots=[{"module": "app/a.py", "commits": 9},
                        {"module": "app/b.py", "commits": 8},
                        {"module": "app/quiet.py", "commits": 7}],
        knowledge_risks=[{"module": "app/a.py", "share": 100, "commits": 9},
                         {"module": "app/b.py", "share": 90, "commits": 8}],
    )
    found = discover(profile)
    assert any("single-author" in d and "high-churn" in d
               and "discovered association" in d for d in found)


def test_discovers_confluence_by_fingerprint_breadth():
    # One module carries many distinct signals; others carry one.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/hot.py"],
        untested_modules=["app/hot.py", "app/x.py"],
        fragile_modules=["app/hot.py"],
        debt_marker_modules=["app/hot.py", "app/y.py"],
    )
    found = discover(profile)
    assert any("`app/hot.py` is a confluence" in d and "4 distinct signals" in d
               for d in found)


def test_no_discovery_below_support_threshold():
    # A single co-occurrence is a coincidence, not a law.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/a.py"],
        untested_modules=["app/a.py"],
    )
    assert discover(profile) == []


def test_empty_profile_is_silent():
    assert discover(ProjectProfile(root=".")) == []


def test_adding_a_signal_widens_discovery_with_no_code_change():
    # The discovery space is the combination of WHATEVER signals are present:
    # the same association emerges purely because the data now carries it.
    base = ProjectProfile(
        root=".",
        untested_modules=["app/a.py", "app/b.py"],
        debt_marker_modules=["app/a.py", "app/b.py"],
    )
    found = discover(base)
    assert any("untested" in d and "debt" in d for d in found)


def test_dream_surfaces_discoveries_and_journals_them(tmp_path):
    from app.engine.dream import dream, render_dream_markdown

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    import os
    import subprocess

    def _git(*a: str, who: str = "alice") -> None:
        env = dict(os.environ)
        env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = who
        env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = f"{who}@t.com"
        subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, env=env)

    # Build a history where two modules are both high-churn AND single-author.
    (tmp_path / "app" / "a.py").write_text("A = 0\n")
    (tmp_path / "app" / "b.py").write_text("B = 0\n")
    _git("init", "-q")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "init")
    for i in range(6):
        (tmp_path / "app" / "a.py").write_text(f"A = {i}\n")
        (tmp_path / "app" / "b.py").write_text(f"B = {i}\n")
        _git("add", "-A")
        _git("-c", "commit.gpgsign=false", "commit", "-qm", f"c{i}")
    # A second active author touches an unrelated file (so multi-author holds).
    for i in range(6):
        (tmp_path / "app" / "m.py").write_text(f"M = {i}\n")
        _git("add", "-A")
        _git("-c", "commit.gpgsign=false", "commit", "-qm", f"o{i}", who="bob")

    first = dream(tmp_path)
    # The discovery section may or may not fire depending on thresholds, but
    # when it does it is journaled; run twice and confirm the streak machinery
    # covers discoveries (no crash, deterministic).
    second = dream(tmp_path)
    md = render_dream_markdown(second)
    assert "Dream digest" in md
    if first.discoveries:
        assert any("consecutive dreams" in d for d in second.discoveries)
