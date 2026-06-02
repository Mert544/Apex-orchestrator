from app.reporting.visual_reports import ProgressDashboard, VisualReportGenerator


def _data():
    return {
        "runs_compared": 2,
        "date_range": {"start": "2026-01-01", "end": "2026-01-02"},
        "summary": {
            "avg_duration_seconds": 1.5,
            "total_patches_applied": 6,
            "total_patches_blocked": 2,
            "test_pass_rate": 90.0,
            "safety_gate_pass_rate": 100.0,
        },
        "trend": {"patches": "up", "tests": "stable"},
        "runs": [
            {"run_id": "r1", "mode": "report", "goal": "g", "patches_applied": 3,
             "tests_passed": True, "duration_seconds": 1.0},
            {"run_id": "r2", "mode": "supervised", "goal": "g2", "patches_applied": 3,
             "tests_passed": False, "duration_seconds": 2.0},
        ],
    }


def test_generate_report_full(tmp_path):
    gen = VisualReportGenerator(project_root=str(tmp_path))
    md = gen.generate_report(_data())
    assert "Apex Run Comparison Report" in md
    assert "Total Patches Applied: 6" in md
    assert "Activity Chart" in md
    assert "r1" in md and "r2" in md


def test_generate_report_error_path(tmp_path):
    gen = VisualReportGenerator(project_root=str(tmp_path))
    md = gen.generate_report({"error": "no runs"})
    assert md.startswith("# Error")
    assert "no runs" in md


def test_save_report_writes_file(tmp_path):
    gen = VisualReportGenerator(project_root=str(tmp_path))
    path = gen.save_report(_data(), filename="r.md")
    assert path.exists()
    assert "Apex Run Comparison Report" in path.read_text()


def test_save_report_auto_filename(tmp_path):
    gen = VisualReportGenerator(project_root=str(tmp_path))
    path = gen.save_report(_data())
    assert path.suffix == ".md"
    assert path.exists()


def test_progress_dashboard_render():
    out = ProgressDashboard().render({"runs": 5, "rate": 0.9})
    assert "APEX PROGRESS DASHBOARD" in out
    assert "runs" in out
    assert "rate" in out


def test_render_bar_normal_and_zero():
    d = ProgressDashboard()
    bar = d.render_bar("cov", 3, 4)
    assert "75.0%" in bar
    assert "(3/4)" in bar
    assert d.render_bar("x", 0, 0) == "x: [no data]"
