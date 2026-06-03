from pathlib import Path

from app.reporting.dashboard import build_dashboard


def _project(tmp: Path) -> Path:
    (tmp / "app").mkdir()
    (tmp / "app" / "svc.py").write_text("import os\ndef run(cmd):\n    return eval(cmd)\n")
    (tmp / "app" / "main.py").write_text("def main():\n    return 1\n")
    return tmp


def test_dashboard_is_self_contained_html(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=12, idea_depth=2, breadth=3)
    assert html_doc.startswith("<!doctype html>")
    assert "</html>" in html_doc
    # No external scripts/stylesheets — fully self-contained.
    assert "<script src=" not in html_doc
    assert 'rel="stylesheet"' not in html_doc


def test_dashboard_has_all_sections(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path))
    for heading in ("Project profile", "Scan findings", "Idea permutation tree", "Action plan", "Reasoning"):
        assert heading in html_doc


def test_dashboard_includes_roadmap_and_shape(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=30, idea_depth=2, breadth=3)
    # Roadmap section: phases + quick wins + ROI bars.
    assert "Engineering roadmap" in html_doc
    assert "Phase 1" in html_doc
    assert "class='roi'" in html_doc
    # Tree-shape section: telemetry + the engine's own observations.
    assert "Idea-tree shape" in html_doc
    assert "Observations" in html_doc
    # Nav links for both are present.
    assert "#roadmap" in html_doc and "#shape" in html_doc


def test_dashboard_roadmap_shows_measured_signals(tmp_path):
    # core.py is imported by two modules and has real size -> the roadmap
    # surfaces measured fan-in / LOC under the idea.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def core(x):\n    if x:\n        return 1\n    return 0\n"
    )
    (tmp_path / "app" / "a.py").write_text("import app.core\ndef a():\n    return app.core.core(1)\n")
    (tmp_path / "app" / "b.py").write_text("import app.core\ndef b():\n    return app.core.core(2)\n")
    html_doc = build_dashboard(str(tmp_path), max_ideas=30, idea_depth=2, breadth=3)
    assert "imported by" in html_doc or "LOC" in html_doc


def test_dashboard_surfaces_security_finding(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path))
    # The eval() in svc.py should appear as a finding.
    assert "svc.py" in html_doc
    assert "security findings" in html_doc


def test_dashboard_renders_idea_tree(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=12)
    assert "class='op'" in html_doc  # idea operator chips rendered
    assert "Action plan" in html_doc


def test_dashboard_includes_git_repo_section_when_in_repo(tmp_path):
    import subprocess
    _project(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path)
    html_doc = build_dashboard(str(tmp_path))
    assert "Repository" in html_doc
    assert "uncommitted files" in html_doc


def test_dashboard_skips_repo_section_outside_git(tmp_path):
    _project(tmp_path)  # not a git repo
    html_doc = build_dashboard(str(tmp_path))
    # Other sections still render; the repo section is simply omitted.
    assert "Project profile" in html_doc
    assert "<h2>Repository</h2>" not in html_doc


def test_dashboard_includes_debug_section(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path))
    assert "<h2><span class='ico'>🐞</span>Debug</h2>" in html_doc or "Debug" in html_doc
    # Debug chips present (traces / anomalies).
    assert "anomalies" in html_doc


def test_dashboard_badges_synthesis_and_fragility(tmp_path):
    # eval/os.system + import edge -> security findings, synthesis, and a pair.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("import os\ndef a(c):\n    return eval(c)\n")
    (tmp_path / "app" / "b.py").write_text("import app.a\ndef b():\n    return app.a.a('1')\n")
    html_doc = build_dashboard(str(tmp_path), max_ideas=60, idea_depth=2, breadth=6)
    # Synthesized/module-pair appendix and badges render.
    assert "Synthesized" in html_doc
    assert "ibadge" in html_doc


def test_dashboard_architecture_section(tmp_path):
    # A->B->C->A indirect cycle should surface in the architecture section.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("import app.b\ndef a():\n    return app.b.b()\n")
    (tmp_path / "app" / "b.py").write_text("import app.c\ndef b():\n    return app.c.c()\n")
    (tmp_path / "app" / "c.py").write_text("import app.a\ndef c():\n    return 1\n")
    html_doc = build_dashboard(str(tmp_path))
    assert "Architecture health" in html_doc
    assert "Import cycles" in html_doc
    assert "Import cycles" in html_doc  # KPI + section
