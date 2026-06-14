from __future__ import annotations

import re
from pathlib import Path

from app.engine.idea_permutation import IdeaPermutationEngine
from app.models.idea import IdeaNode
from app.reporting.idea_html import (
    html_from_ideas,
    idea_tree_html,
    write_idea_html,
)


def _project(tmp: Path) -> Path:
    """Mirror the synthetic project the permutation-engine tests build on."""
    (tmp / "app").mkdir()
    (tmp / "app" / "main.py").write_text("def main():\n    return 1\n")
    (tmp / "app" / "api.py").write_text(
        "import app.main\n\ndef handler():\n    return app.main.main()\n"
    )
    return tmp


_CFG = {"max_total_ideas": 25, "max_idea_depth": 2, "breadth": 3}


def _assert_self_contained(doc: str) -> None:
    """The page is a single, offline, self-contained HTML document."""
    assert doc.startswith("<!DOCTYPE html>")
    assert "</html>" in doc
    # Inlined CSS, no external assets and no network references of any kind.
    assert "<style>" in doc
    assert "http://" not in doc
    assert "https://" not in doc
    assert "<link" not in doc
    assert "<script" not in doc
    assert "src=" not in doc
    assert "@import" not in doc


def test_idea_tree_html_is_self_contained(tmp_path: Path):
    _project(tmp_path)
    doc = idea_tree_html(tmp_path, **_CFG)
    _assert_self_contained(doc)
    # A real run produces at least one collapsible node.
    assert "<details" in doc and "<summary>" in doc


def test_every_idea_title_appears_escaped(tmp_path: Path):
    _project(tmp_path)
    report = IdeaPermutationEngine(_CFG, tmp_path).run()
    assert report.ideas, "engine should produce ideas for the synthetic project"
    doc = html_from_ideas(report.ideas)

    import html as _html

    for idea in report.ideas:
        assert _html.escape(idea.title, quote=True) in doc


def test_parent_child_nesting_is_present(tmp_path: Path):
    _project(tmp_path)
    report = IdeaPermutationEngine(_CFG, tmp_path).run()
    parent = next(
        i for i in report.ideas if any(c.parent_id == i.id for c in report.ideas)
    )
    child = next(i for i in report.ideas if i.parent_id == parent.id)

    doc = html_from_ideas(report.ideas)
    import html as _html

    p_title = _html.escape(parent.title, quote=True)
    c_title = _html.escape(child.title, quote=True)
    # The parent renders as a <details> whose <summary> carries its title, and
    # the child appears nested *after* the parent's summary, before that
    # <details> closes — i.e. inside the parent block.
    p_summary = f"<summary>{_label_fragment(parent)}</summary>"
    assert p_summary in doc
    block_start = doc.index(p_summary)
    block_end = doc.index("</details>", block_start)
    assert c_title in doc[block_start:block_end]
    assert p_title in doc  # parent title present too


def _label_fragment(idea: IdeaNode) -> str:
    import html as _html

    kind = idea.kind or "permutation"
    frag = (
        f'<span class="kind kind-{kind}">{kind}</span>'
        f'<span class="title">{_html.escape(idea.title, quote=True)}</span>'
    )
    if idea.value:
        frag += f'<span class="score">value {idea.value:.2f}</span>'
    return frag


def test_idea_tree_html_is_deterministic(tmp_path: Path):
    _project(tmp_path)
    first = idea_tree_html(tmp_path, **_CFG)
    second = idea_tree_html(tmp_path, **_CFG)
    assert first == second


def test_write_idea_html_byte_identical(tmp_path: Path):
    _project(tmp_path)
    out1 = tmp_path / "out" / "one.html"
    out2 = tmp_path / "two.html"
    write_idea_html(tmp_path, out1, **_CFG)
    write_idea_html(tmp_path, out2, **_CFG)
    assert out1.read_bytes() == out2.read_bytes()
    _assert_self_contained(out1.read_text())


def test_generated_on_is_injectable_and_default_empty(tmp_path: Path):
    _project(tmp_path)
    # Default: no timestamp line, so two builds are byte-identical (covered
    # above). When injected, it appears escaped and does not break determinism.
    bare = idea_tree_html(tmp_path, **_CFG)
    assert "generated on" not in bare

    stamped = idea_tree_html(tmp_path, generated_on="<run 1>", **_CFG)
    assert "generated on &lt;run 1&gt;" in stamped
    # Same injected value -> identical output (still no time/random leak).
    assert stamped == idea_tree_html(tmp_path, generated_on="<run 1>", **_CFG)


