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

Re-baselined a third time intentionally: three further reasoning lenses now
plug into the enricher seam (``app.engine.idea_reasoning``) — counterfactual
("risk if unaddressed: ..."), remediation-sequencing ("fix order: ...") and
hypothesis ("hypothesis: ..."). The fixture's ``app/api.py`` confluence
(hub + symbol-hub + untested) gains their additional rationale clauses and
``counterfactual:`` / ``sequence:`` / ``hypothesis:`` source_facts (each
appended AFTER source_facts[0]). Independently verified a clean SUPERSET: of
25 ideas only the confluence root and its inherited permutation children
change; every other idea keeps its exact subject, title, branch_path,
source_facts[0] and emission order.

Re-baselined a fourth time intentionally: two further reasoning lenses
(interaction; effort) plug into the seam and the hypothesis fact is de-doubled
to a single ``hypothesis:`` prefix. Purely additive — they only append facts
to the confluence idea; source_facts[0], every prior idea identity, and
emission order are preserved. (Dream-discovery seeding was evaluated and
deliberately NOT wired: as competing roots it displaced valuable synthesis
ideas under the bounded budget.)
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
        "e16c1291d728c6d10d2102f41534f8beaad56a757d60ee07985c1b10e311f0fe",
        "92ac865cf43a17275a73bac6bb2d98183d789d57f486c9a811e9ede9491e9019",
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
        "2cd46f6c9711cb4d80736fc4214e6a384c09a55af8cea14a0ff32de8c37d1ac1",
        "266546ccaba377ec15352c5b6fd3b99b741f5fdfad9c94ad191a84c403e4f528",
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
        "c433479d757d2c3e12abadc2752071462f3f2acaaeb5bb87e824bd484f156f2d",
        "17f642bdfb9e6c4dc416a8d2ab994a038a8af9b559989239c7af3a1aab4880c2",
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
