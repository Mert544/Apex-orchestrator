"""Characterization snapshot for the idea-permutation engine.

Pins the *exact* output of ``IdeaPermutationEngine.run`` (the full report
``model_dump()``) and ``render_markdown`` for several fixed configs, so a
behaviour-preserving refactor of ``run``/``render_markdown`` is provably
byte-identical: every idea (id, value, novelty, order, branch_path, facts,
caveats) and every rendered markdown byte must match these digests.

The digests were captured BEFORE the helper-extraction refactor; they must
stay green AFTER. Determinism (no time/random in scoring) makes them stable.
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
        "0af96975c1e85a9c4cd4960cc67fa409b1d9cde27475d5968d508dfa2eed7b5e",
        "f99aee3823cfbf8f0bd71a5dcbc6b94a4b37f0774a85df1f2724737927be29bf",
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
        "f24f252c653b968fa715eb5d27d7cbcefe58ba7f3f5fa1fc95d66c21c0472d47",
        "207b92b425635e618e9c3f14fcf529fc3ea8f430a23f338ba65ed485257a0c58",
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
        "c23dbee805051a1966604ba3ba5101139a6463224c141a8ace7644208376d58d",
        "4870d35c6abfe0a63d94dbe28e698eeb1f4915118de5b17b07cb025e7a18d9a0",
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
