"""Characterization snapshot for the idea-permutation engine.

Pins the *exact* output of ``IdeaPermutationEngine.run`` (the full report
``model_dump()``) and ``render_markdown`` for several fixed configs, so a
behaviour-preserving refactor of ``run``/``render_markdown`` is provably
byte-identical: every idea (id, value, novelty, order, branch_path, facts,
caveats) and every rendered markdown byte must match these digests.

The digests were captured BEFORE the helper-extraction refactor; they must
stay green AFTER. Determinism (no time/random in scoring) makes them stable.

Re-baselined once intentionally: the develop-engine fix that gives each
simplification root an additive ``::simplify-<transform>`` subject (so an
EXECUTABLE behaviour-preserving simplification is no longer deduped away by a
higher-priority recommend-only idea owning the bare module) surfaces one extra
root here — ``Apply merge_nested_if to simplify app/auth.py`` — on the fixture's
nested-if in ``app/auth.py``. Verified to be a clean SUPERSET: every prior idea
(the security finding included) is preserved in order; only the previously
shadowed executable simplification is appended.
"""

import hashlib
import json
from pathlib import Path

import pytest

from app.engine.idea_permutation import IdeaPermutationEngine, render_markdown


def _build_project(tmp: Path) -> None:
    """A small, fixed project that exercises every emit path: roots, deep
    permutations, security/convergence synthesis, dependency-edge pairs, and
    (with facets on) the fractal zoom."""
    (tmp / "app").mkdir()
    (tmp / "app" / "auth.py").write_text(
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
    (tmp / "app" / "api.py").write_text(
        "import app.auth\n"
        "def handler():\n"
        "    return app.auth.login('x')\n"
    )
    (tmp / "app" / "util.py").write_text("def util():\n    return 2\n")


# (name, config, objective, expected dict digest, expected markdown digest)
_CASES = [
    (
        "basic",
        {"max_total_ideas": 25, "max_idea_depth": 2, "breadth": 3},
        None,
        "02ac37097d7ca04d14c8c5c068e6474ea17ae2f0a19a6c678430e785adef4d12",
        "16965082cdfb75abe1e944789e8d23cee4d3da3846f7d29b851f1f445d45a1fe",
    ),
    (
        "facets",
        {
            "max_total_ideas": 60,
            "max_idea_depth": 2,
            "breadth": 4,
            "fractal_facets": True,
            "facets_per_idea": 2,
            "facet_depth": 2,
            "adaptive_depth": True,
        },
        None,
        "297c65cefb36d08589d904d3aeef2b4c0e5e190d03bc6f729ea027a6de924393",
        "62b786041d3303e16ef5ed7be29438250db882d49a4b9d8321c870358d167393",
    ),
    (
        "objective",
        {
            "max_total_ideas": 40,
            "max_idea_depth": 2,
            "breadth": 4,
            "min_relevance": 0.3,
        },
        "improve security and harden authentication",
        "999021ab3d45344c9909b8aa19a2a5eae13387addf5e4cfcf7e0836d33f84b92",
        "1c48c290af922c23d5f78cca69dac0c50e10d80b7588b09eb1eb8e8a0b3db4e9",
    ),
]


def _digests(rep, project_root: str) -> tuple[str, str]:
    d = rep.model_dump()
    d["project_root"] = "<root>"  # neutralize the absolute tmp path
    d["stats"].pop("metrics_error", None)  # OSError text varies by platform
    blob = json.dumps(d, sort_keys=True, default=str)
    md = render_markdown(rep).replace(project_root, "<root>")
    return (
        hashlib.sha256(blob.encode()).hexdigest(),
        hashlib.sha256(md.encode()).hexdigest(),
    )


@pytest.mark.parametrize("name,cfg,objective,dict_sha,md_sha", _CASES)
def test_report_and_markdown_are_byte_identical(
    tmp_path, name, cfg, objective, dict_sha, md_sha
):
    _build_project(tmp_path)
    rep = IdeaPermutationEngine(cfg, tmp_path).run(objective=objective)
    got_dict, got_md = _digests(rep, str(tmp_path))
    assert got_dict == dict_sha, f"{name}: report dict changed"
    assert got_md == md_sha, f"{name}: rendered markdown changed"


def test_run_is_deterministic_across_instances(tmp_path):
    _build_project(tmp_path)
    cfg = {"max_total_ideas": 30, "max_idea_depth": 2, "breadth": 3}
    a = IdeaPermutationEngine(cfg, tmp_path).run()
    b = IdeaPermutationEngine(cfg, tmp_path).run()
    assert a.model_dump() == b.model_dump()
    assert render_markdown(a) == render_markdown(b)


def test_empty_project_renders_without_error(tmp_path):
    # No app/ at all: seeding may still emit roots from the repo skeleton, but
    # the empty/near-empty path must round-trip through run + render cleanly.
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 8, "max_idea_depth": 1, "breadth": 2}, tmp_path
    ).run()
    md = render_markdown(rep)
    assert md.startswith("# Development Ideas for ")
    assert isinstance(rep.model_dump(), dict)
