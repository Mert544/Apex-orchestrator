"""Temporal convergence: is the hotspot getting WORSE? (an Apex original)."""

from __future__ import annotations

from app.engine.signal_trends import SignalTrends
from app.tools.project_profile import ProjectProfile


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def test_no_baseline_means_no_trends(tmp_path):
    trends = SignalTrends(tmp_path)
    profile = _profile(churn_hotspots=[{"module": "app/x.py", "commits": 9}],
                       debt_marker_ages={"app/x.py": 400})
    assert trends.accelerating(profile) == []  # one observation has no slope


def test_rising_churn_with_aging_risk_accelerates(tmp_path):
    trends = SignalTrends(tmp_path)
    trends.record(_profile(churn_hotspots=[{"module": "app/x.py", "commits": 6},
                                           {"module": "app/calm.py", "commits": 6}],
                           debt_marker_ages={"app/x.py": 380}))
    now = _profile(
        churn_hotspots=[{"module": "app/x.py", "commits": 11},     # rose by 5
                        {"module": "app/calm.py", "commits": 6},   # flat
                        {"module": "app/new.py", "commits": 9}],   # no baseline
        debt_marker_ages={"app/x.py": 400},
    )
    accel = trends.accelerating(now)
    assert [a["module"] for a in accel] == ["app/x.py"]
    assert accel[0]["churn_before"] == 6 and accel[0]["churn_now"] == 11
    assert accel[0]["aging"] == ["debt"]


def test_rising_churn_without_aging_risk_is_just_activity(tmp_path):
    trends = SignalTrends(tmp_path)
    trends.record(_profile(churn_hotspots=[{"module": "app/busy.py", "commits": 4}]))
    now = _profile(churn_hotspots=[{"module": "app/busy.py", "commits": 12}])
    assert trends.accelerating(now) == []  # healthy development, not decay


def test_corrupt_history_is_silent(tmp_path):
    trends = SignalTrends(tmp_path)
    trends.path.parent.mkdir(parents=True)
    trends.path.write_text("{not json", encoding="utf-8")
    assert trends.accelerating(_profile()) == []


def test_accelerating_module_narrates_and_converges(tmp_path):
    # End to end inside the engine: with a recorded baseline, the churn seed
    # narrates the slope and convergence gains the time dimension.
    from app.engine.idea_permutation import IdeaPermutationEngine

    (tmp_path / "app").mkdir()
    hot = tmp_path / "app" / "hot.py"
    hot.write_text("# TODO: a\n# FIXME: b\n# XXX: c\ndef f():\n    return 1\n")

    import os
    import subprocess

    def _git(*args: str, date: str = "") -> None:
        env = dict(os.environ)
        if date:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, env=env)

    _git("init", "-q")
    _git("config", "user.email", "t@t.com")
    _git("config", "user.name", "t")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "old",
         date="2025-06-01T12:00:00 +0000")
    for i in range(5):
        hot.write_text(f"# TODO: a\n# FIXME: b\n# XXX: c\ndef f():\n    return {i}\n")
        _git("add", "-A")
        _git("-c", "commit.gpgsign=false", "commit", "-qm", f"c{i}",
             date="2026-06-01T12:00:00 +0000")

    # Baseline: pretend the last run saw less churn on the same aging module.
    SignalTrends(tmp_path).record(_profile(
        churn_hotspots=[{"module": "app/hot.py", "commits": 3}],
        debt_marker_ages={"app/hot.py": 380},
    ))

    report = IdeaPermutationEngine(
        {"max_total_ideas": 30, "max_idea_depth": 1}, tmp_path).run()
    # The annotation rides on WHICHEVER root claimed the subject (here the
    # debt root wins the seeding order) — the slope is part of the fact.
    claimed = next(i for i in report.ideas
                   if i.operator == "root" and i.subject == "app/hot.py")
    assert "accelerating: 3→" in claimed.title and "risk ages" in claimed.title
    assert "(accelerating 3→" in claimed.source_facts[0]
    conv = [i for i in report.ideas
            if i.source_facts and i.source_facts[0].startswith("convergence:")]
    assert any("accelerating" in i.source_facts[0] for i in conv)
