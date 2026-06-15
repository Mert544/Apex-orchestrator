from __future__ import annotations

from pathlib import Path

from app.engine.idea_permutation import IdeaPermutationEngine
from app.models.idea import IdeaNode
from app.reporting.idea_html import html_from_ideas, idea_tree_html

_CFG = {"max_total_ideas": 25, "max_idea_depth": 2, "breadth": 3}


def _project(tmp: Path) -> Path:
    """Mirror the synthetic project the permutation-engine tests build on."""
    (tmp / "app").mkdir()
    (tmp / "app" / "main.py").write_text("def main():\n    return 1\n")
    (tmp / "app" / "api.py").write_text(
        "import app.main\n\ndef handler():\n    return app.main.main()\n"
    )
    return tmp


def test_stats_chips_appear_for_a_populated_tree(tmp_path: Path):
    _project(tmp_path)
    report = IdeaPermutationEngine(_CFG, tmp_path).run()
    assert report.ideas, "engine should produce ideas for the synthetic project"
    doc = html_from_ideas(report.ideas)

    assert '<ul class="stats">' in doc
    assert "tied to concrete code facts" in doc
    assert "applied</li>" in doc  # the lens-diversity chip


def test_grounding_ratio_is_computed_locally_and_correct():
    # Two of three ideas carry source_facts -> 66% (floor), 2/3.
    grounded_a = IdeaNode(
        id="a", title="A", branch_path="x0", operator="cover",
        source_facts=["untested: app/a.py"],
    )
    grounded_b = IdeaNode(
        id="b", title="B", branch_path="x1", operator="secure",
        source_facts=["sensitive-path: app/b.py"],
    )
    bare = IdeaNode(id="c", title="C", branch_path="x2", operator="cover")
    doc = html_from_ideas([grounded_a, grounded_b, bare])

    assert "<strong>66%</strong> of ideas tied to concrete code facts (2/3)" in doc
    # Two distinct operators (cover, secure) -> 2 distinct lenses.
    assert "<strong>2</strong> distinct lenses applied" in doc


def test_single_lens_uses_singular_wording():
    nodes = [
        IdeaNode(id="a", title="A", branch_path="x0", operator="cover"),
        IdeaNode(id="b", title="B", branch_path="x1", operator="cover"),
    ]
    doc = html_from_ideas(nodes)
    assert "<strong>1</strong> distinct lens applied" in doc
    # No grounding anywhere -> 0%.
    assert "<strong>0%</strong> of ideas tied to concrete code facts (0/2)" in doc


def test_stats_values_are_escaped_and_no_injection():
    # A malicious operator name must never reach the page unescaped; the lens
    # count is an integer, so the operator string itself never renders, but we
    # assert the page stays clean of raw markup from any field feeding the chips.
    nasty = IdeaNode(
        id="r",
        title="<script>x</script>",
        branch_path="x0",
        operator="<script>evil</script>",
        source_facts=["<b>fact</b>"],
    )
    doc = html_from_ideas([nasty])
    assert "<script>" not in doc
    assert '<ul class="stats">' in doc
    # 1/1 grounded -> 100%.
    assert "<strong>100%</strong> of ideas tied to concrete code facts (1/1)" in doc


def test_empty_tree_omits_stats():
    doc = html_from_ideas([])
    assert '<ul class="stats">' not in doc
    assert "tied to concrete code facts" not in doc
    assert "idea tree is empty" in doc


def test_stats_are_deterministic(tmp_path: Path):
    _project(tmp_path)
    first = idea_tree_html(tmp_path, **_CFG)
    second = idea_tree_html(tmp_path, **_CFG)
    assert first == second
    assert '<ul class="stats">' in first
