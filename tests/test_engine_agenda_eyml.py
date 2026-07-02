"""The agenda's V2 contracts: three honest lanes, deterministic, read-only.

Unit tests drive :func:`build_agenda` through its engine seams (monkeypatched
readiness/memory/realization — the repo's established seam style) so lane
semantics are pinned without a whole-project scan; two end-to-end cases cover
the honest-empty bare project and the CLI.
"""

from __future__ import annotations

import json
from pathlib import Path

import app.engine.agenda as agenda_mod
from app.engine.agenda import build_agenda, render_agenda_markdown


def _pyproject(tmp: Path) -> None:
    (tmp / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")


def _fake_readiness(buckets):
    total = sum(len(v) for v in buckets.values())
    return {"score": 0.5, "weighted": True, "total": total,
            "counts": {k: len(v) for k, v in buckets.items()},
            "buckets": buckets}


class _Memory:
    """A stub IdeaMemory carrying explicit feasibility factors."""

    def __init__(self, factors):
        self._factors = factors

    def feasibility_factor(self, operator, label="", **_):
        return self._factors.get(operator, 1.0)


def _patch_engines(monkeypatch, buckets, factors=None, realization=None):
    monkeypatch.setattr(agenda_mod, "develop_readiness",
                        lambda root="", **kw: _fake_readiness(buckets))
    monkeypatch.setattr(agenda_mod.IdeaMemory, "load",
                        classmethod(lambda cls, root: _Memory(factors or {})))
    monkeypatch.setattr(agenda_mod, "operator_realization_factors",
                        lambda root: dict(realization or {}))


# --------------------------------------------------------------------------- #
# Lane semantics
# --------------------------------------------------------------------------- #


def test_landable_lane_ranks_by_demoted_value_then_file(monkeypatch, tmp_path):
    buckets = {
        "fixable_now": [
            {"file": "b.py", "line": 5, "category": "typing",
             "fix_kind": "infer_type_hints", "message": ""},
            {"file": "a.py", "line": 1, "category": "tests",
             "fix_kind": "create_test_stub", "message": ""},
            {"file": "c.py", "line": 9, "category": "typing",
             "fix_kind": "infer_type_hints", "message": ""},
        ],
        "flag_only": [], "unknown": [],
    }
    # Demote create_test_stub (0.96 — BELOW neutral but ABOVE the V4
    # retirement floor of 0.92, so it stays landable) so the two
    # infer_type_hints entries lead.
    _patch_engines(monkeypatch, buckets,
                   factors={"create_test_stub": 0.96},
                   realization={"create_test_stub": 0.7})
    lane = build_agenda(tmp_path)["lanes"]["landable"]
    assert [e["rank"] for e in lane] == [1, 2, 3]
    assert lane[0]["file"] == "b.py" and lane[1]["file"] == "c.py"
    assert lane[2]["fix_kind"] == "create_test_stub"
    assert lane[2]["value"] < lane[0]["value"]


def test_human_lane_carries_rationale(monkeypatch, tmp_path):
    buckets = {
        "fixable_now": [],
        "flag_only": [
            {"file": "core.py", "line": 42, "category": "design",
             "fix_kind": "design_task", "message": "split the god class"},
        ],
        "unknown": [],
    }
    _patch_engines(monkeypatch, buckets)
    lane = build_agenda(tmp_path)["lanes"]["human"]
    assert lane == [{"fix_kind": "design_task", "file": "core.py", "line": 42,
                     "category": "design", "rationale": "split the god class"}]


def test_watched_lane_surfaces_only_below_neutral_operators(monkeypatch, tmp_path):
    buckets = {
        "fixable_now": [
            {"file": "a.py", "line": 1, "category": "t",
             "fix_kind": "drop_param", "message": ""},
            {"file": "b.py", "line": 2, "category": "t",
             "fix_kind": "dataclassify", "message": ""},
        ],
        "flag_only": [], "unknown": [],
    }
    # 0.96 sits below neutral but above the V4 retirement floor (0.92):
    # exactly the "watched, not retired" band this test characterizes.
    _patch_engines(monkeypatch, buckets,
                   factors={"drop_param": 0.96},
                   realization={"drop_param": 0.8})
    watched = build_agenda(tmp_path)["lanes"]["watched"]
    assert [w["operator"] for w in watched] == ["drop_param"]
    assert "feasibility 0.96" in watched[0]["note"]
    assert "realization 0.80" in watched[0]["note"]
    assert not watched[0].get("retired")


def test_agenda_is_deterministic(monkeypatch, tmp_path):
    buckets = {
        "fixable_now": [
            {"file": "z.py", "line": 3, "category": "t",
             "fix_kind": "infer_type_hints", "message": ""},
        ],
        "flag_only": [], "unknown": [],
    }
    _patch_engines(monkeypatch, buckets)
    a = json.dumps(build_agenda(tmp_path), sort_keys=True)
    b = json.dumps(build_agenda(tmp_path), sort_keys=True)
    assert a == b


def test_markdown_counts_overflow_instead_of_hiding_it(monkeypatch, tmp_path):
    buckets = {
        "fixable_now": [
            {"file": f"m{i:02d}.py", "line": i, "category": "t",
             "fix_kind": "infer_type_hints", "message": ""}
            for i in range(14)
        ],
        "flag_only": [], "unknown": [],
    }
    _patch_engines(monkeypatch, buckets)
    md = render_agenda_markdown(build_agenda(tmp_path))
    assert "14 (showing 10 of 14)" in md
    assert "m09.py" in md and "m13.py" not in md  # capped render, counted total


# --------------------------------------------------------------------------- #
# End-to-end
# --------------------------------------------------------------------------- #


def test_bare_project_yields_honest_empty_agenda(tmp_path):
    _pyproject(tmp_path)
    agenda = build_agenda(tmp_path)
    assert agenda["total_findings"] == 0
    assert agenda["lanes"] == {"landable": [], "human": [], "watched": [],
                               "user": []}
    md = render_agenda_markdown(agenda)
    assert "Nothing provable-landable right now" in md
    assert "No human-decision items" in md
    assert "No learned demotions" in md


def test_cmd_agenda_json_roundtrip(tmp_path, capsys):
    import argparse

    from app.cli_insight import cmd_agenda

    _pyproject(tmp_path)
    ns = argparse.Namespace(target=str(tmp_path), json=True)
    assert cmd_agenda(ns) == 0
    first = capsys.readouterr().out
    assert cmd_agenda(ns) == 0
    assert capsys.readouterr().out == first
    assert json.loads(first)["schema_version"] == 1
