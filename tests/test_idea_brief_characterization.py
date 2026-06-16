"""Characterization harness: build_brief must stay byte-identical through the
refactor.

This compares the live (refactored) `build_brief` against a verbatim copy of
the ORIGINAL implementation, frozen inline as `_orig_build_brief` below, across
a matrix of inputs that exercises every branch of the function:

  - no candidates -> None;
  - branch_path match (break path) vs subject match vs design-level default;
  - max() selection tie-break on (value, branch_path);
  - measured filtering (each metric present / None);
  - lens from operator-in-_FACETS vs label-in-_LABEL_LENS vs fallback;
  - convergence phased steps (>= 2 labels) vs none;
  - evidence binding from a real on-disk subject vs none;
  - rationale present vs empty (why composition);
  - fan_in present vs absent (blast-radius done-when insertion).

`_orig_build_brief` is the original function body unchanged, reusing the live
module's still-unchanged collaborators (`Brief`, `_lens_for`, `_bind_evidence`,
and the imported facet/convergence helpers). It is the oracle; any divergence
fails loudly with the full repr diff.
"""

from __future__ import annotations

import itertools

from app.engine import idea_brief as live
from app.engine.idea_brief import Brief, _bind_evidence, _lens_for
from app.engine.idea_permutation import (
    _FACET_SUBASPECTS,
    _FACETS,
    convergence_labels,
    convergence_plan,
)
from app.models.idea import IdeaNode, IdeaTreeReport


def _orig_build_brief(report: IdeaTreeReport, branch_path: str = "",
                      subject: str = "") -> Brief | None:
    """Verbatim copy of the pre-refactor build_brief — the oracle."""
    from app.engine.idea_action_bridge import IdeaActionBridge

    bridge = IdeaActionBridge()
    candidates: list[IdeaNode] = []
    for node in report.ideas:
        if branch_path and node.branch_path == branch_path:
            candidates = [node]
            break
        if subject and not branch_path:
            base = node.subject.split(" :: ", 1)[0].split("::", 1)[0]
            if base == subject:
                candidates.append(node)
        elif not branch_path and not bridge.plan_idea(node).executable:
            candidates.append(node)
    if not candidates:
        return None
    node = (candidates[0] if branch_path
            else max(candidates, key=lambda n: (n.value, n.branch_path)))

    subject_module = node.subject.split(" :: ", 1)[0].split("::", 1)[0]
    fan_in = (report.stats.get("fan_in") or {}).get(subject_module)
    metrics = (report.stats.get("metrics") or {}).get(subject_module) or {}
    measured = {k: v for k, v in {
        "fan_in": fan_in,
        "loc": metrics.get("loc"),
        "complexity": metrics.get("complexity"),
        "symbols": metrics.get("symbols"),
    }.items() if v is not None}

    lens = _lens_for(node)
    plan = [(aspect, list(_FACET_SUBASPECTS.get(aspect, []))) for aspect in _FACETS[lens]]

    conv = convergence_labels(node)
    phased = convergence_plan(conv) if len(conv) >= 2 else []

    evidence = _bind_evidence(report, subject_module, plan)

    done = [
        "`pytest -q` stays green (every change test-verified).",
        f"`apex ideate --roadmap --diff` no longer surfaces “{node.title}” "
        "— the engine itself confirms the work landed.",
        "`apex grade` does not drop.",
    ]
    if fan_in:
        done.insert(1, f"The {fan_in} importing module(s) still pass their tests "
                       "(blast radius re-verified).")

    return Brief(
        branch_path=node.branch_path, title=node.title, subject=node.subject,
        operator=lens,
        why=[*node.source_facts[:2], node.rationale] if node.rationale else list(node.source_facts[:2]),
        measured=measured, plan=plan, phased_steps=phased, done_when=done,
        evidence=evidence,
    )


def _node(**kw) -> IdeaNode:
    base = dict(
        id="n", title="t", subject="app/core.py", rationale="",
        branch_path="bp", operator="root", source_facts=[], value=0.0,
    )
    base.update(kw)
    return IdeaNode(**base)


def _nonexec_node(**kw) -> IdeaNode:
    # operator "root" with no executable mapping stays design-level.
    return _node(**kw)


def _make_subject_file(tmp_path, body: str) -> None:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "core.py").write_text(body, encoding="utf-8")