def test_empty_tree_is_a_valid_minimal_page():
    doc = html_from_ideas([])
    _assert_self_contained(doc)
    assert "idea tree is empty" in doc
    # No tree structure for an empty set.
    assert "<details" not in doc


def test_idea_tree_html_empty_project(tmp_path: Path):
    # A project with no analysable source yields the empty-tree page (still a
    # valid, self-contained document).
    doc = idea_tree_html(tmp_path, **_CFG)
    _assert_self_contained(doc)


def test_html_text_is_escaped_against_injection():
    # Titles/facts containing HTML metacharacters must be escaped, never raw.
    nasty = IdeaNode(
        id="r",
        title="<script>alert('x')</script> & \"go\"",
        branch_path="x0",
        depth=0,
        source_facts=["fact: <b>bold</b> & risky"],
        value=0.5,
    )
    doc = html_from_ideas([nasty])
    _assert_self_contained(doc)
    # The raw script tag from the title never appears unescaped in the body.
    assert "<script>alert" not in doc
    assert "&lt;script&gt;alert" in doc
    assert "&amp;" in doc and "&quot;" in doc
    assert "&lt;b&gt;bold&lt;/b&gt;" in doc  # the fact is escaped too


def test_synthetic_tree_nests_children_under_parents():
    # A tiny explicit tree: root -> a, b ; a -> a1. Emit order is scrambled to
    # prove nesting is independent of it (mirrors the canvas exporter's test).
    root = IdeaNode(id="r", title="Root", branch_path="x0", depth=0, value=0.9)
    a = IdeaNode(id="r-0", title="A", parent_id="r", branch_path="x0.0", depth=1)
    b = IdeaNode(id="r-1", title="B", parent_id="r", branch_path="x0.1", depth=1)
    a1 = IdeaNode(
        id="r-0-0", title="A1", parent_id="r-0", branch_path="x0.0.0", depth=2
    )
    doc = html_from_ideas([a1, b, root, a])

    for title in ("Root", "A", "B", "A1"):
        assert f'<span class="title">{title}</span>' in doc

    # Root's <details> block contains A, B and (nested deeper) A1.
    root_summary = (
        '<summary><span class="kind kind-permutation">permutation</span>'
        '<span class="title">Root</span>'
        '<span class="score">value 0.90</span></summary>'
    )
    assert root_summary in doc
    start = doc.index(root_summary)
    tail = doc[start:]
    # A1 nests under A, so A's title precedes A1's; all are inside root's block.
    assert (
        tail.index('"title">A<') < tail.index('"title">A1<')
    )
    assert '"title">B<' in tail
    # Determinism: rebuilding from a different emit order is identical.
    assert doc == html_from_ideas([root, a, b, a1])


def test_parentless_synthesis_renders_as_its_own_root():
    # Synthesis/pair ideas carry no parent_id: they render as their own top-level
    # node (no incoming nesting), just like a real root.
    synth = IdeaNode(
        id="synth-0", title="Synth", kind="synthesis", branch_path="x.s0", value=0.4
    )
    doc = html_from_ideas([synth])
    _assert_self_contained(doc)
    assert '<span class="kind kind-synthesis">synthesis</span>' in doc
    assert '<span class="title">Synth</span>' in doc
    # No children -> a flat leaf, not a <details>.
    assert "<details" not in doc
    assert '<div class="leaf">' in doc


def test_grounding_facts_render_when_present():
    node = IdeaNode(
        id="r",
        title="Cover the auth module",
        branch_path="x0",
        depth=0,
        source_facts=["untested: app/auth.py (no tests)", "sensitive-path: app/auth.py"],
    )
    doc = html_from_ideas([node])
    assert '<div class="grounding">grounding:' in doc
    assert "untested: app/auth.py (no tests)" in doc
    # A node with no facts omits the grounding block entirely (the class still
    # lives in the stylesheet, but no grounding div is emitted in the body).
    bare = html_from_ideas([IdeaNode(id="b", title="Bare", branch_path="x1")])
    assert '<div class="grounding">' not in bare


def test_no_timestamp_or_volatile_token_by_default(tmp_path: Path):
    # Belt-and-braces determinism: the default document contains no date-like or
    # clock-like token that could vary between runs.
    _project(tmp_path)
    doc = idea_tree_html(tmp_path, **_CFG)
    assert not re.search(r"\d{4}-\d{2}-\d{2}", doc)  # no ISO date
    assert not re.search(r"\d{2}:\d{2}:\d{2}", doc)  # no clock time
