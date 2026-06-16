"""Characterization test: render_roadmap_markdown decomposition is byte-identical.

Loads the pre-refactor snapshot of idea_roadmap.py (captured from git HEAD into a
scratch module) and compares its render_roadmap_markdown output against the live
refactored implementation over many hand-built roadmaps that exercise every
branch: empty roadmap, header objective on/off, best-first-move present/absent,
quick-wins present/absent, measured suffix (fan_in/loc combinations), and the
why-line (rationale / source_facts / payoff / nothing).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from app.engine.idea_roadmap import (
    Roadmap,
    RoadmapItem,
    RoadmapPhase,
    render_roadmap_markdown,
)

_REPO = Path(__file__).resolve().parents[1]


def _load_original_render():
    """Materialize the HEAD version of the module and return its renderer."""
    src = subprocess.check_output(
        ["git", "show", "HEAD:app/engine/idea_roadmap.py"],
        cwd=_REPO,
        text=True,
    )
    scratch = _REPO / "tests" / "_orig_idea_roadmap_eyml1y.py"
    scratch.write_text(src)
    try:
        spec = importlib.util.spec_from_file_location(
            "_orig_idea_roadmap_eyml1y", scratch
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod  # dataclass introspection needs this
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop("_orig_idea_roadmap_eyml1y", None)
        scratch.unlink(missing_ok=True)
    return mod


_ORIG = _load_original_render()


def _item(**kw) -> RoadmapItem:
    base = dict(
        branch_path="x.0",
        title="Do the thing",
        subject="app/foo.py",
        phase="Stabilize",
        impact=0.6,
        effort=0.4,
        roi=1.5,
        value=0.7,
        kind="permutation",
        rationale="",
        fan_in=0,
        loc=0,
        source_facts=[],
    )
    base.update(kw)
    return RoadmapItem(**base)


def _roadmaps() -> list[Roadmap]:
    cases: list[Roadmap] = []

    # 1. Fully empty roadmap (no phases -> no best move, no quick wins).
    cases.append(Roadmap(objective="", project_root="/repo"))

    # 2. Empty but with objective set.
    cases.append(Roadmap(objective="ship faster", project_root="/repo", stats={
        "total_items": 0, "mean_roi": 0.0}))

    # 3. Single phase, single bare item (no fan_in/loc/rationale/facts).
    cases.append(Roadmap(
        objective="", project_root="/p",
        phases=[RoadmapPhase("Stabilize", "Theme A", [_item()])],
        stats={"total_items": 1, "mean_roi": 1.5},
    ))

    # 4. Item with fan_in only (measured + payoff + why from rationale).
    cases.append(Roadmap(
        objective="obj", project_root="/p",
        phases=[RoadmapPhase("Secure", "Theme B", [
            _item(fan_in=4, rationale="risky path", phase="Secure")])],
        stats={"total_items": 1, "mean_roi": 1.5},
    ))

    # 5. Item with loc only (measured, no payoff, why from source_facts).
    cases.append(Roadmap(
        objective="", project_root="/p",
        phases=[RoadmapPhase("Refine", "Theme C", [
            _item(loc=120, source_facts=["doc-drift: stale"], phase="Refine")])],
        stats={"total_items": 1, "mean_roi": 1.5},
    ))

    # 6. Item with both fan_in and loc, rationale present (full measured suffix).
    cases.append(Roadmap(
        objective="o", project_root="/p",
        phases=[RoadmapPhase("Evolve", "Theme D", [
            _item(fan_in=7, loc=900, rationale="big hub", phase="Evolve")])],
        stats={"total_items": 1, "mean_roi": 2.0},
    ))

    # 7. Item with neither why nor payoff (empty rationale, no facts, no fan_in).
    cases.append(Roadmap(
        objective="", project_root="/p",
        phases=[RoadmapPhase("Stabilize", "Theme E", [
            _item(rationale="", source_facts=[])])],
        stats={"total_items": 1, "mean_roi": 1.0},
    ))

    # 8. fan_in but blank why -> payoff only (why line still rendered).
    cases.append(Roadmap(
        objective="", project_root="/p",
        phases=[RoadmapPhase("Secure", "Theme F", [
            _item(fan_in=2, rationale="   ", source_facts=[], phase="Secure")])],
        stats={"total_items": 1, "mean_roi": 1.0},
    ))

    # 9. Quick wins present + multiple phases + multiple items each.
    cases.append(Roadmap(
        objective="multi", project_root="/big",
        phases=[
            RoadmapPhase("Stabilize", "ST", [
                _item(branch_path="x.0", fan_in=3, loc=50, rationale="r0"),
                _item(branch_path="x.1", phase="Stabilize", source_facts=["fragile: x"]),
            ]),
            RoadmapPhase("Evolve", "EV", [
                _item(branch_path="x.2", phase="Evolve", loc=10, rationale="r2"),
            ]),
        ],
        quick_wins=[
            _item(branch_path="x.0", title="QW one", roi=3.0),
            _item(branch_path="x.2", title="QW two", roi=2.5),
        ],
        stats={"total_items": 3, "mean_roi": 1.8},
    ))

    # 10. Quick wins present but only one phase with one item.
    cases.append(Roadmap(
        objective="", project_root="/q",
        phases=[RoadmapPhase("Refine", "RF", [_item(branch_path="x.9", roi=4.0)])],
        quick_wins=[_item(branch_path="x.9", title="QW", roi=4.0)],
        stats={"total_items": 1, "mean_roi": 4.0},
    ))

    # 11. Stats missing keys entirely (defaults exercised).
    cases.append(Roadmap(
        objective="default-stats", project_root="/d",
        phases=[RoadmapPhase("Evolve", "EV", [_item(phase="Evolve")])],
        stats={},
    ))

    return cases


@pytest.mark.parametrize("roadmap", _roadmaps())
def test_render_byte_identical(roadmap: Roadmap) -> None:
    assert render_roadmap_markdown(roadmap) == _ORIG.render_roadmap_markdown(roadmap)


def test_at_least_one_of_each_branch_covered() -> None:
    # Sanity: ensure the corpus actually triggers the rendered sub-blocks.
    outs = [render_roadmap_markdown(r) for r in _roadmaps()]
    joined = "\n".join(outs)
    assert "Best first move" in joined
    assert "Quick wins" in joined
    assert "imported by" in joined
    assert "LOC" in joined
    assert "↳ why:" in joined
    assert "module(s) that depend on it" in joined
    # An empty roadmap renders only the header.
    assert outs[0] == "# Engineering Roadmap for `/repo`\n\n0 ideas sequenced · mean ROI 0\n"
