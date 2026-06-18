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

Re-baselined a second time intentionally: confluence ideas now carry an
abductive ROOT-CAUSE explanation. The fixture's confluence on ``app/api.py``
(hub + symbol-hub + untested) maps its converging hub/symbol-hub signals to two
``high_import_count`` observations, and ``AbductiveReasoner().infer`` attaches
"root cause: Module is a 'god module' with too many concerns (confidence 0.9)".
This rides as a PURELY ADDITIVE enrichment: the confluence idea's rationale gains
the clause and an ``abductive: ...`` source_fact is appended AFTER (never
replacing) ``source_facts[0]``. Verified to be a clean SUPERSET — only the
confluence root and its three permutation children (which inherit the parent's
source_facts) change; every other idea (the security finding included) keeps its
exact subject, title, branch_path, source_facts[0], and emission order. Ideas
with < 2 mappable converging signals are byte-identical to before.
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
        "342315848bf5c40af797e04ee1340d94e145f4f84393a7137661a9d34dec1519",
        "e0a9846a6e3bf11ec08aba72b1a9b54d0058b5bb11dcb0d8765946106ba8a76a",
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
        "f1deb3ee2af377c055bd3fad7550f343e877f8fc4a6e12964611bc223c5aa839",
        "e37055deb284e224d475c0a6ac8088d84a00b199ac716f565758a38d9a3916ac",
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
        "6d90accb975b41a1897f6c6cb582ae72a47445838702d15bbc01788b9a1d6431",
        "9a7f56a94e95ae01927e2ab5027b16c2b1d466a54168caca275e192033f93b66",
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
