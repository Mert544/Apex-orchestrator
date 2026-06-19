"""The CLI->engine->seeder forwarding of the opt-in discovery-seeding switch.

The seeder grew an opt-in ``seed_discoveries`` that appends fused cross-engine
discovery leads as recommend-only roots (proved at the seeder level in
``test_discovery_seeding_eyml``). This pins the LAST mile: ``IdeaPermutationEngine``
reads ``seed_discoveries`` from its config and forwards it to ``seed(...)``, so the
``--include-discoveries`` flag actually takes effect at runtime — and the default
(off) leaves the produced idea tree byte-identical.

Deterministic: fixed tmp tree, generous budget, no time/random.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.idea_permutation import IdeaPermutationEngine


def _project(tmp_path: Path) -> Path:
    # Eight near-identical modules + one structural outlier so the anomaly engine
    # (via discovery_synthesis) produces at least one lead.
    for i in range(8):
        (tmp_path / f"m{i}.py").write_text("def f():\n    return None\n", encoding="utf-8")
    (tmp_path / "odd.py").write_text(
        "import os\nimport sys\nclass Big:\n"
        + "".join(f"    def m{j}(self):\n        return {j}\n" for j in range(8)),
        encoding="utf-8")
    return tmp_path


def _discovery_subjects(root: Path, *, on: bool) -> list[str]:
    engine = IdeaPermutationEngine(
        project_root=str(root),
        config={"seed_discoveries": on, "max_total_ideas": 120, "min_relevance": 0.0})
    report = engine.run()
    return sorted({n.subject for n in report.ideas if "::discovery-" in n.subject})


def test_default_off_produces_no_discovery_roots(tmp_path: Path):
    assert _discovery_subjects(_project(tmp_path), on=False) == []


def test_default_off_idea_tree_is_byte_identical(tmp_path: Path):
    proj = _project(tmp_path)
    a = IdeaPermutationEngine(project_root=str(proj),
                              config={"max_total_ideas": 120}).run().model_dump()
    b = IdeaPermutationEngine(project_root=str(proj),
                              config={"seed_discoveries": False,
                                      "max_total_ideas": 120}).run().model_dump()
    assert a == b


def test_flag_on_surfaces_recommend_only_discovery_roots(tmp_path: Path):
    proj = _project(tmp_path)
    subjects = _discovery_subjects(proj, on=True)
    assert subjects  # at least one discovery lead reached the tree
    assert all("::discovery-" in s for s in subjects)
    # The discovery roots are recommend-only (not executable transforms).
    report = IdeaPermutationEngine(
        project_root=str(proj),
        config={"seed_discoveries": True, "max_total_ideas": 120}).run()
    from app.engine.idea_action_bridge import IdeaActionBridge
    bridge = IdeaActionBridge()
    for node in report.ideas:
        if "::discovery-" in node.subject:
            step = bridge.plan_idea(node)
            assert step.executable is False, node.subject
