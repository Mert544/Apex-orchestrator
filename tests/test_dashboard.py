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
