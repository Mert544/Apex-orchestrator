"""Characterization test pinning ``cmd_ideate``'s branch dispatch.

The heavy builders (engine, roadmap synthesizer, action bridge, …) are
monkeypatched with light fakes so each flag combination's *dispatch path* and
*return code* are exercised deterministically, without a real codebase scan.

This locks the mechanical decomposition of ``cmd_ideate`` into private helpers:
the same flag must route to the same helper and yield the same return code.
"""

from __future__ import annotations

import argparse

import app.cli_ideate as ci


def _ns(**ov) -> argparse.Namespace:
    base = dict(
        target="", objective="", depth=2, breadth=3, max_ideas=20,
        min_relevance=0.0, actions=False, top=0, draft=False, apply=False,
        verify=False, commit=False, max_apply=0, mode="supervised",
        mermaid=False, json=False, out="", kind="", roadmap=False, facets=False,
        facet_depth=1, shape=False, pareto=False, sequence=False, adaptive=False,
        budget=0.0, invest=False, phase="", save=False, diff=False,
    )
    base.update(ov)
    return argparse.Namespace(**base)


class _FakeReport:
    ideas: list = []

    def model_dump(self):
        return {"ideas": []}


class _FakeEngine:
    last_profile = None


def _install_fakes(monkeypatch, calls):
    """Stub every helper so each branch records the dispatch and prints nothing."""
    monkeypatch.setattr(ci, "_get_project_root", lambda: ci.Path("/proj"))
    monkeypatch.setattr(
        ci, "_build_ideate_report", lambda args, target: (_FakeEngine(), _FakeReport())
    )

    # IdeaMemory.load is imported inside cmd_ideate from app.engine.idea_memory.
    import app.engine.idea_memory as mem
    monkeypatch.setattr(mem.IdeaMemory, "load", staticmethod(lambda root: object()))

    def _roadmap_view(args, report, target, memory):
        calls.append("roadmap_view")
        return 7 if getattr(args, "diff", False) else 0

    def _analysis_view(args, report, target, memory):
        for flag in ("invest", "budget", "sequence", "pareto", "shape"):
            if getattr(args, flag, False):
                calls.append(f"analysis:{flag}")
                return True
        return False

    def _kind_view(args, report, target, kind):
        calls.append(f"kind:{kind}")

    def _action_plan(args, report, target):
        calls.append("action_plan")
        return ("PLAN", {"r": 1}) if getattr(args, "apply", False) else ("PLAN", None)

    def _render(args, report, action_plan, apply_results, confluence):
        calls.append(f"render:plan={action_plan is not None}")

    def _write_out(args, report, action_plan):
        calls.append("write_out")

    monkeypatch.setattr(ci, "_ideate_roadmap_view", _roadmap_view)
    monkeypatch.setattr(ci, "_ideate_analysis_view", _analysis_view)
    monkeypatch.setattr(ci, "_ideate_kind_view", _kind_view)
    monkeypatch.setattr(ci, "_ideate_action_plan", _action_plan)
    monkeypatch.setattr(ci, "_render_ideate", _render)
    monkeypatch.setattr(ci, "_ideate_write_out", _write_out)
    monkeypatch.setattr(ci, "_confluence_entries", lambda profile: [])


def test_roadmap_view_branch(monkeypatch):
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    rc = ci.cmd_ideate(_ns(roadmap=True))
    assert rc == 0
    assert calls == ["roadmap_view"]


def test_roadmap_diff_propagates_return_code(monkeypatch):
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    rc = ci.cmd_ideate(_ns(roadmap=True, diff=True))
    # The fake roadmap view returns 7 on --diff; cmd_ideate must propagate it.
    assert rc == 7
    assert calls == ["roadmap_view"]


def test_roadmap_with_actions_skips_roadmap_view(monkeypatch):
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    rc = ci.cmd_ideate(_ns(roadmap=True, actions=True))
    assert rc == 0
    # --actions diverts away from the view-only roadmap branch into the bridge.
    assert "roadmap_view" not in calls
    assert calls == ["action_plan", "render:plan=True"]


def test_analysis_flags_each_route_and_return_zero(monkeypatch):
    for flag in ("invest", "sequence", "pareto", "shape"):
        calls: list[str] = []
        _install_fakes(monkeypatch, calls)
        rc = ci.cmd_ideate(_ns(**{flag: True}))
        assert rc == 0
        assert calls == [f"analysis:{flag}"]


def test_budget_routes_to_analysis(monkeypatch):
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    rc = ci.cmd_ideate(_ns(budget=2.0))
    assert rc == 0
    assert calls == ["analysis:budget"]


def test_kind_branch(monkeypatch):
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    rc = ci.cmd_ideate(_ns(kind="permutation"))
    assert rc == 0
    assert calls == ["kind:permutation"]


def test_kind_all_falls_through_to_default(monkeypatch):
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    rc = ci.cmd_ideate(_ns(kind="all"))
    assert rc == 0
    # kind == "all" is not a focused filter; it falls through to default render.
    assert calls == ["render:plan=False"]


def test_default_render_branch(monkeypatch):
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    rc = ci.cmd_ideate(_ns())
    assert rc == 0
    assert calls == ["render:plan=False"]


def test_actions_branch_builds_plan_then_renders(monkeypatch):
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    rc = ci.cmd_ideate(_ns(actions=True))
    assert rc == 0
    assert calls == ["action_plan", "render:plan=True"]


def test_out_triggers_write(monkeypatch):
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    rc = ci.cmd_ideate(_ns(out="/tmp/x.md"))
    assert rc == 0
    assert calls == ["render:plan=False", "write_out"]


def test_dispatch_priority_roadmap_view_wins_over_analysis(monkeypatch):
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    # Both --roadmap (view) and --shape set: roadmap view is checked first.
    rc = ci.cmd_ideate(_ns(roadmap=True, shape=True))
    assert rc == 0
    assert calls == ["roadmap_view"]
