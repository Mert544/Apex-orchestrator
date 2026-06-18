"""Deep-mutation-hardening tests for ``app.reporting.dashboard_sections``.

These kill surviving mutants that the default ``apex mutants --max-mutants 30``
cap never reaches: the full mutant universe of ``dashboard_sections.py`` is 342
single-token faults, and enumerating + verifying every one of them (via
``_collect_sites`` / ``_splice`` from ``app.engine.mutation_tester``) against the
module's covering tests surfaces blind spots far past the 30th site.

Each test below pins the exact broken behaviour of one such survivor so the
mutant dies. The docstring names the source line + token flip it closes. All
tests are deterministic and hermetic — hand-built data objects / ``SimpleNamespace``
stand-ins, never a clock, network, or randomness — and match the style of
``test_reporting_mutation_hardening_eyml.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.models.idea import IdeaNode, IdeaTreeReport
from app.reporting import dashboard_sections as s


def _ns(**kw):
    return SimpleNamespace(**kw)


# ---------------------------------------------------------------------------
# _health_bars — the security-bar formula ``1.0 / (1.0 + findings)``
#
# The prior suite asserted only that a "Security" row renders, never its VALUE,
# so the whole ``1.0 / (1.0 + findings)`` expression was a blind spot. With a
# NON-ZERO finding count the four arithmetic/constant flips each move the bar to
# a different fraction (hence a different fill width + traffic-light colour),
# which these assertions pin exactly. (With 0 findings ``/`` and ``*`` coincide,
# which is why the earlier test could not see them.)
# ---------------------------------------------------------------------------


def _security_bar_geometry(findings_count: int) -> str:
    return s._health_bars(
        _ns(analyzed_ratio=0.5),
        {"coverage": {"coverage_ratio": 0.5},
         "security": {"findings_count": findings_count}},
    )


def test_health_bars_security_value_pins_division_not_multiplication():
    """Kills line 126 ``1.0 / (1.0 + sec_n)`` arithmetic ``/``->``*``.

    With 3 findings the security fraction is ``1.0 / (1.0 + 3) = 0.25`` -> a 25%
    bar (fill width ``194 * 0.25 = 48.5``, red band). Flipping ``/`` to ``*``
    gives ``1.0 * 4 = 4.0`` (clamped to a full green bar), so the 48.5-wide red
    fill is the discriminator the old "Security in out" test missed.
    """
    out = _security_bar_geometry(3)
    # track_w = 320 - 120 - 6 = 194; fill = 194 * 0.25 = 48.5
    assert 'width="48.5"' in out
    assert "#d24b3e" in out  # red band at 25%


def test_health_bars_security_value_pins_plus_not_minus():
    """Kills line 126 ``(1.0 + sec_n)`` arithmetic ``+``->``-``.

    With 3 findings the denominator is ``1.0 + 3 = 4`` (fraction 0.25). Flipping
    ``+`` to ``-`` yields ``1.0 - 3 = -2`` -> ``1.0 / -2 = -0.5`` clamped to 0 ->
    an empty (width 0) bar, distinct from the real 48.5-wide fill.
    """
    out = _security_bar_geometry(3)
    assert 'width="48.5"' in out


def test_health_bars_security_value_pins_numerator_constant():
    """Kills line 126 numerator ``1.0``->``2.0``.

    With 3 findings the real fraction is ``1.0 / 4 = 0.25``. A ``2.0`` numerator
    gives ``2.0 / 4 = 0.5`` -> a 50% amber bar (fill 97.0), so pinning the 48.5
    red fill kills the constant flip.
    """
    out = _security_bar_geometry(3)
    assert 'width="48.5"' in out
    assert "#d24b3e" in out


def test_health_bars_security_value_pins_denominator_constant():
    """Kills line 126 denominator ``1.0``->``2.0``.

    With 3 findings the real fraction is ``1.0 / (1.0 + 3) = 0.25``. A ``2.0``
    denominator base gives ``1.0 / (2.0 + 3) = 0.2`` -> a 20% bar (fill 38.8),
    so the exact 48.5 fill width pins the boundary literal.
    """
    out = _security_bar_geometry(3)
    assert 'width="48.5"' in out


# ---------------------------------------------------------------------------
# _profile_section — the "stale debt" column (line 207-209)
#
# Only ``test_dashboard.py`` exercises ``_profile_section``, and it builds a real
# project profile + asserts structure — never the debt-marker math. So the whole
# ``[f"{m} · ~{d // 30} months" ... if d >= 90]`` comprehension was a blind spot:
# the ``>= 90`` day gate, the ``// 30`` months conversion, and even the
# ``-kv[1]`` sort index (``kv[1]`` -> ``kv[2]`` would IndexError on the 2-tuples)
# all went unchecked. A direct call with concrete debt ages pins every token.
# ---------------------------------------------------------------------------


def _profile(**over):
    base = dict(
        total_files=3, entrypoints=[], dependency_hubs=[], untested_modules=[],
        sensitive_paths=[], ci_files=[], churn_hotspots=[], debt_marker_ages={},
    )
    base.update(over)
    return _ns(**base)


def test_profile_section_stale_debt_months_and_threshold():
    """Kills line 208 ``d // 30`` months and line 209 ``d >= 90`` / ``-kv[1]``.

    A marker aged 120 days renders ``~4 months`` (``120 // 30``) and is included
    (``120 >= 90``); a marker aged 89 days is excluded (below the 90-day gate).
    Sorting is by ``-kv[1]`` (the age), so the oldest comes first — accessing
    ``kv[2]`` would raise on the 2-tuples, so reaching this assertion at all
    pins the sort index too.
    """
    out = s._profile_section(_profile(debt_marker_ages={
        "old.py": 120, "older.py": 365, "fresh.py": 89,
    }))
    assert "old.py · ~4 months" in out        # 120 // 30 == 4, included (>=90)
    assert "older.py · ~12 months" in out      # 365 // 30 == 12
    assert "fresh.py" not in out               # 89 < 90 -> excluded
    # oldest first: older.py (365) precedes old.py (120)
    assert out.index("older.py") < out.index("old.py")


def test_profile_section_debt_boundary_includes_exactly_ninety():
    """Kills line 209 ``d >= 90`` boundary flips ``>=``->``>`` and ``90``->``91``.

    A marker aged exactly 90 days sits ON the inclusive boundary and MUST render
    (``90 >= 90``). Sliding the operator to ``>`` or bumping the literal to ``91``
    would drop it, so pinning its presence kills both boundary mutants.
    """
    out = s._profile_section(_profile(debt_marker_ages={"edge.py": 90}))
    assert "edge.py · ~3 months" in out        # 90 // 30 == 3, included


def test_profile_section_churn_and_list_caps_render():
    """Kills line 196 ``items[:8]``->``[:9]`` and line 195 ``return ""``->``None``.

    A list of 9 entrypoints must show exactly 8 (the ``[:8]`` cap); the 9th is
    dropped. An empty list yields no column (the ``return ""`` gate), so a
    populated list that omits the 9th entry pins both the cap and the gate.
    """
    names = [f"e{i}.py" for i in range(9)]
    out = s._profile_section(_profile(entrypoints=names))
    assert "e7.py" in out          # 8th entry shown
    assert "e8.py" not in out      # 9th entry dropped by [:8] cap


# ---------------------------------------------------------------------------
# _architecture_section — the import-cycles body block (line 412-413, 418)
#
# The covering tests build the architecture card with coordinators/fragile hubs
# but never with import CYCLES, so the ``if cycles:`` block (its ``cycles[:5]``
# cap and its ``body += ...`` accumulation) is unexercised. ``body`` is a string,
# so the ``+=`` -> ``-=`` flip would raise ``TypeError`` the moment that branch
# runs — a fault no test triggers. A direct call with cycles pins it.
# ---------------------------------------------------------------------------


def _arch_profile(**over):
    base = dict(
        import_cycles=[], fragile_modules=[], coordinator_modules=[],
        dependency_edges=[], deeply_nested_functions=[], out_of_scope_ratio=0.0,
        analyzed_ratio=1.0,
    )
    base.update(over)
    return _ns(**base)


def test_architecture_section_renders_import_cycles_block():
    """Kills line 413 ``body += ...`` augassign ``+=``->``-=`` (TypeError on str)
    and line 412 ``cycles[:5]``->``[:6]`` truncation.

    With 6 import cycles the card shows the first 5 (the ``[:5]`` cap) under an
    "Import cycles" heading. The ``+=`` accumulation onto the ``body`` string
    must run without error — flipping it to ``-=`` raises ``TypeError``.
    """
    cycles = [[f"a{i}.py", f"b{i}.py"] for i in range(6)]
    out = s._architecture_section(_arch_profile(import_cycles=cycles))
    assert "Import cycles" in out
    assert "a0.py" in out and "a4.py" in out   # first 5 shown
    assert "a5.py" not in out                  # 6th dropped by [:5] cap


def test_architecture_section_renders_fragile_block():
    """Kills line 420 ``body += ...`` augassign ``+=``->``-=`` for fragile hubs
    and line 418 ``fragile[:5]``->``[:6]`` truncation.

    Six fragile modules render under a "Fragile modules" heading, but only the
    first 5 (the ``[:5]`` cap); the 6th is dropped. The ``body += `` accumulation
    must succeed (``-=`` would ``TypeError`` on the string).
    """
    mods = [f"m{i}.py" for i in range(6)]
    out = s._architecture_section(_arch_profile(fragile_modules=mods))
    assert "Fragile modules" in out
    assert "m0.py" in out and "m4.py" in out   # first 5 shown
    assert "m5.py" not in out                  # 6th dropped by [:5] cap
    # The fragile badge is rendered by _kind_badge_label('fragile') -> kills
    # line 430 ``== "fragile"`` (-> ``!=`` drops the badge) and line 431
    # ``return "<span ...>fragile</span>"`` (-> None renders the literal "None").
    assert "ibadge b-frag" in out
    assert ">fragile</span>" in out
    assert "None <code>m0.py" not in out


def test_architecture_section_appends_coordinator_and_nesting():
    """Kills line 421/422 ``body += _coordinator_block(p)`` / ``body += deep_nesting``
    augassign ``+=``->``-=`` (TypeError on the ``body`` string).

    When the chips branch runs (any of cycles/fragile/coordinators present), the
    two unconditional ``body += `` appends must execute; ``-=`` would raise.
    """
    out = s._architecture_section(_arch_profile(
        coordinator_modules=[{"module": "god.py", "fan_out": 9, "imports": ["x"]}],
        deeply_nested_functions=[{"module": "deep.py", "function": "f", "depth": 7}],
    ))
    assert "god.py" in out                 # coordinator block appended
    assert "deep.py" in out                # deep-nesting block appended


# ---------------------------------------------------------------------------
# _roadmap_section — phase numbering + the per-item ROI bar (line 586, 590)
#
# The roadmap card is only built through ``test_dashboard.py``'s full page, which
# asserts "Phase 1" exists but never the ROI-bar width math, and never the
# ``enumerate(..., start=1)`` numbering against a *second* phase. The
# ``int(i.roi / 10 * 100)`` width and the ``start=1`` base both went unchecked.
# ---------------------------------------------------------------------------


def _ritem(**over):
    base = dict(branch_path="x.py", title="do x", impact=0.8, effort=0.4,
                roi=5.0, fan_in=0, loc=0)
    base.update(over)
    return _ns(**base)


def _roadmap(**over):
    base = dict(
        stats={"total_items": 1, "mean_roi": 5.0, "quick_win_count": 0},
        quick_wins=[],
        phases=[_ns(name="Secure", theme="harden", items=[_ritem()])],
    )
    base.update(over)
    return _ns(**base)


def test_roadmap_section_phase_numbering_starts_at_one():
    """Kills line 586 ``enumerate(roadmap.phases, start=1)`` ``1``->``2``.

    The first phase must be labelled "Phase 1"; a second phase "Phase 2".
    Bumping the start to 2 would label them "Phase 2"/"Phase 3".
    """
    rm = _roadmap(phases=[
        _ns(name="Secure", theme="t", items=[_ritem()]),
        _ns(name="Evolve", theme="t", items=[_ritem()]),
    ])
    out = s._roadmap_section(rm)
    assert "Phase 1</span>" in out
    assert "Phase 2</span>" in out
    assert "Phase 3</span>" not in out


def test_roadmap_section_roi_bar_width_pins_division():
    """Kills line 590 ``int(i.roi / 10 * 100)`` arithmetic ``/``->``*`` and
    ``*``->``/`` (the ROI-bar fill width).

    With ROI 5.0 the bar is ``int(5.0 / 10 * 100) = 50`` -> ``width:50%``.
    ``/``->``*`` gives ``5000`` (clamped to 100%); ``*``->``/`` gives ``0``
    (clamped up to the 4% floor). Pinning ``width:50%`` kills both.
    """
    out = s._roadmap_section(_roadmap())
    assert "width:50%" in out


def test_roadmap_section_roi_bar_floor_and_cap():
    """Kills line 590 ``max(4, ...)`` ``4``->``5`` and ``min(100, ...)`` ``100``->``101``.

    A near-zero ROI clamps UP to the 4% floor (``width:4%``); a huge ROI clamps
    DOWN to the 100% cap (``width:100%``). Bumping the floor to 5 or the cap to
    101 would change those exact widths.
    """
    floor = s._roadmap_section(_roadmap(
        phases=[_ns(name="Secure", theme="t", items=[_ritem(roi=0.1)])]))
    assert "width:4%" in floor            # int(0.1/10*100)=1 -> max(4,1)=4
    cap = s._roadmap_section(_roadmap(
        phases=[_ns(name="Secure", theme="t", items=[_ritem(roi=50.0)])]))
    assert "width:100%" in cap            # int(50/10*100)=500 -> min(100,500)=100
    # roi 5.95 -> int(5.95/10*100)=59; the trailing ``* 100``->``* 101`` factor
    # would give int(5.95/10*101)=60, so pinning width:59% kills that literal too.
    odd = s._roadmap_section(_roadmap(
        phases=[_ns(name="Secure", theme="t", items=[_ritem(roi=5.95)])]))
    assert "width:59%" in odd


def test_roadmap_section_items_capped_at_eight():
    """Kills line 589 ``phase.items[:8]``->``[:9]`` truncation.

    A phase with 9 items shows only the first 8; the 9th's title is dropped.
    """
    items = [_ritem(title=f"item-{i}") for i in range(9)]
    out = s._roadmap_section(_roadmap(
        phases=[_ns(name="Secure", theme="t", items=items)]))
    assert "item-7" in out        # 8th shown
    assert "item-8" not in out    # 9th dropped by [:8] cap


# ---------------------------------------------------------------------------
# _actions_section — the ``plan.steps[:20]`` cap (line 533)
#
# ``test_reporting_mutation_hardening_eyml`` exercises _actions_section with a
# single step, so the 20-row truncation is never seen. 21 steps must show the
# first 20 only; the 21st is dropped.
# ---------------------------------------------------------------------------


def _step(**over):
    base = dict(executable=False, patch_preview=None, branch_path="b",
                action_type="at", description="desc", value=1)
    base.update(over)
    return _ns(**base)


def test_actions_section_caps_rows_at_twenty():
    """Kills line 533 ``plan.steps[:20]``->``[:21]`` truncation.

    With 21 steps the table shows the first 20 (descriptions ``d0``..``d19``);
    the 21st (``d20``) is dropped by the ``[:20]`` cap.
    """
    steps = [_step(description=f"d{i}") for i in range(21)]
    plan = _ns(steps=steps,
               stats={"total_steps": 21, "executable_steps": 0, "design_tasks": 21})
    out = s._actions_section(plan)
    assert ">d19<" in out          # 20th step shown
    assert ">d20<" not in out      # 21st dropped by [:20] cap


# ---------------------------------------------------------------------------
# _shape_section — the percentage read-outs + the "heaviest" gate (628/631/651)
#
# The covering shape test fixes ``facet_penetration=0.0``, ``total_measured_loc=0``
# and ``top_subject_share=0.5``, which makes several arithmetic/boundary flips
# coincide (``0 * 100 == 0 / 100``; a round 50%). A fixture with NON-zero,
# NON-round values exposes them: the facet percent (``* 100``), the heaviest-LOC
# gate (``loc > 0``), and the top-subject share percent.
# ---------------------------------------------------------------------------


def _shape(**over):
    base = dict(
        total_ideas=8, by_kind={"permutation": 8}, depth_distribution={0: 4, 1: 4},
        max_depth=1, branching_factor=2.0, distinct_subjects=4,
        facet_penetration=0.4, distinct_values=5, total_measured_loc=0,
        heaviest_module="", heaviest_loc=0, top_subject="app/x.py",
        top_subject_share=0.3, observations=["ok"],
        grounded_count=0, grounding_ratio=0.0,
    )
    base.update(over)
    return _ns(**base)


def test_shape_section_facet_and_subject_percentages():
    """Kills line 628 ``int(facet_penetration * 100)`` ``*``->``/`` and line 651
    ``int(top_subject_share * 100)`` ``*``->``/``.

    With facet 0.4 the facets chip reads ``40%`` (``0.4 * 100``); flipping ``*``
    to ``/`` gives ``int(0.4 / 100) = 0`` -> ``0%``. With share 0.3 the top
    subject reads ``(30%)``; ``*``->``/`` gives ``(0%)``.
    """
    # facet 0.408 -> int(0.408*100)=40 (``/`` would give 0; ``*101`` would give 41)
    # share 0.307 -> int(0.307*100)=30 (``/`` -> 0; ``*101`` -> 31)
    out = s._shape_section(_shape(facet_penetration=0.408, top_subject_share=0.307))
    assert "40%" in out          # facets 0.408 * 100
    assert "(30%)" in out        # top subject 0.307 * 100


def test_shape_section_heaviest_gate_is_strict_positive():
    """Kills line 631 ``total_measured_loc > 0`` flips (``>``->``>=``, ``>``->``<=``)
    and the ``0``->``1`` literal.

    With ``total_measured_loc == 0`` the "heaviest" chip is OMITTED (``0 > 0`` is
    False). ``>``->``>=`` would make ``0 >= 0`` true and wrongly add the chip;
    with a positive LOC the chip MUST appear, which pins the real branch.
    """
    absent = s._shape_section(_shape(total_measured_loc=0,
                                     heaviest_module="big.py", heaviest_loc=900))
    assert "heaviest" not in absent
    present = s._shape_section(_shape(total_measured_loc=1200,
                                      heaviest_module="big.py", heaviest_loc=900))
    assert "heaviest" in present
    assert "big.py (900 LOC)" in present
    # loc == 1 sits ON the boundary: ``1 > 0`` is true so the chip renders, but
    # ``1 > 1`` (the ``0``->``1`` literal flip) would drop it.
    edge = s._shape_section(_shape(total_measured_loc=1,
                                   heaviest_module="b.py", heaviest_loc=5))
    assert "heaviest" in edge


# ---------------------------------------------------------------------------
# _coordinator_block — the ``coordinators[:5]`` cap (line 302)
#
# The coordinator-block tests use <= 5 coordinators, so the 5-row truncation is
# never seen. Six coordinators must show only the first 5; the 6th is dropped.
# ---------------------------------------------------------------------------


def test_coordinator_block_caps_at_five():
    """Kills line 302 ``coordinators[:5]``->``[:6]`` truncation."""
    coords = [{"module": f"c{i}.py", "fan_out": 9, "imports": []} for i in range(6)]
    out = s._coordinator_block(_ns(coordinator_modules=coords))
    assert "c4.py" in out          # 5th shown
    assert "c5.py" not in out      # 6th dropped by [:5] cap


# ---------------------------------------------------------------------------
# _ideas_section — synthesis selection + ordering (line 489, 513)
#
# The ideas tests use a single permutation root, so the "synthesized" sub-list
# (parentless, kind != "permutation", sorted by value descending) is never
# exercised. The ``and`` that picks synth ideas and the ``reverse=True`` that
# orders them both went unchecked.
# ---------------------------------------------------------------------------


def _idea(**over):
    base = dict(
        id="x", title="t", subject="app/x.py", rationale="r", branch_path="x",
        depth=0, parent_id=None, source_facts=[], operator="op",
        operator_chain=["op"], kind="permutation", relevance=1.0, novelty=1.0,
        feasibility=1.0, value=0.5, caveats=[], anchors=[],
    )
    base.update(over)
    return IdeaNode(**base)


def _report(*ideas):
    return IdeaTreeReport(
        objective="o", ideas=list(ideas),
        stats={"total_ideas": len(ideas), "mean_value": 0.5, "synthesized": 0},
    )


def test_ideas_section_synthesis_block_sorted_by_value_desc():
    """Kills line 513 ``sorted(synth, ..., reverse=True)`` ``True``->``False``.

    Two synthesized ideas render in the "Synthesized" block ordered by value
    DESCENDING (high before low). Flipping ``reverse`` to ``False`` would put
    the low-value idea first.
    """
    lo = _idea(id="s_lo", kind="synthesis", title="LOW-synth", value=0.2)
    hi = _idea(id="s_hi", kind="synthesis", title="HIGH-synth", value=0.9)
    out = s._ideas_section(_report(lo, hi))
    assert "HIGH-synth" in out and "LOW-synth" in out
    assert out.index("HIGH-synth") < out.index("LOW-synth")   # value desc


# NOTE: line 489 ``i.kind != "permutation" and i.parent_id is None`` -> ``or`` is
# an EQUIVALENT mutant here. The ``synth`` list it builds feeds both the
# ``synth_html`` block AND ``synth_ids`` (which prunes ``perm_roots``); for every
# idea shape tried (a permutation root, a parented non-permutation facet) the two
# effects cancel so the rendered HTML is byte-identical under ``and``/``or``.
# It is therefore left unkilled by design rather than pinned with a brittle test.


# ---------------------------------------------------------------------------
# _pareto_section / _trajectory_section — row caps + the sparkline gate
# ---------------------------------------------------------------------------


def test_pareto_section_caps_rows_at_twelve():
    """Kills line 691 ``points[:12]``->``[:13]`` truncation."""
    pts = [_ns(branch_path=f"b{i}", title=f"pt-{i}", reasons=["r"],
               impact=1, effort=1, roi=1.0) for i in range(13)]
    out = s._pareto_section(pts, 20)
    assert "pt-11" in out          # 12th shown
    assert "pt-12" not in out      # 13th dropped by [:12] cap


def test_trajectory_sparkline_gate_needs_two_points():
    """Kills line 729 ``len(series) >= 2`` boundary flips (``>=``->``>``, ``2``->``3``).

    Two recorded runs with a numeric ``security_findings`` make a 2-point series,
    which renders the "findings trend" sparkline. With a single point the trend
    is omitted. ``>=``->``>`` or ``2``->``3`` would suppress the 2-point spark.
    """
    two = s._trajectory_section([
        {"ts": "a", "after": {"security_findings": 5}},
        {"ts": "b", "after": {"security_findings": 3}},
    ])
    assert "findings trend" in two
    one = s._trajectory_section([{"ts": "a", "after": {"security_findings": 5}}])
    assert "findings trend" not in one


def test_trajectory_section_caps_rows_at_ten():
    """Kills line 741 ``history[-10:]``->``[-11:]`` truncation.

    With 11 runs the table body shows only the last 10 (timestamps ``t1``..``t10``);
    the oldest (``t0``) is dropped by the ``[-10:]`` slice.
    """
    hist = [{"ts": f"t{i}", "applied": 0, "mode": "m"} for i in range(11)]
    out = s._trajectory_section(hist)
    assert ">t10<" in out          # newest kept
    assert ">t1<" in out           # 10th-from-end kept
    assert ">t0<" not in out       # oldest dropped by [-10:]


# ---------------------------------------------------------------------------
# _quality_* helpers — the hotspot/worst-module row caps (990/1032/1054)
# ---------------------------------------------------------------------------


def test_quality_type_hints_worst_modules_capped_at_five():
    """Kills line 990 ``worst[...][:5]``->``[:6]`` and the ``ratio < 1.0`` filter.

    Six modules under 100% type-hint coverage render only the first 5 as
    "thinnest-typed"; the 6th is dropped. A fully-annotated module (ratio 1.0)
    is filtered out entirely.
    """
    worst = [{"module": f"thin{i}.py", "ratio": 0.1 * i, "annotated": i, "total": 10}
             for i in range(6)]
    worst.append({"module": "full.py", "ratio": 1.0, "annotated": 10, "total": 10})
    th = _ns(total_functions=70, overall_ratio=0.5, annotated_functions=35,
             worst_modules=worst)
    chips, blocks = s._quality_type_hints(th)
    body = "".join(blocks)
    assert "thin0.py" in body and "thin4.py" in body   # first 5 shown
    assert "thin5.py" not in body                       # 6th dropped by [:5]
    assert "full.py" not in body                        # ratio 1.0 filtered out (< 1.0)


def test_quality_complexity_hotspots_capped_at_five():
    """Kills line 1032 ``cx.hotspots[:5]``->``[:6]`` truncation."""
    hotspots = [{"module": f"m{i}.py", "function": f"f{i}", "complexity": 20 - i}
                for i in range(6)]
    cx = _ns(total=100, threshold=10, over_threshold=6, max=20, mean=5, median=4,
             hotspots=hotspots)
    chips, blocks = s._quality_complexity(cx)
    body = "".join(blocks)
    assert "f0" in body and "f4" in body   # first 5 shown
    assert "f5" not in body                 # 6th dropped by [:5]


def test_quality_todo_debt_markers_capped_at_five():
    """Kills line 1054 ``td.items[:5]``->``[:6]`` truncation."""
    items = [{"module": f"m{i}.py", "line": i, "marker": "TODO", "text": f"txt{i}"}
             for i in range(6)]
    td = _ns(total=6, by_marker={"TODO": 6}, items=items)
    chips, blocks = s._quality_todo_debt(td)
    body = "".join(blocks)
    assert "txt0" in body and "txt4" in body   # first 5 shown
    assert "txt5" not in body                   # 6th dropped by [:5]


# ---------------------------------------------------------------------------
# _reasoning_section / _proof_section / _dream_section — list caps
# ---------------------------------------------------------------------------


def test_reasoning_section_claims_capped_at_ten():
    """Kills line 1121 ``confidence_map.items())[:10]``->``[:11]`` truncation."""
    cmap = {f"claim{i}": 0.5 for i in range(11)}
    out = s._reasoning_section({"mode": "m", "confidence_map": cmap,
                                "debug_stats": {}, "estimated_total_tokens": 1})
    assert "claim9" in out         # 10th shown (insertion order preserved)
    assert "claim10" not in out    # 11th dropped by [:10]


def test_proof_section_fixes_capped_at_twelve(tmp_path):
    """Kills line 1158 ``(proof.get("fixes") ...)[:12]``->``[:13]`` truncation."""
    import json
    fixes = [{"outcome": "applied",
              "finding": {"action": "a", "target": f"tgt{i}.py"},
              "verification": {"strength": {"level": "module"}}}
             for i in range(13)]
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text(
        json.dumps({"totals": {"applied": 13}, "fixes": fixes}))
    out = s._proof_section(str(tmp_path))
    assert "tgt11.py" in out        # 12th shown
    assert "tgt12.py" not in out    # 13th dropped by [:12]


def test_dream_section_items_capped_at_fourteen(tmp_path):
    """Kills line 1268 ``items[:14]``->``[:15]`` truncation."""
    apex = tmp_path / ".apex"
    apex.mkdir()
    lines = "\n".join(f"- bullet{i}" for i in range(15))
    (apex / "dream-digest.md").write_text(lines + "\n")
    out = s._dream_section(str(tmp_path))
    assert "bullet13" in out        # 14th shown
    assert "bullet14" not in out    # 15th dropped by [:14]
