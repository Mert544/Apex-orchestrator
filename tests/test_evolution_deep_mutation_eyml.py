"""Deep mutation hardening for ``app.engine.evolution`` past the 30-mutant cap.

The mutation tester's default ``max_mutants=30`` only ever seeds the first 30
sites in document order, so the back half of this module — the ``run()`` loop
accumulators, the circuit-breaker boundary, the ``_measure`` ``.get`` defaults,
the constructor/dataclass defaults, and the ``render_evolution_markdown``
``_delta`` direction logic — is never exercised by the live mutation run.

Enumerating the FULL universe (``_collect_sites`` => 75 sites) and splicing each
against the focused evolution tests surfaced 45 survivors. The characterization
tests below pin the behaviour of the 40 REAL (killable) survivors so a flip in
any of those tokens is now caught. The remaining 5 survivors are genuinely
EQUIVALENT (28, 47, 50, 52, 53) and are documented (not asserted) at the bottom
of this module.

Every test is deterministic: no timestamps, no wall-clock, no set/dict ordering
assumptions. The loop-internal tests stub every collaborator ``run()`` imports
so the loop executes cheaply with fully controlled summaries.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.evolution import (
    EvolutionLoop,
    EvolutionResult,
    render_evolution_markdown,
)


# --------------------------------------------------------------------------- #
# Constructor + dataclass defaults (sites 0,1,3,4,5,6,7) and the ``max(1, …)``  #
# floors (sites 9,10). The focused suite always constructs with explicit       #
# arguments, so the default literals/floors went untested.                     #
# --------------------------------------------------------------------------- #

def test_evolution_result_default_committed_and_circuit_broken():
    # Sites 0 (``committed: int = 0``) and 1 (``circuit_broken: bool = False``):
    # the dataclass defaults are filled when the optional fields are omitted.
    result = EvolutionResult(
        cycles_run=1, reached_fixpoint=True, applied=0, rolled_back=0,
        before={}, after={}, roadmap_diff={"dropped": []},
    )
    assert result.committed == 0
    assert result.circuit_broken is False
    # The other defaulted fields are pinned too, for completeness.
    assert result.per_cycle == []
    assert result.mode == "supervised"
    assert result.stop_reason == ""


def test_evolution_loop_constructor_defaults():
    # Sites 3,4,5,6,7: every ``__init__`` default literal, asserted directly.
    loop = EvolutionLoop("/tmp/proj")
    assert loop.max_cycles == 3            # site 3 (3 -> 4)
    assert loop.max_apply_per_cycle == 5   # site 4 (5 -> 6)
    assert loop.verify is True             # site 5 (True -> False)
    assert loop.commit is False            # site 6 (False -> True)
    assert loop.max_rollbacks_per_cycle == 3  # site 7 (3 -> 4)
    assert loop.mode == "supervised"
    assert loop.objective is None


def test_evolution_loop_floors_clamp_to_one():
    # Sites 9 (``max(1, max_apply_per_cycle)``) and 10
    # (``max(1, max_rollbacks_per_cycle)``): a zero/negative input is clamped up
    # to 1, never left at the input. (If the floor literal were 2, these would
    # become 2; if the call were dropped, they would stay 0.)
    loop = EvolutionLoop(
        "/tmp/proj", max_cycles=0, max_apply_per_cycle=0,
        max_rollbacks_per_cycle=0,
    )
    assert loop.max_cycles == 1
    assert loop.max_apply_per_cycle == 1
    assert loop.max_rollbacks_per_cycle == 1


# --------------------------------------------------------------------------- #
# ``_build_report`` config + objective (sites 11,12,13,14). The permutation     #
# engine is stubbed so we can read exactly which config / objective it got.    #
# --------------------------------------------------------------------------- #

def test_build_report_passes_fixed_config_and_objective(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeEngine:
        def __init__(self, config, project_root):
            captured["config"] = config
            captured["project_root"] = project_root

        def run(self, objective=None):
            captured["objective"] = objective
            return "REPORT"

    import app.engine.idea_permutation as ip
    monkeypatch.setattr(ip, "IdeaPermutationEngine", _FakeEngine)

    loop = EvolutionLoop("/tmp/proj", objective="harden")
    assert loop._build_report() == "REPORT"
    # Sites 11,12,13: the three config literals are exactly these values.
    assert captured["config"] == {
        "max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4,
    }
    # Site 14 (``self.objective or None``): a truthy objective is forwarded.
    assert captured["objective"] == "harden"


def test_build_report_objective_or_none_falls_back(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeEngine:
        def __init__(self, config, project_root):
            pass

        def run(self, objective=None):
            captured["objective"] = objective
            return "REPORT"

    import app.engine.idea_permutation as ip
    monkeypatch.setattr(ip, "IdeaPermutationEngine", _FakeEngine)

    # An empty-string objective is falsy: ``"" or None`` -> None is forwarded.
    loop = EvolutionLoop("/tmp/proj", objective="")
    loop._build_report()
    assert captured["objective"] is None


# --------------------------------------------------------------------------- #
# ``_measure`` ``.get`` defaults + the ``or 0`` guard (sites 15,16,17,19,20,21).#
# Everything ``_measure`` touches is stubbed so the default branches are forced.#
# --------------------------------------------------------------------------- #

class _Stats:
    def __init__(self, d):
        self._d = d

    def get(self, k, default=None):
        return self._d.get(k, default)


def _patch_measure(monkeypatch, *, roadmap_stats, plan_stats, report_stats,
                   findings_run):
    class _Roadmap:
        stats = _Stats(roadmap_stats)

    class _Plan:
        stats = _Stats(plan_stats)

    class _Synth:
        def build(self, report):
            return _Roadmap()

    class _Bridge:
        def plan_roadmap(self, *a, **k):
            return _Plan()

    class _Agent:
        def __init__(self, *a, **k):
            pass

        def run(self, *a, **k):
            return findings_run

    import app.agents.skills as skills
    import app.engine.idea_action_bridge as iab
    import app.engine.idea_roadmap as ir
    monkeypatch.setattr(ir, "RoadmapSynthesizer", _Synth)
    monkeypatch.setattr(iab, "IdeaActionBridge", _Bridge)
    monkeypatch.setattr(skills, "SecurityAgent", _Agent)

    class _Report:
        stats = _Stats(report_stats)

    return _Report()


def test_measure_uses_get_defaults_when_keys_absent(monkeypatch):
    # Sites 15,17 (the two ``0`` literals in ``.get("findings_count", 0) or 0``),
    # 19 (``mean_roi`` default ``0.0``), 20 (``executable_steps`` default ``0``),
    # 21 (``total_ideas`` default ``0``): every stats dict is EMPTY so each
    # ``.get`` returns its default verbatim.
    report = _patch_measure(
        monkeypatch, roadmap_stats={}, plan_stats={}, report_stats={},
        findings_run={},  # no "findings_count" key -> .get default 0
    )
    measure = EvolutionLoop("/tmp/proj")._measure(report)
    assert measure["security_findings"] == 0
    assert measure["mean_roi"] == 0.0
    assert measure["executable_fixes"] == 0
    assert measure["total_ideas"] == 0


def test_measure_findings_or_guard_keeps_real_count(monkeypatch):
    # Site 16 (``... or 0`` -> ``... and 0``): with a real positive count present,
    # ``5 or 0`` keeps 5, whereas the ``and`` mutant would collapse it to 0.
    report = _patch_measure(
        monkeypatch, roadmap_stats={"mean_roi": 2.5},
        plan_stats={"executable_steps": 7}, report_stats={"total_ideas": 9},
        findings_run={"findings_count": 5},
    )
    measure = EvolutionLoop("/tmp/proj")._measure(report)
    assert measure["security_findings"] == 5
    assert measure["mean_roi"] == 2.5
    assert measure["executable_fixes"] == 7
    assert measure["total_ideas"] == 9


# --------------------------------------------------------------------------- #
# ``run()`` loop internals (sites 23,24,25,26,32,33,34,35,37,38,39,40). All     #
# collaborators are stubbed so the loop runs cheaply with controlled summaries  #
# and we can assert exact accumulator / flag values.                           #
# --------------------------------------------------------------------------- #

class _FakeMemory:
    def __init__(self):
        self.recorded = []
        self.saved = False

    @classmethod
    def load(cls, project_root, path=None):
        return cls()

    def record_outcomes(self, summary):
        self.recorded.append(summary)

    def save(self, project_root, path=None):
        self.saved = True


class _FakeDiff:
    def to_dict(self):
        return {"dropped": []}


def _patch_run(monkeypatch, summaries, *, capture=None):
    """Stub everything ``run()`` imports. ``summaries`` is consumed one per
    cycle (the apply_plan return values)."""
    seq = list(summaries)

    class _Bridge:
        def plan_roadmap(self, report, mode=None, project_root=None,
                         draft=None):
            if capture is not None:
                capture["draft"] = draft
                capture["plan_mode"] = mode
            return "PLAN"

        def apply_plan(self, plan, project_root, mode=None, verify=None,
                       max_apply=None, commit=None):
            return seq.pop(0)

    import app.engine.idea_action_bridge as iab
    import app.engine.idea_memory as im
    import app.engine.roadmap_history as rh
    monkeypatch.setattr(iab, "IdeaActionBridge", _Bridge)
    monkeypatch.setattr(im, "IdeaMemory", _FakeMemory)
    monkeypatch.setattr(rh, "roadmap_to_snapshot", lambda roadmap: {})
    monkeypatch.setattr(rh, "diff_roadmaps", lambda prev, cur: _FakeDiff())


def _make_loop(monkeypatch, **kw):
    loop = EvolutionLoop("/tmp/proj", **kw)
    monkeypatch.setattr(loop, "_build_report", lambda: "REPORT")
    monkeypatch.setattr(
        loop, "_measure",
        lambda report: {"security_findings": 0, "mean_roi": 0.0,
                        "executable_fixes": 0, "total_ideas": 0, "_roadmap": {}},
    )
    return loop


def test_run_accumulates_exact_totals_across_cycles(monkeypatch):
    # Sites 23,24,25 (accumulator inits start at 0) and 37,38 (``total_rolled``,
    # ``total_committed`` use ``+=``): two cycles whose summaries sum to known
    # totals. A non-zero init or a dropped accumulation would shift these.
    _patch_run(monkeypatch, [
        {"applied": 2, "rolled_back": 1, "blocked": 0, "committed": 1},
        {"applied": 3, "rolled_back": 1, "blocked": 0, "committed": 2},
    ])
    loop = _make_loop(monkeypatch, max_cycles=2, max_rollbacks_per_cycle=5)
    result = loop.run()
    assert result.applied == 5      # 2 + 3 (init 0 -> site 23)
    assert result.rolled_back == 2  # 1 + 1 (init 0 -> site 24; += -> site 37)
    assert result.committed == 3    # 1 + 2 (init 0 -> site 25; += -> site 38)
    assert result.cycles_run == 2


def test_run_summary_get_defaults_when_keys_missing(monkeypatch):
    # Sites 33,34,35 (``summary.get("applied"/"rolled_back"/"committed", 0)``)
    # and 39 (``"blocked"`` default 0): an EMPTY summary forces every default,
    # so applied==0 also trips the fixpoint branch.
    _patch_run(monkeypatch, [{}])
    loop = _make_loop(monkeypatch, max_cycles=3, max_rollbacks_per_cycle=5)
    result = loop.run()
    assert result.applied == 0
    assert result.rolled_back == 0
    assert result.committed == 0
    assert result.per_cycle[0]["blocked"] == 0
    # applied == 0 means the loop reached a fixpoint on the first cycle.
    assert result.reached_fixpoint is True
    assert result.cycles_run == 1


def test_run_circuit_breaker_boundary_is_inclusive(monkeypatch):
    # Site 40 (``rolled >= self.max_rollbacks_per_cycle``, boundary ``>=``):
    # rolled EXACTLY equal to the threshold must trip the breaker. The ``>``
    # boundary mutant would NOT trip here; the ``<`` negation mutant inverts it.
    _patch_run(monkeypatch, [
        {"applied": 1, "rolled_back": 3, "blocked": 0, "committed": 0},
    ])
    loop = _make_loop(monkeypatch, max_cycles=3, max_rollbacks_per_cycle=3)
    result = loop.run()
    assert result.circuit_broken is True
    assert result.cycles_run == 1
    # Site 26 (``reached_fixpoint = False`` init): a circuit-broken run never
    # reaches a fixpoint, so the flag stays False (init not flipped to True).
    assert result.reached_fixpoint is False
    assert "circuit breaker" in result.stop_reason.lower()


def test_run_just_below_breaker_threshold_continues(monkeypatch):
    # Complements the boundary test: rolled one below the threshold does NOT
    # break (so the ``>=`` is genuinely the boundary, not a looser ``>``-style).
    _patch_run(monkeypatch, [
        {"applied": 1, "rolled_back": 2, "blocked": 0, "committed": 0},
        {"applied": 0, "rolled_back": 0, "blocked": 0, "committed": 0},
    ])
    loop = _make_loop(monkeypatch, max_cycles=3, max_rollbacks_per_cycle=3)
    result = loop.run()
    assert result.circuit_broken is False
    assert result.reached_fixpoint is True  # 2nd cycle applied 0
    assert result.cycles_run == 2


def test_run_forwards_draft_true_and_mode_to_plan_roadmap(monkeypatch):
    # Site 32 (``draft=True`` keyword on the planning call): the loop always
    # plans with ``draft=True`` and forwards its own mode.
    capture: dict[str, object] = {}
    _patch_run(monkeypatch, [
        {"applied": 0, "rolled_back": 0, "blocked": 0, "committed": 0},
    ], capture=capture)
    loop = _make_loop(monkeypatch, mode="autonomous", max_cycles=1)
    loop.run()
    assert capture["draft"] is True
    assert capture["plan_mode"] == "autonomous"


# --------------------------------------------------------------------------- #
# ``render_evolution_markdown`` ``_delta`` direction + defaults                  #
# (sites 48,49,51,55,56,57,58). The remaining L204 sites — 50, 52, 53 — are     #
# equivalent (see the documented block at the bottom of this module).          #
# --------------------------------------------------------------------------- #

def _render_result(**over):
    base = dict(
        cycles_run=1, reached_fixpoint=True, applied=2, rolled_back=0,
        before={"security_findings": 3, "executable_fixes": 5, "mean_roi": 2.0},
        after={"security_findings": 1, "executable_fixes": 2, "mean_roi": 1.0},
        roadmap_diff={"dropped": []}, per_cycle=[], mode="supervised",
    )
    base.update(over)
    return EvolutionResult(**base)


def test_delta_lower_is_better_marks_improvement_with_check(monkeypatch):
    # Site 51 (``av < bv`` negation flip ``<`` -> ``>=``) and sites 55,56 (the
    # ``lower_is_better=True`` arguments): when a lower-is-better metric FALLS,
    # the row is marked improved (✅), not regressed (⚠️).
    md = render_evolution_markdown(_render_result(), "/tmp/proj")
    sec_line = next(ln for ln in md.splitlines() if "Security findings" in ln)
    fix_line = next(ln for ln in md.splitlines() if "Open safe fixes" in ln)
    # 3 -> 1 and 5 -> 2 are both improvements for lower-is-better metrics.
    assert "3 → 1" in sec_line and "✅" in sec_line and "⚠️" not in sec_line
    assert "5 → 2" in fix_line and "✅" in fix_line and "⚠️" not in fix_line


def test_delta_lower_is_better_marks_regression_with_warning():
    # Same direction logic, opposite data: a lower-is-better metric that RISES
    # is flagged as a regression (⚠️), pinning the ``av < bv`` comparison sense.
    result = _render_result(
        before={"security_findings": 1, "executable_fixes": 2, "mean_roi": 1.0},
        after={"security_findings": 3, "executable_fixes": 5, "mean_roi": 2.0},
    )
    md = render_evolution_markdown(result, "/tmp/proj")
    sec_line = next(ln for ln in md.splitlines() if "Security findings" in ln)
    assert "1 → 3" in sec_line and "⚠️" in sec_line and "✅" not in sec_line


def test_delta_equal_values_get_no_mark():
    # Boundary completeness: when before == after, neither ✅ nor ⚠️ appears
    # (the ``av != bv`` gate short-circuits before ``better`` is consulted).
    # NOTE: this is exactly why the L204 boundary mutant 50 (``<`` -> ``<=``) is
    # equivalent — the only value it changes is ``better`` at equality, which is
    # never read here.
    result = _render_result(
        before={"security_findings": 4, "executable_fixes": 4, "mean_roi": 1.0},
        after={"security_findings": 4, "executable_fixes": 4, "mean_roi": 1.0},
    )
    md = render_evolution_markdown(result, "/tmp/proj")
    sec_line = next(ln for ln in md.splitlines() if "Security findings" in ln)
    assert "4 → 4" in sec_line
    assert "✅" not in sec_line and "⚠️" not in sec_line


def test_delta_missing_keys_default_to_zero(monkeypatch):
    # Sites 48,49 (``b.get(key, 0)``, ``a.get(key, 0)``) and 57
    # (``b.get('mean_roi', 0)``): before/after dicts missing the keys render 0.
    result = _render_result(before={}, after={})
    md = render_evolution_markdown(result, "/tmp/proj")
    sec_line = next(ln for ln in md.splitlines() if "Security findings" in ln)
    roi_line = next(ln for ln in md.splitlines() if "Mean ROI" in ln)
    assert "0 → 0" in sec_line
    assert "0 → 0" in roi_line


def test_resolved_ideas_capped_at_twelve():
    # Site 58 (``resolved[:12]``): with 13 resolved ideas, only the first 12 are
    # listed. The ``[:13]`` mutant would render all 13.
    dropped = [{"title": f"idea-{i}"} for i in range(13)]
    result = _render_result(roadmap_diff={"dropped": dropped})
    md = render_evolution_markdown(result, "/tmp/proj")
    rendered = [ln for ln in md.splitlines() if ln.startswith("- idea-")]
    assert len(rendered) == 12
    assert "- idea-0" in md and "- idea-11" in md
    assert "- idea-12" not in md


# --------------------------------------------------------------------------- #
# ``record_run`` — directory creation + return value (sites 61, 64).            #
# --------------------------------------------------------------------------- #

def test_record_run_returns_log_path(tmp_path):
    # Site 64 (``return log`` -> ``return None``): the function returns the Path
    # it wrote to, not None.
    from app.engine.evolution import record_run

    result = _render_result()
    log = record_run(result, str(tmp_path))
    assert isinstance(log, Path)
    assert log == Path(tmp_path) / "/".join((".apex", "evolution-history.jsonl"))
    assert log.exists()


def test_record_run_creates_missing_parent_dirs(tmp_path):
    # Site 61 (``mkdir(parents=True, ...)`` -> ``parents=False``): the explicit
    # ``path`` points several levels deep into directories that do not exist yet,
    # so the write only succeeds if intermediate parents are created. With
    # ``parents=False`` this would raise FileNotFoundError.
    from app.engine.evolution import record_run

    nested = Path(tmp_path) / "a" / "b" / "c" / "history.jsonl"
    assert not nested.parent.exists()
    log = record_run(_render_result(), str(tmp_path), path=nested)
    assert log == nested
    assert nested.exists()


# --------------------------------------------------------------------------- #
# EQUIVALENT survivors (documented, not asserted)                              #
# --------------------------------------------------------------------------- #
#
# Site 28 — ``cycles_run = 0`` (the init before the cycle loop): ``run()`` loops
#   over ``range(1, self.max_cycles + 1)`` and ``max_cycles`` is floored to >= 1
#   in ``__init__``, so the loop body always executes at least once and
#   immediately reassigns ``cycles_run = cycle``. The init value is therefore
#   dead on every reachable path; flipping ``0`` to ``1`` is unobservable.
#
# Site 47 — ``def _delta(..., lower_is_better: bool = True)`` (the default
#   parameter value): both call sites (lines 209 and 210) pass
#   ``lower_is_better=True`` explicitly, and there is no third call that relies
#   on the default, so flipping the default to ``False`` changes no behaviour.
#
# Sites 52 & 53 — the ``else`` arm of ``(av < bv) if lower_is_better else
#   (av > bv)`` on line 204. Because every call passes ``lower_is_better=True``
#   (site 47, above), the ``av > bv`` else-branch is dead code, so neither the
#   boundary flip (52: ``>`` -> ``>=``) nor the negation flip (53: ``>`` ->
#   ``<=``) is ever evaluated.
#
# Site 50 — the boundary flip ``av < bv`` -> ``av <= bv`` on line 204. It only
#   changes ``better`` when ``av == bv``, but ``mark`` consults ``better`` solely
#   inside the ``av != bv`` guard, so the equality case never reads it (see
#   ``test_delta_equal_values_get_no_mark``).
#
# These five are genuinely equivalent mutants — unkillable by any test without
# changing the source — so they are recorded here rather than chased.
