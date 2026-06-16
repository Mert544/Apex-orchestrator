"""Code-quality metrics card in the HTML dashboard.

Apex surfaces four deterministic, LLM-free analyzers as one "Code quality
metrics" panel: type-hint coverage %, public docstring coverage %, the
cyclomatic-complexity over-threshold count + hotspots, and the inline TODO/FIXME
debt census. These tests drive the pure ``_quality_section`` render helper
directly and through a full ``build_dashboard`` integration, guarding the key
invariants: gated absence (no measurable code -> no section / no nav anchor),
the card markup appears when data exists, HTML escaping, determinism, and the
page-wide self-contained + single-timestamp invariants.

Pattern-matched on tests/test_dashboard_trackrecord.py — fast, offline, no
time/random assertions.
"""

from app.reporting import dashboard as D
from app.reporting.dashboard import build_dashboard


def _write_project(tmp_path):
    """A tiny project with a typed+documented function, an undocumented public
    function, a complex hotspot, and a TODO marker — so every analyzer fires."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "good.py").write_text(
        '"""Module docstring."""\n\n\n'
        "def tidy(x: int) -> int:\n"
        '    """Documented and fully typed."""\n'
        "    return x + 1\n",
        encoding="utf-8",
    )
    # A public, undocumented, untyped, and branchy function -> drives docstring
    # gaps, type-hint gaps, and a complexity hotspot at once. # TODO marker too.
    branches = "".join(f"    if x == {i}:\n        return {i}\n" for i in range(20))
    (app / "messy.py").write_text(
        "def tangle(x):\n"
        "    # TODO: simplify this dispatcher\n"
        f"{branches}"
        "    return -1\n",
        encoding="utf-8",
    )
    return tmp_path


# --- gated absence ----------------------------------------------------------

def test_quality_section_absent_on_empty_tree(tmp_path):
    # No Python sources -> no measurable functions/symbols/markers -> "".
    assert D._quality_section(str(tmp_path)) == ""


def test_quality_pct_bar_clamps_and_buckets():
    assert "100%" in D._quality_pct_bar("L", 1.5)
    assert "0%" in D._quality_pct_bar("L", -0.2)
    assert "bar-good" in D._quality_pct_bar("L", 0.9)
    assert "bar-warn" in D._quality_pct_bar("L", 0.5)
    assert "bar-bad" in D._quality_pct_bar("L", 0.1)


# --- renders each analyzer's markup -----------------------------------------

def test_quality_section_renders_all_four(tmp_path):
    _write_project(tmp_path)
    html_doc = D._quality_section(str(tmp_path))
    assert "Code quality metrics" in html_doc
    assert "id='quality'" in html_doc
    # type-hint coverage
    assert "Type-hint coverage" in html_doc
    assert "type hints" in html_doc
    # docstring coverage
    assert "Public docstring coverage" in html_doc
    assert "public docs" in html_doc
    # complexity over-threshold + hotspots
    assert "complexity &gt;" in html_doc or "complexity >" in html_doc
    assert "Complexity hotspots" in html_doc
    assert "tangle" in html_doc
    # TODO debt
    assert "debt markers" in html_doc
    assert "TODO" in html_doc


# --- escaping ---------------------------------------------------------------

def test_quality_section_escapes_todo_text(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "x.py").write_text(
        "def f(a: int) -> int:\n"
        "    # TODO: <script>alert(1)</script>\n"
        "    return a\n",
        encoding="utf-8",
    )
    html_doc = D._quality_section(str(tmp_path))
    assert "<script>alert(1)</script>" not in html_doc
    assert "&lt;script&gt;" in html_doc


# --- determinism ------------------------------------------------------------

def test_quality_section_is_deterministic(tmp_path):
    _write_project(tmp_path)
    a = D._quality_section(str(tmp_path))
    b = D._quality_section(str(tmp_path))
    assert a == b
    assert "UTC" not in a  # no timestamp leaked into the panel


# --- full-page integration --------------------------------------------------

def test_full_dashboard_includes_quality_when_present(tmp_path):
    _write_project(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=8, idea_depth=1, breadth=2)
    assert "#quality" in html_doc          # nav anchor
    assert "Code quality metrics" in html_doc
    assert "Type-hint coverage" in html_doc


def test_full_dashboard_self_contained_and_single_timestamp(tmp_path):
    _write_project(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=8, idea_depth=1, breadth=2)
    # Self-contained: no remote scripts/stylesheets, and the only URL on the
    # page is the SVG xmlns namespace (charts), never a fetched resource.
    assert "<script src=" not in html_doc
    assert 'rel="stylesheet"' not in html_doc
    assert "src='http" not in html_doc and 'src="http' not in html_doc
    assert "href='http" not in html_doc and 'href="http' not in html_doc
    # Exactly one timestamp on the page.
    assert html_doc.count("UTC") == 1
