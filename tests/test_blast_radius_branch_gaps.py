"""Branch-gap coverage for app.engine.blast_radius.

Targets the two partial branches left by the existing edge suites:

  * ``_compute_cohesion``: a changed module whose import target is NOT in the
    changed set — the False arm of ``if target in changed_set`` (the import edge
    is ignored, leaving the changed modules disconnected).
  * ``render_blast_radius_markdown``: a non-empty BlastRadius whose ``cohesion``
    is ``None`` — the "## Scope cohesion" section is skipped.

Deterministic and hermetic (no tmp_path needed; no network; structure-only
assertions). Style mirrors tests/test_blast_radius_edges.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.engine.blast_radius import (
    BlastRadius,
    Cohesion,
    _compute_cohesion,
    render_blast_radius_markdown,
)


@dataclass
class _Node:
    """Minimal stand-in for a DependencyNode: only ``.imports`` is read here."""

    imports: set[str] = field(default_factory=set)


def test_cohesion_import_target_outside_changed_set_is_ignored():
    # Two changed modules in DIFFERENT packages (not same-package), present in the
    # graph. The first imports a module that is NOT among the changed set, so the
    # `if target in changed_set` arm is False: the edge is dropped, the changed
    # subgraph stays disconnected, and the verdict falls through to the prefix
    # rule. With a shared 'app' prefix both modules match -> tight 1.0.
    changed = ["app/engine/a.py", "app/tools/b.py"]
    graph = {
        "app/engine/a.py": _Node(imports={"app/other/external.py"}),
        "app/tools/b.py": _Node(imports=set()),
    }
    c = _compute_cohesion(changed, graph)
    assert isinstance(c, Cohesion)
    # Not connected by the (ignored) external edge; resolved via common prefix.
    assert "connected by direct imports" not in c.reason
    assert c.score == 1.0 and c.label == "tight"
    assert "common prefix 'app'" in c.reason


def test_cohesion_external_import_with_no_common_prefix_is_scattered():
    # Same False-arm path, but now no shared package prefix either: the external
    # import edge is ignored and the modules share nothing -> scattered 0.0.
    changed = ["pkga/a.py", "pkgb/b.py"]
    graph = {
        "pkga/a.py": _Node(imports={"vendor/dep.py"}),
        "pkgb/b.py": _Node(imports=set()),
    }
    c = _compute_cohesion(changed, graph)
    assert c.score == 0.0 and c.label == "scattered"
    assert "scope creep" in c.reason


def test_render_with_changed_but_cohesion_none_skips_cohesion_section():
    # A populated BlastRadius whose cohesion is None: the counts table and the
    # four sections render, but the "## Scope cohesion" block is omitted.
    br = BlastRadius(
        changed=["app/x.py"],
        direct_dependents=["app/y.py"],
        transitive_dependents=[],
        covering_tests=[],
        cohesion=None,
    )
    md = render_blast_radius_markdown(br)
    assert "Scope cohesion" not in md
    assert "| Changed modules | 1 |" in md
    assert "`app/y.py`" in md
    # Renderer still terminates the document with a single trailing newline.
    assert md.endswith("\n")
