"""The brief→develop narrative names the CONCRETE locus ADDITIVELY.

When the engine's top recommendation carries function anchors
(``IdeaNode.anchors`` = ``[{"module","symbol","line","metric"}]``), the rendered
brief adds a "Start here:" line naming the specific function + file:line + metric
— and weaves in the idea's ``rationale`` when present. With no anchored idea the
brief is byte-identical to before — the feature is opt-in by the data. This is
the function-level locus, complementary to (not a duplicate of) the module-level
Convergence note.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.engine.brief_develop import (
    BriefDevelopResult,
    _anchor_record,
    _loci_from_report,
    _locus_lines,
    _locus_phrase,
    render_brief_develop_markdown,
)


def _result(loci=None, confluences=None, objectives=("remove-dead-code",),
            **kw) -> BriefDevelopResult:
    return BriefDevelopResult(
        branch_path="x.o", title="T", subject="app/m.py",
        objectives=list(objectives), applied=False,
        confluences=list(confluences or []),
        loci=list(loci or []),
        check={"branch_path": "x.o", "title": "T", "subject": "app/m.py",
               "resolved": [], "open": [], "measured_total": 0},
        **kw)


_LOCUS = {"module": "app/tools/project_profile.py", "symbol": "_scan_churn",
          "line": 550, "metric": "cyclomatic 18", "rationale": ""}


def _idea(value, subject="app/tools/project_profile.py", anchors=None,
          rationale="", branch_path="x.1", id_="i1"):
    return SimpleNamespace(value=value, subject=subject, anchors=anchors,
                           rationale=rationale, branch_path=branch_path, id=id_)


# --- the "Start here:" line names symbol + file:line + metric -----------------

def test_locus_line_names_symbol_line_and_metric():
    md = render_brief_develop_markdown(_result(loci=[_LOCUS]))
    assert "**Start here:**" in md
    assert "`_scan_churn`" in md
    assert "app/tools/project_profile.py:550" in md
    assert "cyclomatic 18" in md


def test_locus_line_weaves_in_rationale():
    locus = {**_LOCUS, "rationale": "the riskiest function in the hot module"}
    md = render_brief_develop_markdown(_result(loci=[locus]))
    assert "**Start here:**" in md
    assert "the riskiest function in the hot module" in md


def test_locus_line_appears_even_without_objectives():
    md = render_brief_develop_markdown(_result(loci=[_LOCUS], objectives=[]))
    assert "**Start here:**" in md
    assert "`_scan_churn`" in md
    # The manual fallback narrative still renders alongside it.
    assert "Carry it out by hand" in md


def test_locus_complements_confluence_not_duplicates():
    conv = {"module": "app/core/router.py", "family_count": 3,
            "families": ("complex-function", "high-churn", "hub")}
    md = render_brief_develop_markdown(_result(loci=[_LOCUS], confluences=[conv]))
    # Both sections render, each exactly once — they are complementary.
    assert md.count("**Convergence:**") == 1
    assert md.count("**Start here:**") == 1


def test_locus_names_multiple_functions():
    second = {"module": "app/tools/project_profile.py", "symbol": "_scan_hubs",
              "line": 720, "metric": "fan-in 31", "rationale": ""}
    md = render_brief_develop_markdown(_result(loci=[_LOCUS, second]))
    assert "`_scan_churn`" in md
    assert "`_scan_hubs`" in md
    assert "fan-in 31" in md


# --- byte-identical when no idea carries anchors -----------------------------

def test_no_loci_is_byte_identical_with_objectives():
    base = render_brief_develop_markdown(_result(loci=[]))
    # The pre-feature output never carried a Start here note.
    assert "Start here" not in base
    assert base == render_brief_develop_markdown(_result(loci=None))


def test_no_loci_is_byte_identical_no_objectives():
    base = render_brief_develop_markdown(_result(loci=[], objectives=[]))
    assert "Start here" not in base
    assert "Carry it out by hand" in base


# --- determinism --------------------------------------------------------------

def test_render_is_deterministic():
    a = render_brief_develop_markdown(_result(loci=[_LOCUS]))
    b = render_brief_develop_markdown(_result(loci=[_LOCUS]))
    assert a == b


# --- _locus_phrase formats each optional field cleanly -----------------------

def test_locus_phrase_full():
    assert _locus_phrase(_LOCUS) == (
        "`_scan_churn` (app/tools/project_profile.py:550, cyclomatic 18)")


def test_locus_phrase_drops_metric_when_absent():
    phrase = _locus_phrase({"module": "app/m.py", "symbol": "f", "line": 9})
    assert phrase == "`f` (app/m.py:9)"


def test_locus_phrase_symbol_only():
    assert _locus_phrase({"symbol": "f"}) == "`f`"


def test_locus_phrase_module_without_line():
    assert _locus_phrase({"symbol": "f", "module": "app/m.py"}) == "`f` (app/m.py)"


# --- _locus_lines gating + rationale weave ------------------------------------

def test_locus_lines_empty_when_no_loci():
    assert _locus_lines([]) == []


def test_locus_lines_uses_first_nonempty_rationale():
    loci = [{**_LOCUS, "rationale": ""},
            {"module": "app/m.py", "symbol": "g", "line": 1, "metric": "",
             "rationale": "second carries it"}]
    out = _locus_lines(loci)
    assert any("second carries it" in ln for ln in out)


# --- _anchor_record reads defensively -----------------------------------------

def test_anchor_record_well_formed():
    rec = _anchor_record(
        {"module": "app/m.py", "symbol": "f", "line": 5, "metric": "cc 7"},
        "app/fallback.py")
    assert rec == {"module": "app/m.py", "symbol": "f", "line": 5, "metric": "cc 7"}


def test_anchor_record_falls_back_to_idea_subject():
    rec = _anchor_record({"symbol": "f", "line": 5}, "app/fallback.py")
    assert rec["module"] == "app/fallback.py"


def test_anchor_record_none_without_symbol():
    assert _anchor_record({"module": "app/m.py", "line": 5}, "app/x.py") is None
    assert _anchor_record({"symbol": "  "}, "app/x.py") is None


def test_anchor_record_none_when_not_a_dict():
    assert _anchor_record("not a dict", "app/x.py") is None
    assert _anchor_record(None, "app/x.py") is None


# --- _loci_from_report picks the top anchored idea ----------------------------

def test_loci_from_report_picks_highest_value_anchored_idea():
    high = _idea(0.9, anchors=[{"symbol": "f", "line": 5, "metric": "cc 9"}],
                 rationale="hot", branch_path="x.hi", id_="hi")
    low = _idea(0.2, anchors=[{"symbol": "g", "line": 1}],
                branch_path="x.lo", id_="lo")
    report = SimpleNamespace(ideas=[low, high])
    loci = _loci_from_report(report)
    assert len(loci) == 1
    assert loci[0]["symbol"] == "f"
    assert loci[0]["rationale"] == "hot"


def test_loci_from_report_skips_ideas_without_anchors():
    no_anchor = _idea(0.99, anchors=None, branch_path="x.top", id_="top")
    anchored = _idea(0.5, anchors=[{"symbol": "f", "line": 5}],
                     branch_path="x.a", id_="a")
    report = SimpleNamespace(ideas=[no_anchor, anchored])
    loci = _loci_from_report(report)
    assert [r["symbol"] for r in loci] == ["f"]


def test_loci_from_report_empty_when_no_anchors():
    report = SimpleNamespace(ideas=[_idea(0.9, anchors=None),
                                    _idea(0.5, anchors=[])])
    assert _loci_from_report(report) == []


def test_loci_from_report_missing_ideas_field_is_empty():
    assert _loci_from_report(SimpleNamespace()) == []
    assert _loci_from_report(None) == []


def test_loci_from_report_is_deterministic_on_value_ties():
    # Equal value: stable branch_path/id tiebreak, not insertion order.
    a = _idea(0.5, anchors=[{"symbol": "a", "line": 1}], branch_path="x.a", id_="a")
    b = _idea(0.5, anchors=[{"symbol": "b", "line": 2}], branch_path="x.b", id_="b")
    r1 = _loci_from_report(SimpleNamespace(ideas=[a, b]))
    r2 = _loci_from_report(SimpleNamespace(ideas=[b, a]))
    assert r1 == r2
    assert r1[0]["symbol"] == "a"


# --- to_dict carries the signal ----------------------------------------------

def test_to_dict_includes_loci():
    d = _result(loci=[_LOCUS]).to_dict()
    assert d["loci"] == [_LOCUS]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
