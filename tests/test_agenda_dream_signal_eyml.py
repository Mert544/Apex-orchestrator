"""The agenda's V6 contract (obsidian bridge): a dream-confluence tiebreak.

``build_agenda`` reads ``app.engine.dream_landing.dream_signal_weight`` — a pure,
offline store read of the dream's PERSISTED confluence modules (no live dream, no
clock/random) — and folds it into ``_landable_lane``'s sort key as a SECOND
descending tiebreak, right after value: within a value tier, a module the dream
graduated as a CONFLUENCE now leads its same-value peers instead of losing to
plain alphabetic file order. Mirrors the SAME pattern ``apex auto`` already
trusts for its action plan (``idea_action_bridge._dream_step_boost`` +
``cli_autonomy._auto_dream_boost``). Pinned here:

* an EMPTY/absent confluence store (the default — no ``apex dream --curate`` has
  ever run) makes ``dream_signal_weight`` return ``{}``, so the landable order is
  BYTE-IDENTICAL to the pre-dream-signal shape (the RAILS invariant);
* a PERSISTED confluence for one module lifts that module's entry ahead of its
  same-value peers — concretely, from a rank OUTSIDE ``_LANE_CAP`` into rank 1,
  reproducing the live evidence (``app/execution/cross_file_rename.py`` sitting
  at 435/18217, far outside the visible lane);
* the tiebreak is pure re-ranking: it changes WHICH RANK an entry gets, never its
  scored value, never which entries are retired, and never which entries land
  here at all;
* a confluence naming a module that no longer exists on disk is dropped by
  ``dream_landing`` itself, so a stale promotion cannot silently reorder today's
  agenda.
"""

from __future__ import annotations

import json
from pathlib import Path

import app.engine.agenda as agenda_mod
from app.engine.agenda import _LANE_CAP, _landable_lane, build_agenda


