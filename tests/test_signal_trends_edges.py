"""Edge paths for SignalTrends: record I/O failures, security aging, boundaries."""

from __future__ import annotations

from pathlib import Path

from app.engine.signal_trends import RISE_THRESHOLD, SignalTrends
from app.tools.project_profile import ProjectProfile


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def test_load_missing_file_returns_none(tmp_path: Path):
    trends = SignalTrends(tmp_path)
    assert trends.load() is None  # no file yet -> no baseline


def test_record_then_load_round_trips(tmp_path: Path):
    trends = SignalTrends(tmp_path)
    trends.record(_profile(
        churn_hotspots=[{"module": "app/x.py", "commits": 7}],
        debt_marker_ages={"app/x.py": 120},
        security_finding_ages={"app/y.py": 200},
    ))
    loaded = trends.load()
    assert loaded is not None
    assert loaded["churn"] == {"app/x.py": 7}
    assert loaded["debt_ages"] == {"app/x.py": 120}
    assert loaded["security_ages"] == {"app/y.py": 200}
    assert "generated" in loaded


def test_record_swallows_oserror(tmp_path: Path, monkeypatch):
    # mkdir/write fails -> the OSError branch is hit and silently ignored.
    trends = SignalTrends(tmp_path)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", boom)
    trends.record(_profile(churn_hotspots=[{"module": "app/x.py", "commits": 3}]))
    # No history persisted, so accelerating stays empty.
    assert trends.load() is None


def test_security_aging_alone_accelerates(tmp_path: Path):
    # Exercises the security-aging branch (line 74) independent of debt.
    trends = SignalTrends(tmp_path)
    trends.record(_profile(
        churn_hotspots=[{"module": "app/sec.py", "commits": 4}],
        security_finding_ages={"app/sec.py": 95},
    ))
    accel = trends.accelerating(_profile(
        churn_hotspots=[{"module": "app/sec.py", "commits": 10}],
        security_finding_ages={"app/sec.py": 120},
    ))
    assert [a["module"] for a in accel] == ["app/sec.py"]
    assert accel[0]["aging"] == ["security"]


def test_both_debt_and_security_aging_listed(tmp_path: Path):
    trends = SignalTrends(tmp_path)
    trends.record(_profile(
        churn_hotspots=[{"module": "app/both.py", "commits": 5}],
        debt_marker_ages={"app/both.py": 90},
        security_finding_ages={"app/both.py": 90},
    ))
    accel = trends.accelerating(_profile(
        churn_hotspots=[{"module": "app/both.py", "commits": 9}],
        debt_marker_ages={"app/both.py": 91},
        security_finding_ages={"app/both.py": 91},
    ))
    assert accel[0]["aging"] == ["debt", "security"]


def test_rise_below_threshold_is_ignored(tmp_path: Path):
    # A rise of exactly RISE_THRESHOLD-1 is noise and must not register.
    trends = SignalTrends(tmp_path)
    trends.record(_profile(
        churn_hotspots=[{"module": "app/n.py", "commits": 5}],
        debt_marker_ages={"app/n.py": 365},
    ))
    accel = trends.accelerating(_profile(
        churn_hotspots=[{"module": "app/n.py", "commits": 5 + RISE_THRESHOLD - 1}],
        debt_marker_ages={"app/n.py": 365},
    ))
    assert accel == []


def test_rise_at_threshold_with_young_risk_is_ignored(tmp_path: Path):
    # Churn rose enough, but the risk is younger than 90 days -> not accelerating.
    trends = SignalTrends(tmp_path)
    trends.record(_profile(
        churn_hotspots=[{"module": "app/y.py", "commits": 5}],
        debt_marker_ages={"app/y.py": 89},
    ))
    accel = trends.accelerating(_profile(
        churn_hotspots=[{"module": "app/y.py", "commits": 20}],
        debt_marker_ages={"app/y.py": 89},
    ))
    assert accel == []


def test_accelerating_sorted_by_delta_then_module(tmp_path: Path):
    trends = SignalTrends(tmp_path)
    trends.record(_profile(
        churn_hotspots=[{"module": "app/a.py", "commits": 1},
                        {"module": "app/b.py", "commits": 1}],
        debt_marker_ages={"app/a.py": 100, "app/b.py": 100},
    ))
    accel = trends.accelerating(_profile(
        churn_hotspots=[{"module": "app/a.py", "commits": 5},    # delta 4
                        {"module": "app/b.py", "commits": 11}],  # delta 10
        debt_marker_ages={"app/a.py": 100, "app/b.py": 100},
    ))
    # Larger delta first.
    assert [a["module"] for a in accel] == ["app/b.py", "app/a.py"]


def test_empty_baseline_dict_means_no_trends(tmp_path: Path):
    # A history file present but with an empty churn map -> nothing to compare.
    trends = SignalTrends(tmp_path)
    trends.path.parent.mkdir(parents=True)
    trends.path.write_text('{"churn": {}}', encoding="utf-8")
    accel = trends.accelerating(_profile(
        churn_hotspots=[{"module": "app/x.py", "commits": 99}],
        debt_marker_ages={"app/x.py": 999},
    ))
    assert accel == []
