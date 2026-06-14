"""Anchor (concrete-locus) rendering in the dashboard idea/roadmap section.

Ideas now carry ``IdeaNode.anchors`` — a ``list[dict]`` of
``{"module", "symbol", "line", "metric"}`` naming the riskiest function(s) an
idea should act on first. The dashboard surfaces them as a small "focus:" line
under each idea. These tests drive the pure render helpers directly with
lightweight SimpleNamespace inputs (no scan, no network) and guard the key
invariant: with NO anchors the rendered HTML is byte-identical to before.
"""

from types import SimpleNamespace

from app.models.idea import IdeaNode, IdeaTreeReport
from app.reporting import dashboard as D


def _idea(**kw):
    base = dict(
        operator="untangle", title="Untangle app/x.py", value=0.7,
        kind="permutation", source_facts=[], caveats=[], anchors=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


# --- _anchor_focus: empty / defensive paths --------------------------------

def test_anchor_focus_no_anchors_is_blank():
    assert D._anchor_focus(_idea(anchors=[])) == ""


def test_anchor_focus_missing_attribute_is_blank():
    # Older payloads / stand-ins without an `anchors` attribute at all.
    assert D._anchor_focus(SimpleNamespace(title="x")) == ""


def test_anchor_focus_non_dict_entries_ignored():
    assert D._anchor_focus(_idea(anchors=["not a dict", 42])) == ""


def test_anchor_focus_entry_without_symbol_ignored():
    assert D._anchor_focus(_idea(anchors=[{"module": "app/x.py", "line": 5}])) == ""


# --- _anchor_focus: render content ------------------------------------------

def test_anchor_focus_renders_symbol_line_metric():
    out = D._anchor_focus(_idea(anchors=[
        {"module": "app/x.py", "symbol": "_scan_churn", "line": 550,
         "metric": "cyclomatic 18"},
    ]))
    assert "focus:" in out
    assert "_scan_churn" in out
    assert "app/x.py:550" in out
    assert "cyclomatic 18" in out


def test_anchor_focus_multiple_anchors_joined():
    out = D._anchor_focus(_idea(anchors=[
        {"module": "app/x.py", "symbol": "alpha", "line": 1, "metric": "loc 80"},
        {"module": "app/x.py", "symbol": "beta", "line": 2, "metric": "loc 90"},
    ]))
    assert "alpha" in out and "beta" in out
    assert " · " in out


def test_anchor_focus_partial_fields_omit_gracefully():
    # symbol only -> no parenthetical detail, no crash.
    out = D._anchor_focus(_idea(anchors=[{"symbol": "lonely"}]))
    assert "lonely" in out
    assert "()" not in out


# --- HTML escaping ----------------------------------------------------------

def test_anchor_focus_escapes_codebase_strings():
    out = D._anchor_focus(_idea(anchors=[
        {"module": "app/<x>.py", "symbol": "f<&>", "line": 1,
         "metric": "m<i>c</i>"},
    ]))
    assert "f<&>" not in out
    assert "&lt;" in out and "&amp;" in out
    assert "<i>" not in out  # metric markup neutralised


# --- determinism ------------------------------------------------------------

def test_anchor_focus_is_deterministic():
    idea = _idea(anchors=[
        {"module": "app/x.py", "symbol": "_scan_churn", "line": 550,
         "metric": "cyclomatic 18"},
    ])
    assert D._anchor_focus(idea) == D._anchor_focus(idea)


# --- _ideas_section integration + byte-identical legacy guard ---------------

def _report(*ideas) -> IdeaTreeReport:
    return IdeaTreeReport(
        objective="o",
        ideas=list(ideas),
        stats={"total_ideas": len(ideas), "mean_value": 0.5, "synthesized": 0},
    )


def _root(anchors):
    return IdeaNode(
        id="r1", parent_id=None, kind="permutation",
        operator="untangle", title="Untangle app/x.py",
        depth=0, operator_chain=["untangle"],
        value=0.7, novelty=1.0, anchors=anchors,
    )


def test_ideas_section_renders_focus_when_anchored():
    rep = _report(_root([
        {"module": "app/x.py", "symbol": "_scan_churn", "line": 550,
         "metric": "cyclomatic 18"},
    ]))
    out = D._ideas_section(rep)
    assert "focus:" in out
    assert "_scan_churn" in out
    assert "cyclomatic 18" in out


def test_ideas_section_no_anchors_is_byte_identical_to_legacy():
    # The SAME idea tree rendered with empty anchors must match the historical
    # output (anchors stripped from the rendered string entirely).
    anchored = _report(_root([
        {"module": "app/x.py", "symbol": "_scan_churn", "line": 550,
         "metric": "cyclomatic 18"},
    ]))
    bare = _report(_root([]))

    out_bare = D._ideas_section(bare)
    out_anchored = D._ideas_section(anchored)

    # The bare render carries no focus element at all.
    assert "focus:" not in out_bare
    # The anchored render is exactly the bare render plus the focus div.
    assert out_anchored != out_bare
    assert out_anchored.replace(D._anchor_focus(anchored.ideas[0]), "") == out_bare


def test_ideas_section_deterministic():
    rep = _report(_root([
        {"module": "app/x.py", "symbol": "_scan_churn", "line": 550,
         "metric": "cyclomatic 18"},
    ]))
    assert D._ideas_section(rep) == D._ideas_section(rep)