def _pyproject(tmp: Path) -> None:
    (tmp / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")


def _many_same_value_bucket(n: int) -> dict:
    """``n`` fixable_now findings sharing ONE fix_kind (identical static value),
    named so plain alphabetic order sorts them m00.py, m01.py, ... — the exact
    "every finding ties on value" shape the live evidence (18,217 landable
    entries at value=0.3) describes."""
    return {
        "fixable_now": [
            {"file": f"m{i:02d}.py", "line": 1, "category": "types",
             "fix_kind": "infer_type_hints", "message": ""}
            for i in range(n)
        ],
        "flag_only": [], "unknown": [],
    }


# --------------------------------------------------------------------------- #
# Unit level: _landable_lane's sort key directly
# --------------------------------------------------------------------------- #


def test_empty_dream_weight_is_byte_identical_to_pre_dream_order():
    buckets = _many_same_value_bucket(12)
    plain_order = [f"m{i:02d}.py" for i in range(12)]
    no_param, _ = _landable_lane(buckets, None, {})
    empty_map, _ = _landable_lane(buckets, None, {}, dream_weight={})
    none_map, _ = _landable_lane(buckets, None, {}, dream_weight=None)
    assert [e["file"] for e in no_param] == plain_order
    assert [e["file"] for e in empty_map] == plain_order
    assert [e["file"] for e in none_map] == plain_order


def test_confluence_module_rises_from_outside_cap_to_rank_one():
    buckets = _many_same_value_bucket(12)
    target = "m11.py"  # sorts LAST alphabetically -> rank 12, outside _LANE_CAP=10
    baseline, _ = _landable_lane(buckets, None, {})
    baseline_rank = next(e["rank"] for e in baseline if e["file"] == target)
    assert baseline_rank == 12
    assert baseline_rank > _LANE_CAP  # confirms it starts OUTSIDE the visible lane

    boosted, _ = _landable_lane(buckets, None, {}, dream_weight={target: 1.0})
    boosted_rank = next(e["rank"] for e in boosted if e["file"] == target)
    assert boosted_rank == 1  # leads every same-value peer
    assert boosted_rank <= _LANE_CAP  # now visible within the capped lane


def test_dream_weight_never_changes_scored_value_or_lane_membership():
    buckets = _many_same_value_bucket(5)
    baseline, baseline_retired = _landable_lane(buckets, None, {})
    boosted, boosted_retired = _landable_lane(
        buckets, None, {}, dream_weight={"m04.py": 1.0})
    assert {e["file"] for e in baseline} == {e["file"] for e in boosted}
    assert baseline_retired == boosted_retired == {}
    baseline_values = {e["file"]: e["value"] for e in baseline}
    boosted_values = {e["file"]: e["value"] for e in boosted}
    assert baseline_values == boosted_values  # values untouched, only order moved


def test_dream_weight_never_reorders_across_value_tiers():
    """The dream-signal tiebreak is SECONDARY to value: a boosted low-value entry
    never leaps ahead of a higher-value entry."""
    buckets = {
        "fixable_now": [
            {"file": "low.py", "line": 1, "category": "types",
             "fix_kind": "infer_type_hints", "message": ""},  # 0.72
            {"file": "high.py", "line": 1, "category": "tests",
             "fix_kind": "cover_gaps", "message": ""},  # 0.90
        ],
        "flag_only": [], "unknown": [],
    }
    entries, _ = _landable_lane(buckets, None, {}, dream_weight={"low.py": 1.0})
    assert [e["file"] for e in entries] == ["high.py", "low.py"]


def test_multiple_confluences_tie_break_by_file_among_themselves():
    """Two boosted entries both lead the unboosted rest, and fall back to the
    existing file tiebreak between each other — the sort stays a TOTAL order."""
    buckets = _many_same_value_bucket(12)
    entries, _ = _landable_lane(
        buckets, None, {}, dream_weight={"m11.py": 1.0, "m05.py": 1.0})
    assert [e["file"] for e in entries[:2]] == ["m05.py", "m11.py"]
    assert entries[0]["rank"] == 1 and entries[1]["rank"] == 2


# --------------------------------------------------------------------------- #
# End-to-end: build_agenda reads the REAL .apex/dream-promotions.json store
# --------------------------------------------------------------------------- #


def _fake_readiness(buckets):
    total = sum(len(v) for v in buckets.values())
    return {"score": 0.5, "weighted": True, "total": total,
            "counts": {k: len(v) for k, v in buckets.items()},
            "buckets": buckets}


def _patch_readiness(monkeypatch, buckets):
    """Only ``develop_readiness`` is faked — memory/realization/gate/dream are
    left to run FOR REAL against ``tmp_path``, since all four are naturally
    neutral/empty on a project carrying no ``.apex/`` state (pinned by
    ``test_build_agenda_is_byte_identical_with_no_persisted_confluence``)."""
    monkeypatch.setattr(agenda_mod, "develop_readiness",
                        lambda root="", **kw: _fake_readiness(buckets))


def _seed_confluence(tmp: Path, module: str) -> None:
    """Persist a REAL ``.apex/dream-promotions.json`` naming ``module`` as a
    graduated confluence, and make sure the module file actually EXISTS (the
    same existence check ``dream_landing._confluence_key_module`` applies)."""
    target = tmp / module
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x = 1\n")
    (tmp / ".apex").mkdir(exist_ok=True)
    (tmp / ".apex" / "dream-promotions.json").write_text(json.dumps(
        [{"key": f"confluence:{module}", "kind": "confluence",
          "confidence": 0.9, "support": 4, "text": "test confluence"}]))


def test_build_agenda_is_byte_identical_with_no_persisted_confluence(
        monkeypatch, tmp_path):
    """RAILS pin: no ``.apex/dream-promotions.json`` at all -> dream_signal_weight
    yields ``{}`` -> the landable order is byte-identical to the pre-V6 shape,
    and the whole agenda stays reproducible."""
    _pyproject(tmp_path)
    buckets = _many_same_value_bucket(12)
    _patch_readiness(monkeypatch, buckets)
    agenda = build_agenda(tmp_path)
    order = [e["file"] for e in agenda["lanes"]["landable"]]
    assert order == [f"m{i:02d}.py" for i in range(12)]
    assert json.dumps(agenda, sort_keys=True) == json.dumps(
        build_agenda(tmp_path), sort_keys=True)


def test_build_agenda_surfaces_persisted_confluence_within_the_cap(
        monkeypatch, tmp_path):
    """CONCRETE reproduction of the live evidence: a module that would sort deep
    (outside ``_LANE_CAP``) on file order alone rises to rank 1 once the dream
    has PERSISTED it as a confluence — the organism's hardest-won multi-night
    discovery becomes visible on the human-read surface."""
    _pyproject(tmp_path)
    buckets = _many_same_value_bucket(12)
    _patch_readiness(monkeypatch, buckets)
    target = "m11.py"

    baseline = build_agenda(tmp_path)
    baseline_rank = next(e["rank"] for e in baseline["lanes"]["landable"]
                         if e["file"] == target)
    assert baseline_rank > _LANE_CAP  # confluence starts invisible, like cross_file_rename.py

    _seed_confluence(tmp_path, target)
    boosted = build_agenda(tmp_path)
    boosted_rank = next(e["rank"] for e in boosted["lanes"]["landable"]
                        if e["file"] == target)
    assert boosted_rank == 1
    assert boosted_rank <= _LANE_CAP  # now inside the visible lane


def test_build_agenda_confluence_for_absent_file_is_ignored(monkeypatch, tmp_path):
    """A confluence key naming a module that no longer exists under the project
    is dropped by ``dream_landing`` itself (``_confluence_key_module``), so a
    stale promotion cannot silently reorder today's agenda."""
    _pyproject(tmp_path)
    buckets = _many_same_value_bucket(12)
    _patch_readiness(monkeypatch, buckets)
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "dream-promotions.json").write_text(json.dumps(
        [{"key": "confluence:does/not/exist.py", "kind": "confluence"}]))
    agenda = build_agenda(tmp_path)
    order = [e["file"] for e in agenda["lanes"]["landable"]]
    assert order == [f"m{i:02d}.py" for i in range(12)]  # unchanged
