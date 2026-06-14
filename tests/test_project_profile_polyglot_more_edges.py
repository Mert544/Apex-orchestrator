"""Edge coverage for the polyglot-hotspot scan on ProjectProfiler:
``_scan_polyglot_hotspots`` and its Apex-report self-filter ``_is_apex_report``.

test_polyglot_seeding.py pins the happy paths (field populated, cap, hand-written
HTML kept, Apex-report HTML filtered, all-Python empty). This file closes the
remaining branches:
  - ``_is_apex_report`` on a NON-html path (early False) and on an UNREADABLE
    html path (OSError → False, line 506-507);
  - the Apex-report filter actually skipping a marked page while still yielding
    real hotspots beneath it (the ``continue`` + ``break`` interplay);
  - an HTML file too SHORT to carry the marker beyond the 2000-char head is kept;
  - light-mode (``profile(light=True)``) leaves the field empty (scan gated out).

Deterministic, stdlib-only, no network.
"""

from __future__ import annotations

from pathlib import Path

from app.tools.project_profile import ProjectProfiler


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# --- _is_apex_report unit branches ------------------------------------------

def test_is_apex_report_false_for_non_html(tmp_path):
    prof = ProjectProfiler(str(tmp_path))
    # A .js path is never an Apex report — the extension guard returns early.
    assert prof._is_apex_report("web/app.js") is False
    assert prof._is_apex_report("app/main.py") is False


def test_is_apex_report_false_when_unreadable(tmp_path):
    # A path that ends in .html but does not exist on disk → the read raises
    # OSError, which is swallowed to False (line 506-507).
    prof = ProjectProfiler(str(tmp_path))
    assert prof._is_apex_report("does/not/exist.html") is False


def test_is_apex_report_true_for_marked_page(tmp_path):
    _write(tmp_path, "report.html",
           "<html><head><title>Apex Idea Tree</title></head><body></body></html>\n")
    prof = ProjectProfiler(str(tmp_path))
    assert prof._is_apex_report("report.html") is True


def test_is_apex_report_false_for_plain_html(tmp_path):
    _write(tmp_path, "index.html", "<html><body><h1>Hi</h1></body></html>\n")
    prof = ProjectProfiler(str(tmp_path))
    assert prof._is_apex_report("index.html") is False


# --- the filter inside _scan_polyglot_hotspots ------------------------------

def test_apex_report_skipped_real_hotspots_kept(tmp_path):
    # An Apex artifact alongside genuine non-Python source: the artifact is
    # filtered out, the developer's files survive.
    _write(tmp_path, "app/main.py", "def run():\n    return 1\n")
    _write(tmp_path, "report.html",
           "<!DOCTYPE html>\n<html><head><title>Apex Idea Tree</title></head>\n"
           "<body>" + "x\n" * 50 + "</body></html>\n")
    _write(tmp_path, "web/app.js", "const a = 1;\nconst b = 2;\n")
    _write(tmp_path, "web/style.css", "body { color: red; }\n")

    profile = ProjectProfiler(str(tmp_path)).profile()
    paths = {h["path"] for h in profile.polyglot_hotspots}
    assert "report.html" not in paths
    assert "web/app.js" in paths
    assert "web/style.css" in paths


def test_filter_then_cap_still_yields_three(tmp_path):
    # One Apex report plus FIVE real non-Python files: the report is skipped, and
    # the cap still delivers exactly three real hotspots (extra candidates are
    # requested precisely so the filter never starves the result).
    _write(tmp_path, "report.html",
           "<html><head><title>Apex Idea Tree</title></head><body>"
           + "y\n" * 40 + "</body></html>\n")
    for i in range(5):
        _write(tmp_path, f"web/f{i}.js", f"const x{i} = {i};\n")

    profile = ProjectProfiler(str(tmp_path)).profile()
    assert len(profile.polyglot_hotspots) == 3
    assert all(h["path"] != "report.html" for h in profile.polyglot_hotspots)
    assert all(h["path"].endswith(".js") for h in profile.polyglot_hotspots)


def test_marker_beyond_head_is_not_filtered(tmp_path):
    # The marker only counts within the first 2000 chars. A long HTML file whose
    # Apex-looking marker sits PAST that head is treated as real source (kept).
    padding = "<p>filler line</p>\n" * 400  # > 2000 chars before the marker
    _write(tmp_path, "huge.html",
           "<html><body>\n" + padding
           + "<title>Apex Idea Tree</title>\n</body></html>\n")
    _write(tmp_path, "app/main.py", "def run():\n    return 1\n")

    profile = ProjectProfiler(str(tmp_path)).profile()
    assert any(h["path"] == "huge.html" for h in profile.polyglot_hotspots)


# --- light mode gates the scan out ------------------------------------------

def test_light_mode_skips_polyglot_scan(tmp_path):
    _write(tmp_path, "app/main.py", "def run():\n    return 1\n")
    _write(tmp_path, "web/app.js", "const a = 1;\nconst b = 2;\n")

    full = ProjectProfiler(str(tmp_path)).profile(light=False)
    light = ProjectProfiler(str(tmp_path)).profile(light=True)
    # Full mode names the JS hotspot; light mode leaves the field empty (the
    # grade never reads it, so it is gated out of the light path).
    assert any(h["path"] == "web/app.js" for h in full.polyglot_hotspots)
    assert light.polyglot_hotspots == []


def test_polyglot_hotspots_deterministic(tmp_path):
    _write(tmp_path, "app/main.py", "def run():\n    return 1\n")
    _write(tmp_path, "web/a.js", "const a = 1;\n" * 10)
    _write(tmp_path, "web/b.html", "<html>\n<body>\n<h1>Hi</h1>\n</body>\n</html>\n")

    first = ProjectProfiler(str(tmp_path)).profile().polyglot_hotspots
    second = ProjectProfiler(str(tmp_path)).profile().polyglot_hotspots
    assert first == second
    # Each entry carries exactly the documented keys.
    for h in first:
        assert set(h) == {"path", "language", "loc", "churn", "debt_markers"}