# A spread of nodes covering lens sources, rationale, source_facts, values.
_NODES = [
    _nonexec_node(id="a", branch_path="extend.a", operator="root",
                  source_facts=["dependency-hub: core imported by 3"],
                  rationale="because hub", value=0.7,
                  subject="app/core.py :: foo"),
    _nonexec_node(id="b", branch_path="harden.b", operator="harden",
                  source_facts=["security-finding: eval here"],
                  rationale="", value=0.9, subject="app/core.py"),
    _nonexec_node(id="c", branch_path="test.c", operator="root",
                  source_facts=["untested: no tests"], rationale="r",
                  value=0.7, subject="app/core.py"),
    _nonexec_node(id="d", branch_path="extend.d", operator="root",
                  source_facts=["mystery-label: nothing"], rationale="",
                  value=0.7, subject="app/other.py"),
    _nonexec_node(id="e", branch_path="conv.e", operator="root",
                  source_facts=["convergence: untested + a complexity hotspot"],
                  rationale="converge", value=0.5, subject="app/core.py"),
    _nonexec_node(id="f", branch_path="conv.f", operator="root",
                  source_facts=["convergence: untested"],
                  rationale="", value=0.5, subject="app/core.py"),
    _nonexec_node(id="g", branch_path="gen.g", operator="generalize",
                  source_facts=[], rationale="", value=0.7,
                  subject="app/core.py :: bar"),
]

_STATS_VARIANTS = [
    {},
    {"fan_in": {"app/core.py": 3}},
    {"metrics": {"app/core.py": {"loc": 10, "complexity": 5, "symbols": 2}}},
    {"fan_in": {"app/core.py": 4},
     "metrics": {"app/core.py": {"loc": 12, "complexity": None, "symbols": 0}}},
    {"fan_in": {"app/core.py": 0},
     "metrics": {"app/core.py": {"loc": None, "complexity": 7}}},
]


def _compare(report, **kwargs):
    a = _orig_build_brief(report, **kwargs)
    b = live.build_brief(report, **kwargs)
    if a is None or b is None:
        assert a is None and b is None, (kwargs, a, b)
        return
    assert a.to_dict() == b.to_dict(), (kwargs, a.to_dict(), b.to_dict())
    # Markdown render must also match (downstream byte-identical).
    assert (live.render_brief_markdown(a)
            == live.render_brief_markdown(b)), kwargs


def _report(tmp_path, ideas, stats):
    rep = IdeaTreeReport(objective="o", ideas=ideas, stats=stats)
    rep.project_root = str(tmp_path)
    return rep


def test_no_candidates_returns_none(tmp_path):
    rep = _report(tmp_path, [], {})
    _compare(rep)
    _compare(rep, branch_path="nope")
    _compare(rep, subject="app/ghost.py")


def test_matrix_default_and_targeted(tmp_path):
    _make_subject_file(
        tmp_path,
        "def fetch(url):\n"
        "    try:\n"
        "        return url\n"
        "    except:\n"
        "        return None\n",
    )
    for stats in _STATS_VARIANTS:
        rep = _report(tmp_path, list(_NODES), stats)
        # design-level default selection
        _compare(rep)
        # subject targeting (stable subject path)
        _compare(rep, subject="app/core.py")
        _compare(rep, subject="app/other.py")
        _compare(rep, subject="app/ghost.py")
        # branch_path targeting for each node (break path)
        for n in _NODES:
            _compare(rep, branch_path=n.branch_path)
        # branch_path that matches nothing
        _compare(rep, branch_path="does.not.exist")


def test_max_tiebreak_on_value_and_branch(tmp_path):
    # Equal value -> branch_path breaks the tie deterministically.
    nodes = [
        _nonexec_node(id="x", branch_path="zzz.last", value=0.5,
                      source_facts=["untested: x"]),
        _nonexec_node(id="y", branch_path="aaa.first", value=0.5,
                      source_facts=["untested: y"]),
        _nonexec_node(id="z", branch_path="mmm.mid", value=0.5,
                      source_facts=["untested: z"]),
    ]
    rep = _report(tmp_path, nodes, {})
    _compare(rep)


def test_evidence_absent_when_subject_missing(tmp_path):
    # No file on disk -> evidence empties; still must match.
    rep = _report(tmp_path, list(_NODES), {})
    _compare(rep, branch_path="harden.b")


def test_non_py_subject_skips_evidence(tmp_path):
    n = _nonexec_node(id="np", branch_path="ext.np", subject="app/data.txt",
                      source_facts=["mystery: x"])
    rep = _report(tmp_path, [n], {})
    _compare(rep, branch_path="ext.np")


def test_branch_path_wins_over_subject(tmp_path):
    # When both given, branch_path takes the break path.
    rep = _report(tmp_path, list(_NODES), {})
    for n in _NODES:
        _compare(rep, branch_path=n.branch_path, subject="app/core.py")


def test_pairwise_subset_reports(tmp_path):
    _make_subject_file(tmp_path, "def f():\n    return 1\n")
    for combo in itertools.combinations(_NODES, 2):
        rep = _report(tmp_path, list(combo), _STATS_VARIANTS[3])
        _compare(rep)
        _compare(rep, subject="app/core.py")
