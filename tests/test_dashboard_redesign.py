"""Guards for the dark-theme dashboard redesign: it must stay 100%
self-contained (no external URL/script/stylesheet), keep its single page
timestamp, expose the new theme hooks, and still render every existing
section anchor and title on a populated dashboard."""
import re

from app.reporting.dashboard import build_dashboard


def _project(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "svc.py").write_text(
        "import os\n\n\ndef run(cmd):\n    return os.system(cmd)\n\n\ndef handler(e):\n    return eval(e)\n"
    )
    (app / "util.py").write_text("def helper(x):\n    return x + 1\n")
    return tmp_path


def test_redesign_is_self_contained(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=20, idea_depth=2, breadth=3, quality=False)
    assert html_doc.startswith("<!doctype html>")
    assert "</html>" in html_doc
    # No external scripts/stylesheets or any remote URL — inline only. The inline
    # SVG charts declare the SVG namespace (`xmlns="http://www.w3.org/2000/svg"`),
    # which is a spec-mandated identifier the browser never fetches — strip those
    # namespace declarations before asserting there is no real remote resource.
    assert "<script src=" not in html_doc
    assert 'rel="stylesheet"' not in html_doc
    without_ns = html_doc.replace('xmlns="http://www.w3.org/2000/svg"', "")
    assert "http://" not in without_ns and "https://" not in without_ns
    assert "//fonts." not in html_doc and "cdn" not in html_doc.lower()
    # Theme/markup is inline <style>/<svg> only.
    assert "<style>" in html_doc and "<svg" in html_doc


def test_redesign_theme_hooks_present(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=20, idea_depth=2, breadth=3, quality=False)
    # Dark-theme palette + new shell hooks introduced by the redesign.
    assert "--accent:#3de2c4" in html_doc
    assert "class='eyebrow'" in html_doc
    assert "class='mark'" in html_doc
    assert "class='pulse'" in html_doc
    # System font stack, no web fonts.
    assert "system-ui" in html_doc
    assert "@import" not in html_doc


def test_redesign_keeps_single_timestamp(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=20, idea_depth=2, breadth=3, quality=False)
    # Exactly one rendered "UTC" stamp, emitted in the hero.
    stamps = re.findall(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", html_doc)
    assert len(stamps) == 1
    assert "class='stamp'" in html_doc


def test_redesign_keeps_footer_signature(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=20, idea_depth=2, breadth=3, quality=False)
    assert "signed by" in html_doc
    assert "barzeuss" in html_doc


def test_redesign_preserves_section_titles(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=40, idea_depth=2, breadth=4, quality=False)
    # Stable titles that must survive any container restyle.
    for title in (
        "Scan findings",
        "Architecture health",
        "Idea permutation tree",
        "Engineering roadmap",
        "Action plan",
        "Reasoning &amp; telemetry",
        "Project profile",
    ):
        assert title in html_doc
    # The <h2><span class='ico'>…</span>Title</h2> structure stays intact.
    assert "<span class='ico'>" in html_doc


def test_redesign_preserves_section_anchors(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=40, idea_depth=2, breadth=4, quality=False)
    for anchor in ("overview", "findings", "architecture", "ideas", "roadmap",
                   "actions", "reasoning", "profile"):
        assert f"id='{anchor}'" in html_doc
        assert f"#{anchor}" in html_doc
