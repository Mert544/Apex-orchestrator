"""Focused characterization for ``IdeaPermutationEngine._expand_facets``.

The byte-identical proof for the facet-zoom refactor: this test loads the
*original* (pre-refactor) ``idea_permutation`` module from ``git show HEAD``
into a throwaway module, then runs both the original and the current engine
over a wide matrix of facet configurations and projects, asserting that every
emitted idea (and the rendered markdown) is identical. ``_expand_facets`` is
the only diverging code, so any change in its output would surface here.

Determinism (no time/random in scoring) makes the comparison stable, and it
is offline/stdlib-only.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.engine.idea_permutation import IdeaPermutationEngine, render_markdown

_REPO = Path(__file__).resolve().parents[1]
_MODULE_REL = "app/engine/idea_permutation.py"


def _load_baseline(tmp_path: Path):
    """Import the HEAD version of idea_permutation as an independent module."""
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{_MODULE_REL}"], cwd=_REPO, text=True
    )
    path = tmp_path / "_baseline_idea_permutation.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("_baseline_idea_permutation", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_baseline_idea_permutation"] = mod
    spec.loader.exec_module(mod)
    return mod


def _build_project(root: Path) -> None:
    """A fixed project that exercises roots, deep permutations, synthesis and
    the fractal facet zoom."""
    (root / "app").mkdir()
    (root / "app" / "auth.py").write_text(
        "import os\n"
        "PASSWORD = 'hunter2'\n"
        "def login(pw):\n"
        "    return os.system(pw)\n"
        "def helper(x):\n"
        "    if x:\n"
        "        if x > 1:\n"
        "            return eval(str(x))\n"
        "    return None\n"
    )
    (root / "app" / "api.py").write_text(
        "import app.auth\n"
        "def handler():\n"
        "    return app.auth.login('x')\n"
    )
    (root / "app" / "util.py").write_text("def util():\n    return 2\n")
    (root / "app" / "models.py").write_text(
        "def serialize(d):\n    return str(d)\n"
        "def parse(s):\n    return eval(s)\n"
    )


# A matrix that varies every facet knob _expand_facets reads:
# fractal_facets, facet_depth, facets_per_idea, adaptive_depth,
# adaptive_depth_bonus, adaptive_depth_threshold, plus budget/breadth.
_CONFIGS = [
    {"max_total_ideas": 60, "breadth": 4, "fractal_facets": True,
     "facets_per_idea": 2, "facet_depth": 2, "adaptive_depth": True},
    {"max_total_ideas": 80, "breadth": 5, "fractal_facets": True,
     "facets_per_idea": 3, "facet_depth": 3, "adaptive_depth": True,
     "adaptive_depth_bonus": 3, "adaptive_depth_threshold": 0.4},
    {"max_total_ideas": 45, "breadth": 3, "fractal_facets": True,
     "facets_per_idea": 1, "facet_depth": 1, "adaptive_depth": False},
    {"max_total_ideas": 100, "breadth": 4, "fractal_facets": True,
     "facets_per_idea": 2, "facet_depth": 4, "adaptive_depth": True,
     "adaptive_depth_bonus": 1, "adaptive_depth_threshold": 0.9},
    {"max_total_ideas": 30, "breadth": 6, "fractal_facets": True,
     "facets_per_idea": 4, "facet_depth": 2, "adaptive_depth": True,
     "adaptive_depth_threshold": 0.0},
    # Facets on but a tiny budget — the _stop()/synth-floor edge path.
    {"max_total_ideas": 12, "breadth": 3, "fractal_facets": True,
     "facets_per_idea": 2, "facet_depth": 3, "adaptive_depth": True},
    # Facets OFF: _expand_facets must still produce an identical (empty-facet)
    # report — characterizes the no-leaves / disabled branch.
    {"max_total_ideas": 50, "breadth": 4, "fractal_facets": False},
    # With an explicit objective, which reweights values feeding source sort.
    {"max_total_ideas": 70, "breadth": 4, "fractal_facets": True,
     "facets_per_idea": 3, "facet_depth": 2, "adaptive_depth": True,
     "min_relevance": 0.3},
]
_OBJECTIVES = [None, "harden authentication and improve security"]


def _facet_view(rep) -> str:
    """A stable digest-input of every facet idea (the _expand_facets output)."""
    d = rep.model_dump()
    facets = [n for n in d["ideas"] if n.get("kind") == "facet"]
    facets.sort(key=lambda n: n["id"])
    return json.dumps(
        {"faceted": d["stats"].get("faceted"), "facets": facets},
        sort_keys=True,
        default=str,
    )


@pytest.mark.parametrize("cfg", _CONFIGS)
@pytest.mark.parametrize("objective", _OBJECTIVES)
def test_expand_facets_byte_identical_to_head(tmp_path, cfg, objective):
    mod_dir = tmp_path / "mod"
    mod_dir.mkdir()
    base_mod = _load_baseline(mod_dir)
    proj_a = tmp_path / "a"
    proj_b = tmp_path / "b"
    proj_a.mkdir()
    proj_b.mkdir()
    _build_project(proj_a)
    _build_project(proj_b)

    rep_orig = base_mod.IdeaPermutationEngine(dict(cfg), proj_a).run(objective=objective)
    rep_new = IdeaPermutationEngine(dict(cfg), proj_b).run(objective=objective)

    # The facet ideas (the _expand_facets product) must match exactly.
    assert _facet_view(rep_new) == _facet_view(rep_orig)

    # And the whole report + rendered markdown, modulo the tmp project path.
    d_o = rep_orig.model_dump()
    d_n = rep_new.model_dump()
    d_o["project_root"] = d_n["project_root"] = "<root>"
    d_o["stats"].pop("metrics_error", None)
    d_n["stats"].pop("metrics_error", None)
    assert json.dumps(d_n, sort_keys=True, default=str) == json.dumps(
        d_o, sort_keys=True, default=str
    )
    md_o = base_mod.render_markdown(rep_orig).replace(str(proj_a), "<root>")
    md_n = render_markdown(rep_new).replace(str(proj_b), "<root>")
    assert md_n == md_o


def test_expand_facets_emits_facets_for_at_least_one_config(tmp_path):
    """Guard: the matrix actually exercises the facet-emission path (not a
    vacuous all-empty comparison)."""
    proj = tmp_path / "p"
    proj.mkdir()
    _build_project(proj)
    cfg = {"max_total_ideas": 80, "breadth": 5, "fractal_facets": True,
           "facets_per_idea": 3, "facet_depth": 3, "adaptive_depth": True}
    rep = IdeaPermutationEngine(cfg, proj).run()
    facets = [n for n in rep.model_dump()["ideas"] if n.get("kind") == "facet"]
    assert facets, "expected the facet matrix to produce facet ideas"
    assert rep.stats.get("faceted", 0) == len(facets)
