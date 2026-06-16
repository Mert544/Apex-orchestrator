"""Characterization tests pinning the refactors of two decomposed helpers:

- ``app.reporting.deadcode._collect_references`` (now built from pure
  ``_node_refs`` / ``_is_all_assign`` / ``_all_exports`` helpers)
- ``app.reporting.dashboard._nav_links`` (now built from pure gate predicates
  plus ``_middle_nav_links``)

Both refactors must be byte-identical to the pre-refactor behavior. These tests
encode the exact expected outputs over representative + edge-case inputs so any
future drift is caught.
"""

from __future__ import annotations

import ast
import itertools
from pathlib import Path
from types import SimpleNamespace

from app.reporting.dashboard import _nav_links
from app.reporting.dashboard_sections import RenderedSections, _esc
from app.reporting.deadcode import (
    _all_exports,
    _collect_references,
    _is_all_assign,
    _node_refs,
)


# --- _collect_references --------------------------------------------------

def _ref(src: str) -> tuple[set[str], set[str]]:
    return _collect_references(ast.parse(src))


def test_collect_references_empty_module():
    assert _ref("") == (set(), set())


def test_collect_references_mixed_node_kinds():
    src = (
        "import os\n"
        "import a.b.c as abc\n"
        "from pkg import one, two as t\n"
        "x = foo()\n"
        "obj.attr\n"
        "__all__ = ['exp1', 'exp2']\n"
    )
    refs, exports = _ref(src)
    # imports collapse to their bound top-level name; from-imports keep asname.
    assert {"os", "abc", "one", "t", "foo", "attr"} <= refs
    assert exports == {"exp1", "exp2"}


def test_collect_references_all_tuple_with_non_str_elements_ignored():
    refs, exports = _ref("__all__ = ('q', 'r', 3, bar)\n")
    # only string constants count as exports
    assert exports == {"q", "r"}
    # `bar` is a Load Name reference
    assert "bar" in refs


def test_collect_references_all_must_be_list_or_tuple():
    # __all__ bound to a non-literal does not produce exports.
    _refs, exports = _ref("__all__ = some_var\n")
    assert exports == set()


def test_collect_references_multitarget_all_assignment():
    refs, exports = _ref("a = b = __all__ = ['shared']\n")
    assert exports == {"shared"}
    assert "a" not in refs  # Store context names are not references


def test_node_refs_helper_isolated():
    # Each node kind in isolation.
    assert _node_refs(ast.parse("name", mode="eval").body) == {"name"}
    attr = ast.parse("o.field", mode="eval").body
    assert _node_refs(attr) == {"field"}
    # A Store-context Name references nothing.
    store = ast.parse("z = 1\n").body[0].targets[0]
    assert _node_refs(store) == set()
    # Non-referencing node.
    assert _node_refs(ast.parse("pass\n").body[0]) == set()


def test_is_all_assign_and_all_exports():
    assign = ast.parse("__all__ = ['x', 'y']\n").body[0]
    assert _is_all_assign(assign) is True
    assert _all_exports(assign) == {"x", "y"}
    not_all = ast.parse("other = ['x']\n").body[0]
    assert _is_all_assign(not_all) is False
    non_seq = ast.parse("__all__ = foo\n").body[0]
    assert _is_all_assign(non_seq) is False


# --- _nav_links -----------------------------------------------------------

def _expected_nav(project_root, git, debug, roadmap, shape, autonomy,
                  pareto, trajectory, learned, sections) -> str:
    """Independent re-implementation of the pre-refactor gating, inline."""
    links = [("overview", "Overview"), ("findings", "Findings"),
             ("architecture", "Architecture"), ("ideas", "Ideas")]
    if sections.quality_html:
        links.append(("quality", "Quality"))
    if shape is not None and getattr(shape, "total_ideas", 0):
        links.append(("shape", "Shape"))
    if roadmap is not None and getattr(roadmap, "phases", None):
        links.append(("roadmap", "Roadmap"))
    if pareto:
        links.append(("frontier", "Frontier"))
    if autonomy:
        links.append(("autonomy", "Autonomy"))
    if trajectory:
        links.append(("trajectory", "Trajectory"))
    if learned and (learned.get("most_reliable") or learned.get("least_reliable")):
        links.append(("learned", "Learned"))
    if sections.trackrecord_html:
        links.append(("trackrecord", "Track record"))
    if sections.outscope_html:
        links.append(("outscope", "Out of scope"))
    if (Path(project_root) / ".apex" / "dream-digest.md").exists():
        links.append(("dream", "Dream"))
    links += [("actions", "Actions"), ("reasoning", "Reasoning"), ("profile", "Profile")]
    if debug:
        links.append(("debug", "Debug"))
    if git:
        links.append(("repository", "Repo"))
    return "".join(f"<a href='#{i}'>{_esc(t)}</a>" for i, t in links)


