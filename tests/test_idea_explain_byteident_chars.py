"""Characterization: refactored render_explanation_markdown / _render_anchor are
byte-identical to the pre-refactor implementation across every branch.

The original module text is loaded from ``git show HEAD:...`` into a throwaway
module so we can diff the FULL markdown string old-vs-new with zero tolerance.
"""

from __future__ import annotations

import importlib.util
import itertools
import subprocess
import sys
import types

from app.engine import idea_explain as new_mod
from app.engine.idea_explain import IdeaExplanation


def _load_original() -> types.ModuleType:
    src = subprocess.run(
        ["git", "show", "HEAD:app/engine/idea_explain.py"],
        capture_output=True, text=True, check=True,
    ).stdout
    spec = importlib.util.spec_from_loader("_idea_explain_orig", loader=None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_idea_explain_orig"] = mod
    exec(compile(src, "<orig idea_explain>", "exec"), mod.__dict__)
    return mod


ORIG = _load_original()


def _anchors_grid() -> list[list[dict]]:
    fields = {
        "symbol": ["", "foo", None],
        "module": ["", "app/x.py", None],
        "line": [None, 0, 12, "", "  ", "7"],
        "metric": ["", "cx=9", None],
    }
    singles = []
    keys = list(fields)
    for combo in itertools.product(*(fields[k] for k in keys)):
        singles.append({k: v for k, v in zip(keys, combo)})
    # single-anchor lists plus a few multi-anchor lists and the empty list
    out: list[list[dict]] = [[], [singles[0]], singles[:3], singles[5:8]]
    out += [[a] for a in singles]
    return out


def test_render_anchor_byte_identical():
    fields = {
        "symbol": ["", "foo", None, "Bar.baz"],
        "module": ["", "app/x.py", None],
        "line": [None, 0, 12, "", "  ", "7", 0.0],
        "metric": ["", "cx=9", None, "loc=120"],
    }
    keys = list(fields)
    for combo in itertools.product(*(fields[k] for k in keys)):
        anchor = {k: v for k, v in zip(keys, combo)}
        assert new_mod._render_anchor(anchor) == ORIG._render_anchor(anchor), anchor


def _exp_variants() -> list[IdeaExplanation]:
    base = dict(
        branch_path="x.s1", title="T", subject="app/m.py :: f", kind="facet",
        operator="lens", operator_chain=[], depth=2, source_facts=[],
        relevance=0.5, novelty=0.7, feasibility=0.6, value=0.55,
        value_formula="value = ...", phase="", impact=0.0, effort=0.0, roi=0.0,
        fan_in=0, loc=0, caveats=[], executable=False, action_type="design",
        action_description="do the thing",
    )
    variants: list[IdeaExplanation] = []
    toggles = {
        "operator_chain": [[], ["a"], ["a", "b", "c"]],
        "source_facts": [[], ["one fact"], ["f1", "f2"]],
        "caveats": [[], ["risk"], ["r1", "r2"]],
        "executable": [True, False],
        "phase": ["", "Now"],
        "rationale": ["", "  ", "because reasons"],
        "anchors": _anchors_grid(),
    }
    keys = list(toggles)
    for combo in itertools.product(*(toggles[k] for k in keys)):
        kw = dict(base)
        for k, v in zip(keys, combo):
            kw[k] = v
        variants.append(IdeaExplanation(**kw))
    return variants


def test_render_markdown_byte_identical():
    mismatches = 0
    variants = _exp_variants()
    for exp in variants:
        if new_mod.render_explanation_markdown(exp) != ORIG.render_explanation_markdown(exp):
            mismatches += 1
    assert mismatches == 0, f"{mismatches}/{len(variants)} markdown mismatches"
    assert len(variants) > 500
