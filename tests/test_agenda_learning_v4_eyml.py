"""V4 learning-depth contracts: retirement is demote-only and explained.

The agenda's learned-caution feedback must be MONOTONE: neutral memory yields
the byte-identical pre-learning agenda; severe operator caution (feasibility
at its floor, or realization at/below half) RETIRES entries from landable
into watched with a stated reason; a dream-gate tighten factor annotates the
matching module's entries without retiring them. Nothing here can ever
promote — caution only removes or explains.
"""

from __future__ import annotations

from typing import Any

import app.engine.agenda as agenda_mod
from app.engine.agenda import build_agenda


class _Memory:
    """A stub IdeaMemory exposing only what the agenda consumes."""

    def __init__(self, factors: dict[str, float]):
        self._factors = factors

    def feasibility_factor(self, operator: str, label: str = "",
                           target: str = "", characteristic: Any = None) -> float:
        return self._factors.get(operator, 1.0)


_BUCKETS = {
    "fixable_now": [
        {"fix_kind": "infer_type_hints", "file": "pkg/a.py", "line": 3,
         "category": "types", "message": ""},
        {"fix_kind": "create_test_stub", "file": "pkg/b.py", "line": 9,
         "category": "testing", "message": ""},
    ],
    "flag_only": [],
    "unknown": [],
}


def _patched_agenda(monkeypatch, tmp_path, *, memory=None, realization=None,
                    gate_factors=None):
    monkeypatch.setattr(agenda_mod, "develop_readiness",
                        lambda root, weight_by_reliability: {
                            "score": 1.0, "total": 2,
                            "buckets": {k: list(v) for k, v in _BUCKETS.items()}})
    monkeypatch.setattr(agenda_mod.IdeaMemory, "load",
                        classmethod(lambda cls, root: memory or _Memory({})))
    monkeypatch.setattr(agenda_mod, "operator_realization_factors",
                        lambda root: dict(realization or {}))
    monkeypatch.setattr(agenda_mod, "gate_tighten_factors",
                        lambda root: dict(gate_factors or {}))
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")
    return build_agenda(tmp_path)


def test_neutral_memory_is_byte_identical_to_prelearning(monkeypatch, tmp_path):
    agenda = _patched_agenda(monkeypatch, tmp_path)
    landable = agenda["lanes"]["landable"]
    assert [e["fix_kind"] for e in landable] == [
        "infer_type_hints", "create_test_stub"]  # static value order, no retirement
    assert all("note" not in e for e in landable)
    assert agenda["lanes"]["watched"] == []


def test_floor_feasibility_retires_with_reason(monkeypatch, tmp_path):
    agenda = _patched_agenda(
        monkeypatch, tmp_path, memory=_Memory({"infer_type_hints": 0.90}))
    landable = agenda["lanes"]["landable"]
    assert [e["fix_kind"] for e in landable] == ["create_test_stub"]  # survivor
    assert landable[0]["rank"] == 1  # ranks recompute over survivors
    watched = agenda["lanes"]["watched"]
    retired = [w for w in watched if w.get("retired")]
    assert len(retired) == 1
    assert retired[0]["operator"] == "infer_type_hints"
    assert retired[0]["entries"] == 1
    assert "rollbacks dominate" in retired[0]["note"]


def test_under_half_realization_retires_with_reason(monkeypatch, tmp_path):
    agenda = _patched_agenda(
        monkeypatch, tmp_path, realization={"create_test_stub": 0.40})
    landable = agenda["lanes"]["landable"]
    assert [e["fix_kind"] for e in landable] == ["infer_type_hints"]
    retired = [w for w in agenda["lanes"]["watched"] if w.get("retired")]
    assert retired and "under-delivered" in retired[0]["note"]


def test_mild_caution_demotes_rank_but_never_retires(monkeypatch, tmp_path):
    # 0.95 sits above the retirement floor: the entry stays landable, its
    # scored value simply carries the demotion (monotone, no removal).
    neutral = _patched_agenda(monkeypatch, tmp_path)
    demoted = _patched_agenda(
        monkeypatch, tmp_path, memory=_Memory({"create_test_stub": 0.95}))
    assert len(demoted["lanes"]["landable"]) == len(neutral["lanes"]["landable"])
    val = {e["fix_kind"]: e["value"] for e in demoted["lanes"]["landable"]}
    neutral_val = {e["fix_kind"]: e["value"] for e in neutral["lanes"]["landable"]}
    assert val["create_test_stub"] <= neutral_val["create_test_stub"]
    assert val["infer_type_hints"] == neutral_val["infer_type_hints"]


def test_dream_gate_factor_annotates_module_without_retiring(monkeypatch, tmp_path):
    agenda = _patched_agenda(
        monkeypatch, tmp_path, gate_factors={"confluence:pkg.a": 0.55})
    landable = {e["fix_kind"]: e for e in agenda["lanes"]["landable"]}
    assert "dream gate tightened" in landable["infer_type_hints"]["note"]
    assert "factor 0.55" in landable["infer_type_hints"]["note"]
    assert "note" not in landable["create_test_stub"]
    assert not [w for w in agenda["lanes"]["watched"] if w.get("retired")]


def test_caution_never_promotes(monkeypatch, tmp_path):
    # The whole-lane invariant: adding ANY caution signal can only shrink the
    # landable lane or lower values — never grow it or raise a value.
    neutral = _patched_agenda(monkeypatch, tmp_path)
    cautious = _patched_agenda(
        monkeypatch, tmp_path,
        memory=_Memory({"infer_type_hints": 0.90, "create_test_stub": 0.95}),
        realization={"create_test_stub": 0.60},
        gate_factors={"confluence:pkg.b": 0.30})
    assert len(cautious["lanes"]["landable"]) <= len(neutral["lanes"]["landable"])
    neutral_val = {e["fix_kind"]: e["value"] for e in neutral["lanes"]["landable"]}
    for entry in cautious["lanes"]["landable"]:
        assert entry["value"] <= neutral_val[entry["fix_kind"]]