def test_nav_links_default_minimal(tmp_path):
    sec = RenderedSections(quality_html="", trackrecord_html="", outscope_html="")
    got = _nav_links(str(tmp_path), {}, {}, None, None, None, [], [], None, sections=sec)
    exp = _expected_nav(str(tmp_path), {}, {}, None, None, None, [], [], None, sec)
    assert got == exp
    # No optional gates fired: only the fixed head + fixed tail.
    assert "quality" not in got and "shape" not in got and "dream" not in got


def test_nav_links_all_gates_on(tmp_path):
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "dream-digest.md").write_text("x")
    sec = RenderedSections(quality_html="<q>", trackrecord_html="<t>", outscope_html="<o>")
    args = (
        str(tmp_path), {"branch": "m"}, {"trace_count": 1},
        SimpleNamespace(phases=["p"]), SimpleNamespace(total_ideas=9),
        {"x": 1}, ["p"], [1], {"most_reliable": ["r"], "least_reliable": []},
    )
    got = _nav_links(*args, sections=sec)
    exp = _expected_nav(*args, sec)
    assert got == exp
    for anchor in ("quality", "shape", "roadmap", "frontier", "autonomy",
                   "trajectory", "learned", "trackrecord", "outscope",
                   "dream", "debug", "repository"):
        assert f"#{anchor}" in got


def test_nav_links_edge_empty_collections_do_not_gate(tmp_path):
    # Empty phases / total_ideas==0 / empty learned dict must NOT add a link.
    sec = RenderedSections(quality_html="", trackrecord_html="", outscope_html="")
    args = (
        str(tmp_path), {}, {}, SimpleNamespace(phases=[]),
        SimpleNamespace(total_ideas=0), None, [], [],
        {"most_reliable": [], "least_reliable": []},
    )
    got = _nav_links(*args, sections=sec)
    exp = _expected_nav(*args, sec)
    assert got == exp
    assert "shape" not in got and "roadmap" not in got and "learned" not in got


def test_nav_links_matches_baseline_over_gate_matrix(tmp_path):
    """Exhaustive-ish: every gate combination yields the baseline string."""
    no_dream = tmp_path / "a"
    no_dream.mkdir()
    dream = tmp_path / "b"
    (dream / ".apex").mkdir(parents=True)
    (dream / ".apex" / "dream-digest.md").write_text("x")
    roots = [str(no_dream), str(dream)]

    learneds = [None, {}, {"most_reliable": ["r"], "least_reliable": []},
                {"most_reliable": [], "least_reliable": ["u"]},
                {"most_reliable": [], "least_reliable": []}]
    shapes = [None, SimpleNamespace(total_ideas=0), SimpleNamespace(total_ideas=3)]
    roadmaps = [None, SimpleNamespace(phases=[]), SimpleNamespace(phases=["p"])]

    n = 0
    for pr, git, debug, roadmap, shape, learned in itertools.product(
        roots, [{}, {"b": 1}], [{}, {"t": 1}], roadmaps, shapes, learneds
    ):
        for pareto, traj, autonomy in itertools.product([[], ["p"]], [[], [1]], [None, {"x": 1}]):
            for q, tr, oo in itertools.product(["", "<q>"], ["", "<t>"], ["", "<o>"]):
                sec = RenderedSections(quality_html=q, trackrecord_html=tr, outscope_html=oo)
                args = (pr, git, debug, roadmap, shape, autonomy, pareto, traj, learned)
                assert _nav_links(*args, sections=sec) == _expected_nav(*args, sec)
                n += 1
    assert n > 1000
