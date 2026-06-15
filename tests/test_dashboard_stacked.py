"""Analysis-scope composition bar in the HTML dashboard.

Apex deep-analyses Python only, so a polyglot repo carries a genuine "how much
of the source tree does our analysis actually cover?" composition. The
Architecture section surfaces it as a proportional ``stacked_bar`` of
``profile.analyzed_ratio`` vs ``profile.out_of_scope_ratio`` (from
``dashboard_charts.stacked_bar``).

These tests drive the pure ``_scope_composition`` helper directly for the
content / escaping / gating / determinism paths, and one end-to-end
``build_dashboard`` over a polyglot fixture guards the self-contained +
single-timestamp invariants. Pattern-matched on tests/test_dashboard_signals.py
and tests/test_dashboard_scope.py — fast, offline, no time/random assertions.
"""

import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

from app.reporting import dashboard as D
from app.reporting.dashboard import build_dashboard


def _profile(**kw):
    """A minimal profile stand-in for the Architecture render helpers."""
    base = dict(
        coordinator_modules=[], import_cycles=[], fragile_modules=[],
        dependency_edges=[], analyzed_ratio=1.0, out_of_scope_ratio=0.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# --- _scope_composition: gating (no informative split -> omitted) -----------

def test_scope_composition_omitted_for_all_python_repo():
    # An all-Python repo has out_of_scope_ratio == 0.0 -> nothing to compose.
    assert D._scope_composition(_profile(analyzed_ratio=1.0, out_of_scope_ratio=0.0)) == ""


def test_scope_composition_omitted_when_ratio_field_absent():
    # A profile from a worktree without the scope fields renders nothing.
    assert D._scope_composition(SimpleNamespace()) == ""


def test_scope_composition_omitted_when_out_ratio_non_numeric():
    assert D._scope_composition(_profile(out_of_scope_ratio="nan")) == ""


def test_scope_composition_omitted_when_analyzed_non_numeric():
    assert D._scope_composition(_profile(analyzed_ratio=None, out_of_scope_ratio=0.4)) == ""


# --- _scope_composition: renders the stacked composition bar ----------------

def test_scope_composition_renders_stacked_bar():
    out = D._scope_composition(_profile(analyzed_ratio=0.6, out_of_scope_ratio=0.4))
    assert out != ""
    # The composition bar is an SVG with a legend naming both segments.
    assert "<svg" in out
    assert 'aria-label="composition"' in out
    assert "Analysed (Python)" in out
    assert "Out of scope" in out
    # The proportional split surfaces as legend percentages.
    assert "60%" in out
    assert "40%" in out


def test_scope_composition_is_self_contained_svg():
    out = D._scope_composition(_profile(analyzed_ratio=0.7, out_of_scope_ratio=0.3))
    # The only remote reference allowed is the SVG xmlns namespace.
    without_ns = out.replace('xmlns="http://www.w3.org/2000/svg"', "")
    assert "http://" not in without_ns and "https://" not in without_ns
    # No timestamp leaked into the bar.
    assert "UTC" not in out


def test_scope_composition_is_deterministic():
    p = _profile(analyzed_ratio=0.55, out_of_scope_ratio=0.45)
    assert D._scope_composition(p) == D._scope_composition(p)


# --- _architecture_section integration --------------------------------------

def test_architecture_section_includes_scope_composition_when_polyglot():
    # A polyglot profile with no architectural risks still gets the scope bar
    # appended to the "all clear" card.
    out = D._architecture_section(_profile(analyzed_ratio=0.6, out_of_scope_ratio=0.4))
    assert "Architecture health" in out
    assert "Analysis scope composition" in out
    assert "Out of scope" in out


def test_architecture_section_includes_scope_composition_with_risks():
    # The scope bar also rides alongside real cycles/fragile/coordinator content.
    out = D._architecture_section(_profile(
        analyzed_ratio=0.5, out_of_scope_ratio=0.5,
        coordinator_modules=[
            {"module": "app/engine/wirer.py", "fan_out": 17, "imports": ["app/a.py"]},
        ],
    ))
    assert "Coordinator modules" in out
    assert "Analysis scope composition" in out


def test_architecture_section_no_scope_bar_for_all_python_is_legacy_identical():
    # An all-Python, all-clean profile renders exactly the historical card: no
    # scope composition heading, no SVG.
    out = D._architecture_section(_profile())
    assert "Analysis scope composition" not in out
    assert "<svg" not in out
    assert "No import cycles or fragile hubs detected" in out


# --- end-to-end: a real polyglot fixture + invariants -----------------------

def _git_repo(root: Path) -> None:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    e = {**os.environ, **env}
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=e)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=e)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"],
        cwd=root, check=True, env=e,
    )


def _polyglot_fixture(tmp: Path) -> Path:
    """A package with both Python and non-Python source -> out_of_scope > 0."""
    pkg = tmp / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "svc.py").write_text("def run():\n    return 1\n")
    web = tmp / "web"
    web.mkdir()
    (web / "app.js").write_text("const a = 1;\nconst b = 2;\n")
    (web / "style.css").write_text("body { color: red; }\n")
    _git_repo(tmp)
    return tmp


def test_dashboard_surfaces_scope_composition_for_polyglot(tmp_path):
    _polyglot_fixture(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=8, idea_depth=1, breadth=2)
    # The composition bar lands inside the Architecture section's markup.
    assert "Analysis scope composition" in html_doc
    arch = html_doc.split("id='architecture'")[1].split("</section>")[0]
    assert 'aria-label="composition"' in arch
    assert "Out of scope" in arch


def test_dashboard_with_scope_bar_stays_self_contained(tmp_path):
    _polyglot_fixture(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=8, idea_depth=1, breadth=2)
    assert html_doc.startswith("<!doctype html>")
    assert "<script src=" not in html_doc
    assert 'rel="stylesheet"' not in html_doc
    without_ns = html_doc.replace('xmlns="http://www.w3.org/2000/svg"', "")
    assert "http://" not in without_ns and "https://" not in without_ns


def test_dashboard_with_scope_bar_has_single_timestamp(tmp_path):
    _polyglot_fixture(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=8, idea_depth=1, breadth=2)
    stamps = re.findall(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", html_doc)
    assert len(stamps) == 1


def test_no_scope_bar_for_all_python_dashboard(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def run():\n    return 1\n")
    html_doc = build_dashboard(str(tmp_path), max_ideas=8, idea_depth=1, breadth=2)
    assert "Analysis scope composition" not in html_doc
