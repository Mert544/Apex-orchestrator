"""Render Apex's Idea Permutation tree as a standalone, self-contained HTML file.

A companion to the JSONCanvas idea exporters: this module turns the Idea
Permutation Engine's tree of development ideas into a single, shareable HTML
document — a collapsible tree view, all CSS inlined, no external assets and no
network. Open it in any browser to explore a project's idea tree;
``<details>/<summary>`` provides native, JS-free collapsibility.

The public entry point is :func:`idea_tree_html`, which runs the engine
(``IdeaPermutationEngine(...).run(objective)``) and renders ``report.ideas`` as
nested ``<details>`` blocks — each idea a node carrying its kind, title, and (if
present) its score and grounding facts; children nested under their parent.

It reuses the same tree traversal the JSONCanvas exporter uses — a stable
``_node_id`` per idea, the same sibling sort key, and the same "parentless
synthesis/pair ideas render as their own roots" rule — so the canvas and the
HTML stay structurally consistent.

Everything is deterministic and stdlib-only: siblings are sorted by a stable
key, all text is escaped via :func:`html.escape`, and the document carries no
timestamp by default — so the same project yields a byte-identical page. No LLM,
no network, no time, no randomness. Read-only: it changes no project files.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from app.engine.idea_permutation import IdeaPermutationEngine
from app.models.idea import IdeaNode

# Inlined stylesheet: no external <link>, no @import, no url(...) — the page is
# fully self-contained and renders identically offline. Kept compact and static
# so the document stays byte-identical across runs.
_CSS = """\
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica,
    Arial, sans-serif;
  margin: 0; padding: 2rem; line-height: 1.45; color: #1b1b1f;
  background: #fafafa;
}
h1 { font-size: 1.4rem; margin: 0 0 0.25rem; }
.meta { color: #666; font-size: 0.85rem; margin: 0 0 1.5rem; }
.tree { max-width: 60rem; }
details { margin: 0.2rem 0; }
details > details, .leaf { margin-left: 1.4rem; }
summary, .leaf {
  padding: 0.35rem 0.55rem; border-radius: 6px;
  border: 1px solid #e3e3e8; background: #fff; list-style-position: outside;
}
summary { cursor: pointer; }
summary:hover, .leaf:hover { border-color: #c7c7d0; }
.kind {
  display: inline-block; font-size: 0.7rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.04em; padding: 0.05rem 0.4rem;
  border-radius: 999px; margin-right: 0.5rem; vertical-align: middle;
  background: #ebedf2; color: #444;
}
.kind-permutation { background: #e0f2fe; color: #075985; }
.kind-synthesis  { background: #dcfce7; color: #166534; }
.kind-pair       { background: #ede9fe; color: #5b21b6; }
.kind-facet      { background: #ffedd5; color: #9a3412; }
.title { font-weight: 600; }
.score { color: #555; font-size: 0.85rem; margin-left: 0.5rem; }
.grounding {
  margin: 0.25rem 0 0.4rem 0.4rem; padding: 0.2rem 0 0.2rem 0.7rem;
  border-left: 3px solid #e3e3e8; color: #555; font-size: 0.82rem;
}
.grounding ul { margin: 0.15rem 0; padding-left: 1.1rem; }
.empty { color: #666; font-style: italic; }
.stats {
  display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0 0 1.5rem;
  padding: 0; list-style: none; max-width: 60rem;
}
.stats li {
  font-size: 0.82rem; color: #444; background: #ebedf2;
  border: 1px solid #e3e3e8; border-radius: 999px; padding: 0.2rem 0.6rem;
}
.stats strong { color: #1b1b1f; }
"""


def _esc(text: object) -> str:
    """Escape arbitrary text for safe HTML embedding (quotes included)."""
    return html.escape(str(text), quote=True)


def _node_id(idea: IdeaNode) -> str:
    """Stable, deterministic node id for an idea (mirrors the canvas exporter).

    The engine's idea ids are unique per run and stable across runs (derived
    from seeding facts and operator indices); ``branch_path`` then ``title`` are
    stable tiebreakers for the rare case an id is missing.
    """
    return idea.id or idea.branch_path or idea.title


def _sort_key(idea: IdeaNode) -> tuple[str, str, str]:
    """Stable sibling ordering key: id, then branch_path, then title.

    Independent of value/score (which would couple ordering to the scorer); a
    pure structural key keeps the page reproducible and insensitive to the order
    ideas happen to be emitted in.
    """
    return (_node_id(idea), idea.branch_path, idea.title)


def _kind(idea: IdeaNode) -> str:
    """The idea's kind, defaulting to ``permutation`` (mirrors the exporter)."""
    return idea.kind or "permutation"


def _children_map(ideas: list[IdeaNode]) -> dict[str | None, list[IdeaNode]]:
    """Group ideas under their parent, sorted by the stable sibling key.

    Same rule the canvas exporter uses: an idea is a child of its parent only
    when that parent is present in the tree; otherwise (parentless synthesis/pair
    ideas, or an orphaned parent ref) it renders as its own root under ``None``.
    """
    by_id = {_node_id(idea): idea for idea in ideas}
    children: dict[str | None, list[IdeaNode]] = {}
    for idea in ideas:
        parent = idea.parent_id if (idea.parent_id in by_id) else None
        children.setdefault(parent, []).append(idea)
    for bucket in children.values():
        bucket.sort(key=_sort_key)
    return children


def _grounding_html(idea: IdeaNode, indent: str) -> str:
    """Render an idea's traceable grounding facts as an escaped bullet list.

    Empty when the idea carries no ``source_facts`` (e.g. a bare synthetic node),
    so the block is omitted rather than rendering an empty container.
    """
    facts = list(idea.source_facts)
    if not facts:
        return ""
    items = "".join(f"{indent}    <li>{_esc(fact)}</li>\n" for fact in facts)
    return (
        f'{indent}  <div class="grounding">grounding:\n'
        f"{indent}    <ul>\n{items}{indent}    </ul>\n"
        f"{indent}  </div>\n"
    )


def _stats_html(ideas: list[IdeaNode]) -> str:
    """Render small header telemetry chips, computed purely from ``ideas``.

    Two reader-facing signals, derived locally (no engine import, no remote
    resource) so the renderer stays pure and self-contained:

    * **grounding ratio** — the share of ideas tied to concrete code facts
      (non-empty ``source_facts``), so a reader can gauge how much of the tree
      is grounded versus synthetic.
    * **lens diversity** — the number of distinct development lenses
      (``operator``) applied across the tree.

    Returns the empty string for an empty tree, so an empty page renders exactly
    as before (the chips are gated on availability). Deterministic: integer
    counts and a floor-rounded percentage, no time/random.
    """
    if not ideas:
        return ""
    total = len(ideas)
    grounded = sum(1 for idea in ideas if idea.source_facts)
    lenses = {idea.operator for idea in ideas if idea.operator}
    pct = grounded * 100 // total  # floor; deterministic, no float formatting
    grounded_chip = (
        f"<li><strong>{pct}%</strong> of ideas tied to concrete code facts "
        f"({grounded}/{total})</li>"
    )
    lens_chip = (
        f"<li><strong>{len(lenses)}</strong> distinct "
        f"{'lens' if len(lenses) == 1 else 'lenses'} applied</li>"
    )
    return f'  <ul class="stats">\n    {grounded_chip}\n    {lens_chip}\n  </ul>\n'


def _label_html(idea: IdeaNode) -> str:
    """The inline label for a node: kind tag, escaped title, optional score."""
    kind = _kind(idea)
    parts = [
        f'<span class="kind kind-{_esc(kind)}">{_esc(kind)}</span>',
        f'<span class="title">{_esc(idea.title)}</span>',
    ]
    # Score is shown only when the engine actually scored the idea (value > 0);
    # a bare synthetic node left at value 0.0 carries no score badge.
    if idea.value:
        parts.append(f'<span class="score">value {idea.value:.2f}</span>')
    return "".join(parts)


def _render_node(
    idea: IdeaNode,
    children: dict[str | None, list[IdeaNode]],
    depth: int,
    seen: set[str],
) -> str:
    """Render one idea (and its subtree) as nested ``<details>``/leaf markup.

    A node with children becomes a collapsible ``<details>`` (open at the top
    levels so the shape is visible immediately, collapsed deeper); a childless
    node becomes a flat ``.leaf`` ``<div>``. ``seen`` guards against any
    accidental cycle in the parent links so rendering always terminates.
    """
    key = _node_id(idea)
    if key in seen:  # defensive: never recurse into an already-rendered node
        return ""
    seen.add(key)

    indent = "  " * (depth + 1)
    kids = children.get(key, [])
    label = _label_html(idea)
    grounding = _grounding_html(idea, indent)

    if not kids:
        return f'{indent}<div class="leaf">{label}</div>\n{grounding}'

    # Open the first two levels by default so the tree's shape is visible; keep
    # deeper subtrees collapsed to stay navigable. Deterministic (depth-driven).
    open_attr = " open" if depth < 2 else ""
    inner = "".join(
        _render_node(child, children, depth + 1, seen) for child in kids
    )
    return (
        f"{indent}<details{open_attr}>\n"
        f"{indent}  <summary>{label}</summary>\n"
        f"{grounding}{inner}"
        f"{indent}</details>\n"
    )


def html_from_ideas(
    ideas: list[IdeaNode],
    *,
    title: str = "Apex Idea Tree",
    generated_on: str = "",
) -> str:
    """Render an explicit list of idea nodes as a self-contained HTML document.

    Split out from :func:`idea_tree_html` so the rendering is testable on a
    synthetic tree without running the engine. The traversal mirrors the canvas
    exporter: siblings are sorted by the stable key and parentless
    synthesis/pair ideas render as their own roots.

    ``generated_on`` is injectable and defaults to the empty string, so two runs
    are byte-identical (no timestamp leaks into the output). An empty ``ideas``
    list yields a valid minimal page stating the tree is empty.
    """
    safe_title = _esc(title)
    meta = (
        f'  <p class="meta">generated on {_esc(generated_on)}</p>\n'
        if generated_on
        else ""
    )

    stats = _stats_html(ideas)

    if not ideas:
        body = '  <p class="empty">No ideas — the idea tree is empty.</p>\n'
    else:
        children = _children_map(ideas)
        seen: set[str] = set()
        roots = sorted(children.get(None, []), key=_sort_key)
        rendered = "".join(
            _render_node(root, children, 0, seen) for root in roots
        )
        # Any idea unreachable from a root (e.g. an orphaned parent ref) still
        # gets rendered at the top level, so no idea is silently dropped.
        leftover = "".join(
            _render_node(idea, children, 0, seen)
            for idea in sorted(ideas, key=_sort_key)
            if _node_id(idea) not in seen
        )
        body = f'  <div class="tree">\n{rendered}{leftover}  </div>\n'

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{safe_title}</title>\n"
        f"  <style>\n{_CSS}  </style>\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>{safe_title}</h1>\n"
        f"{meta}"
        f"{stats}"
        f"{body}"
        "</body>\n"
        "</html>\n"
    )


def idea_tree_html(
    project_root: str | Path,
    *,
    objective: str | None = None,
    generated_on: str = "",
    **engine_config: Any,
) -> str:
    """Build a self-contained HTML idea-tree document for ``project_root``.

    Runs :class:`IdeaPermutationEngine` on ``project_root`` (the same entry point
    the JSONCanvas exporter uses) and renders ``report.ideas`` as a collapsible
    tree. ``engine_config`` is forwarded to the engine (e.g. ``max_total_ideas``,
    ``max_idea_depth``, ``breadth``, ``fractal_facets``); defaults reproduce a
    standard ideate run. ``objective`` steers the run when given.

    ``generated_on`` is injectable and defaults to empty so two runs are
    byte-identical. If the idea tree is empty, a valid minimal page is returned.
    """
    report = IdeaPermutationEngine(engine_config or None, project_root).run(
        objective
    )
    return html_from_ideas(report.ideas, generated_on=generated_on)


def write_idea_html(
    project_root: str | Path,
    path: str | Path,
    *,
    objective: str | None = None,
    generated_on: str = "",
    **engine_config: Any,
) -> None:
    """Write the self-contained idea-tree HTML for ``project_root`` to ``path``.

    A thin file-writing wrapper around :func:`idea_tree_html`. The output is
    deterministic (no timestamp by default), so writing the same project twice
    yields byte-identical files. Read-only with respect to the project: it only
    touches ``path`` (and creates its parent directory if needed).
    """
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        idea_tree_html(
            project_root,
            objective=objective,
            generated_on=generated_on,
            **engine_config,
        ),
        encoding="utf-8",
    )
