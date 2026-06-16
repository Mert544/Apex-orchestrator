"""Tests for the self-contained code-quality report renderer.

Covers both :func:`quality_report_html` and :func:`quality_report_markdown`:
analyzer names and headlines appear, top offenders are listed, every value is
HTML-escaped, an empty mapping yields a valid page, the output is deterministic
(byte-identical across runs), and the HTML is self-contained (no remote URL, no
stylesheet link, no script). Pure renderer — the analyzer dicts are fakes; we
never run a real analyzer here.
"""

from __future__ import annotations

from app.reporting.quality_report import (
    quality_report_html,
    quality_report_markdown,
)


def _fake_results() -> dict[str, dict]:
    """Two fake analyzer .to_dict() outputs in the common Apex shapes."""
    return {
        "type-hint coverage": {
            "overall_ratio": 0.42,
            "annotated_functions": 21,
            "total_functions": 50,
            "worst_modules": [
                {"module": "app/a.py", "ratio": 0.1, "annotated": 1, "total": 10},
                {"module": "app/b.py", "ratio": 0.3, "annotated": 3, "total": 10},
            ],
        },
        "complexity profile": {
            "total": 120,
            "over_threshold": 4,
            "max": 31,
            "mean": 5.2,
            "hotspots": [
                {"name": "do_work", "file": "app/c.py", "complexity": 31},
                {"name": "tangle", "file": "app/d.py", "complexity": 22},
            ],
        },
    }


def test_html_has_doctype_and_names_and_offenders() -> None:
    html = quality_report_html(_fake_results())
    assert html.lower().startswith("<!doctype html>")
    assert "type-hint coverage" in html
    assert "complexity profile" in html
    # Headline metrics surfaced.
    assert "42%" in html  # overall_ratio rendered as percent
    # Offenders listed.
    assert "app/a.py" in html
    assert "do_work" in html
    assert "tangle" in html


def test_html_escapes_special_characters() -> None:
    results = {
        "we<i>rd & <script>": {
            "total": 1,
            "offenders": [{"name": "<b>x</b>", "note": "a & b > c"}],
        }
    }
    html = quality_report_html(results)
    # The only literal "<script" in the document is the (escaped) data; there is
    # no real <script> element anywhere.
    assert "<script>" not in html
    # The raw special chars must be escaped, not present verbatim as markup.
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "a &amp; b &gt; c" in html


def test_empty_results_is_valid_page() -> None:
    html = quality_report_html({})
    assert html.lower().startswith("<!doctype html>")
    assert "</html>" in html
    assert "0 analyzers" not in html  # no card summary, but a "no data" note
    assert "nothing to report" in html


def test_html_is_deterministic() -> None:
    results = _fake_results()
    assert quality_report_html(results) == quality_report_html(results)


def test_html_is_self_contained() -> None:
    html = quality_report_html(_fake_results())
    assert "http://" not in html
    assert "https://" not in html
    assert "rel=\"stylesheet\"" not in html
    assert "<link" not in html
    assert "<script" not in html
    assert "@import" not in html
    assert "url(" not in html


def test_title_and_project_and_generated_injected() -> None:
    html = quality_report_html(
        _fake_results(),
        title="My Report",
        project="acme/widget",
        generated="build-7",
    )
    assert "<title>My Report</title>" in html
    assert "acme/widget" in html
    assert "build-7" in html


def test_generated_defaults_to_empty_no_timestamp_leak() -> None:
    a = quality_report_html(_fake_results())
    b = quality_report_html(_fake_results())
    assert a == b
    # No injected build label by default.
    assert "generated" not in a


def test_markdown_has_names_headlines_and_offenders() -> None:
    md = quality_report_markdown(_fake_results())
    assert md.startswith("# Apex Code Quality")
    assert "## type-hint coverage" in md
    assert "## complexity profile" in md
    assert "42% covered" in md
    assert "app/a.py" in md
    assert "do_work" in md
    # A markdown table divider for the offenders.
    assert "---" in md


def test_markdown_empty_is_valid() -> None:
    md = quality_report_markdown({})
    assert md.startswith("# Apex Code Quality")
    assert "nothing to report" in md


def test_markdown_is_deterministic() -> None:
    results = _fake_results()
    assert quality_report_markdown(results) == quality_report_markdown(results)


def test_metric_only_analyzer_renders_without_table() -> None:
    """A result with no offender list still renders a valid card."""
    results = {"todo debt": {"total": 9}}
    html = quality_report_html(results)
    assert "todo debt" in html
    assert "<table>" not in html  # no offenders -> no table
    md = quality_report_markdown(results)
    assert "## todo debt" in md


def test_malformed_offenders_do_not_break() -> None:
    """Non-dict offender entries and missing keys are tolerated."""
    results = {
        "weird": {
            "offenders": ["not-a-dict", 3],  # ignored: not list-of-dicts
            "total": 2,
        },
        "partial": {
            "candidates": [{"name": "x"}, {"file": "y.py"}],  # ragged keys
        },
    }
    html = quality_report_html(results)
    assert html.lower().startswith("<!doctype html>")
    assert "y.py" in html
    # The non-dict offender list must not have produced a table for "weird".
    assert "not-a-dict" not in html


def test_offender_list_is_capped() -> None:
    rows = [{"name": f"fn{i}", "v": i} for i in range(25)]
    html = quality_report_html({"big": {"offenders": rows}})
    assert "fn0" in html
    assert "fn9" in html
    # Capped at 10 -> the 11th (index 10) onward is dropped.
    assert "fn10" not in html
    assert "fn24" not in html


def test_html_orders_cards_by_input_order() -> None:
    a = quality_report_html({"alpha": {"total": 1}, "beta": {"total": 2}})
    assert a.index(">alpha<") < a.index(">beta<")
