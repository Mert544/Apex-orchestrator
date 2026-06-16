"""Characterization tests for the `_render_html` extraction helpers.

`_render_html` was shrunk by extracting `_nav_links`, `_page_sections` and the
`_BRAND_MARK` constant. These tests pin the resulting structure so the mechanical
extraction stays behavior-preserving: the page is stamped exactly once, the
helpers are byte-faithful to what the page emits, and gated nav links only appear
when their section renders.
"""

from types import SimpleNamespace

from app.reporting import dashboard as d
from app.reporting.dashboard_sections import RenderedSections


def _project(tmp):
    (tmp / "app").mkdir()
    (tmp / "app" / "svc.py").write_text("import os\ndef run(cmd):\n    return eval(cmd)\n")
    (tmp / "app" / "main.py").write_text("def main():\n    return 1\n")
    return tmp


def test_brand_mark_is_inlined_once(tmp_path):
    _project(tmp_path)
    html_doc = d.build_dashboard(str(tmp_path), max_ideas=12, quality=False)
    # The extracted module-level constant is the exact glyph embedded in the page.
    assert d._BRAND_MARK in html_doc
    assert html_doc.count("<svg class='mark'") == 1


def test_single_timestamp_stamp(tmp_path):
    _project(tmp_path)
    html_doc = d.build_dashboard(str(tmp_path), max_ideas=12, quality=False)
    # Exactly one generated-at stamp; nothing else clocks the page.
    assert html_doc.count("class='stamp'>generated ") == 1


def test_nav_links_gate_with_sections():
    """`_nav_links` mirrors section gating: optional anchors appear iff rendered."""
    base = dict(
        project_root="/nonexistent-root-xyz",
        git={},
        debug={},
        roadmap=None,
        shape=None,
        autonomy=None,
        pareto=[],
        trajectory=[],
        learned=None,
    )
    minimal = d._nav_links(
        **base, sections=RenderedSections(),
    )
    # The always-present spine is there...
    for anchor in ("#overview", "#findings", "#architecture", "#ideas",
                   "#actions", "#reasoning", "#profile"):
        assert f"href='{anchor}'" in minimal
    # ...and gated ones are absent when their data is missing.
    for anchor in ("#quality", "#shape", "#roadmap", "#frontier", "#autonomy",
                   "#trajectory", "#learned", "#trackrecord", "#outscope",
                   "#debug", "#repository"):
        assert f"href='{anchor}'" not in minimal

    # Flip every gate on and confirm each anchor appears.
    rich = d._nav_links(
        project_root="/nonexistent-root-xyz",
        git={"branch": "main"},
        debug={"trace_count": 1},
        roadmap=SimpleNamespace(phases=[object()]),
        shape=SimpleNamespace(total_ideas=3),
        autonomy={"act": True},
        pareto=[object()],
        trajectory=[{"ts": "x"}],
        learned={"most_reliable": [{"key": "k"}]},
        sections=RenderedSections(
            outscope_html="<section id='outscope'></section>",
            trackrecord_html="<section id='trackrecord'></section>",
            quality_html="<section id='quality'></section>",
        ),
    )
    for anchor in ("#quality", "#shape", "#roadmap", "#frontier", "#autonomy",
                   "#trajectory", "#learned", "#trackrecord", "#outscope",
                   "#debug", "#repository"):
        assert f"href='{anchor}'" in rich


def test_page_sections_concatenates_in_order(tmp_path):
    """`_page_sections` is a faithful concatenation appearing inside <main>."""
    _project(tmp_path)
    html_doc = d.build_dashboard(str(tmp_path), max_ideas=12, quality=False)
    main = html_doc.split("<main>", 1)[1].split("</main>", 1)[0]
    # Section ids appear in the documented page order.
    order = ["overview", "findings", "architecture", "ideas",
             "actions", "reasoning", "profile"]
    positions = [main.find(f"id='{sid}'") for sid in order]
    assert all(p >= 0 for p in positions)
    assert positions == sorted(positions)
