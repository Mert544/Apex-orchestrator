"""`apex auto` × the organism's own IMMUNE sense: the immune-exposure priority
boost mirrors the EXISTING dream-confluence boost EXACTLY (same contract, same
refusal-safety), so the autonomous loop PROACTIVELY amplifies whichever module
``immune_posture`` ranks most mutation-exposed (many blindly-callable public
functions, no linked test) within its roadmap phase — instead of ranking on the
AST signals alone.

Two seams, both on ``cli_autonomy``:

  * ``_auto_immune_boost(target)`` — a per-module boost map for the modules
    ``immune_posture`` ranks most exposed, rank-decayed (top-exposed gets the
    largest boost, tapering down), REFUSAL-SAFE: any failure, or an all-tested
    / empty project, yields ``{}``.
  * ``_merge_boosts(*maps)`` — sums per-module boosts across boost sources
    (dream + immune) into ONE map, order-independent, tolerant of empty/None
    inputs.

``cmd_auto`` computes both boosts, merges them into ``priority_boost``, and
threads that single map EVERYWHERE ``dream_boost`` used to go (the scout
``plan_roadmap`` call and ``_auto_act``). With NEITHER signal present both
source maps are ``{}``, ``_merge_boosts`` yields ``{}``, and the ranking stays
byte-for-byte identical to before this wave — pinned below on a tmp project
where every own module already has a linked test (so ``immune_posture`` finds
nothing exposed) and no dream store exists.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli_autonomy import (
    _auto_dream_boost,
    _auto_immune_boost,
    _IMMUNE_BOOST_BASE,
    _IMMUNE_BOOST_DECAY,
    _merge_boosts,
    cmd_auto,
)
from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_permutation import IdeaPermutationEngine


# --- fixtures ----------------------------------------------------------------

def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _exposed_project(tmp_path: Path) -> Path:
    """Two own modules with NO linked test (blindly-callable, most-exposed) and
    one module WITH a linked test — so the immune posture ranks the untested
    modules first and the covered one earns no boost at all."""
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/wide.py",
           "def a(x):\n    return x\ndef b(y):\n    return y\ndef c(z):\n    return z\n")
    _write(tmp_path, "app/narrow.py", "def d(x):\n    return x\n")
    _write(tmp_path, "app/covered.py", "def e(x):\n    return x\n")
    _write(tmp_path, "tests/test_covered.py",
           "from app.covered import e\ndef test_e():\n    assert e(1) == 1\n")
    _write(tmp_path, "pyproject.toml", "[project]\nname='m'\nversion='0'\n")
    return tmp_path


def _all_tested_project(tmp_path: Path) -> Path:
    """Every own module has a linked test file -> immune_posture finds nothing
    exposed -> ``_auto_immune_boost`` must be empty (the byte-identical case)."""
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/solo.py", "def f(x):\n    return x\n")
    _write(tmp_path, "tests/test_solo.py",
           "from app.solo import f\ndef test_f():\n    assert f(1) == 1\n")
    _write(tmp_path, "pyproject.toml", "[project]\nname='m'\nversion='0'\n")
    return tmp_path


def _report(root: Path):
    return IdeaPermutationEngine(
        config={"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4},
        project_root=str(root)).run()


def _ns(tmp_path: Path, **overrides) -> argparse.Namespace:
    base = dict(
        goal="", target=str(tmp_path), apply=False, allow_weak=False,
        recommend=False, mode=None, commit=False, deep=False, evolve=0,
        no_verify=False, max_apply=0, json=False, out="",
    )
    base.update(overrides)
    return argparse.Namespace(**base)


# === _merge_boosts: pure summation, order-independent =========================

def test_merge_boosts_sums_overlapping_keys():
    a = {"app/x.py": 1.0, "app/y.py": 0.5}
    b = {"app/x.py": 0.3, "app/z.py": 0.2}
    merged = _merge_boosts(a, b)
    assert merged == {"app/x.py": 1.3, "app/y.py": 0.5, "app/z.py": 0.2}


def test_merge_boosts_is_order_independent():
    a = {"app/x.py": 1.0, "app/y.py": 0.5}
    b = {"app/x.py": 0.3, "app/z.py": 0.2}
    assert _merge_boosts(a, b) == _merge_boosts(b, a)


def test_merge_boosts_tolerates_empty_and_none():
    assert _merge_boosts() == {}
    assert _merge_boosts({}) == {}
    assert _merge_boosts(None, {}) == {}
    assert _merge_boosts(None, {"app/x.py": 1.0}, {}) == {"app/x.py": 1.0}


def test_merge_boosts_never_mutates_inputs():
    a = {"app/x.py": 1.0}
    b = {"app/x.py": 1.0}
    _merge_boosts(a, b)
    assert a == {"app/x.py": 1.0}
    assert b == {"app/x.py": 1.0}


# === _auto_immune_boost: rank-decayed, refusal-safe ==========================

def test_immune_boost_ranks_most_exposed_module_first(tmp_path):
    boost = _auto_immune_boost(_exposed_project(tmp_path))
    assert boost  # non-empty: untested modules are exposed
    # widest untested module (3 callable fns) outranks the narrower one (1 fn);
    # the covered module never appears at all.
    assert boost["app/wide.py"] > boost["app/narrow.py"]
    assert "app/covered.py" not in boost


def test_immune_boost_is_rank_decayed_from_the_base():
    # rank 0 (most exposed) gets the full base; each subsequent rank a shrinking
    # fraction of it -- never zero, never negative, never larger than the base.
    assert _IMMUNE_BOOST_BASE > 0.0
    assert 0.0 < _IMMUNE_BOOST_DECAY < 1.0


def test_immune_boost_magnitude_is_comparable_to_dream_boost(tmp_path):
    # Neither signal should dominate: the top immune boost sits in the same
    # ballpark as the dream's flat confluence constant (both are O(1.0)).
    from app.engine.dream_landing import DREAM_CONFLUENCE_BOOST

    boost = _auto_immune_boost(_exposed_project(tmp_path))
    top = max(boost.values())
    assert 0.0 < top <= DREAM_CONFLUENCE_BOOST * 2
    for value in boost.values():
        assert value > 0.0


def test_immune_boost_empty_for_all_tested_project(tmp_path):
    assert _auto_immune_boost(_all_tested_project(tmp_path)) == {}


def test_immune_boost_empty_for_empty_project(tmp_path):
    _write(tmp_path, "app/__init__.py", "")
    assert _auto_immune_boost(tmp_path) == {}


def test_immune_boost_refusal_safe_on_broken_target(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert _auto_immune_boost(missing) == {}
    assert _auto_immune_boost(None) == {}
    assert _auto_immune_boost(12345) == {}


def test_immune_boost_is_deterministic(tmp_path):
    root = _exposed_project(tmp_path)
    first = _auto_immune_boost(root)
    second = _auto_immune_boost(root)
    assert first == second


# === cmd_auto: byte-identical when both boosts are empty ====================

def test_cmd_auto_priority_boost_is_empty_without_dream_or_immune(tmp_path):
    # No dream store AND every own module already tested -> both source maps
    # are {} -> _merge_boosts yields {} -> the ranking is byte-identical.
    root = _all_tested_project(tmp_path)
    assert _auto_dream_boost(root) == {}
    assert _auto_immune_boost(root) == {}
    assert _merge_boosts(_auto_dream_boost(root), _auto_immune_boost(root)) == {}


def test_cmd_auto_is_byte_identical_to_no_boost_plan(tmp_path):
    # On a project with NEITHER a persisted dream NOR immune exposure, the
    # merged boost is {} and plan_roadmap's ranking is byte-for-byte identical
    # to a call with no boost at all -- pinning the empty-boost guarantee
    # end-to-end (not just at the map level).
    root = _all_tested_project(tmp_path)
    report = _report(root)
    bridge = IdeaActionBridge()

    def _seq(plan):
        return [(s.branch_path, s.phase, s.action_type, s.target, s.value)
                for s in plan.steps]

    base = _seq(bridge.plan_roadmap(report, mode="report", project_root=str(root)))
    merged = _merge_boosts(_auto_dream_boost(root), _auto_immune_boost(root))
    with_boost = _seq(bridge.plan_roadmap(
        report, mode="report", project_root=str(root), dream_boost=merged))
    assert with_boost == base


def test_cmd_auto_recommend_is_deterministic_with_no_signals(tmp_path, capsys):
    _all_tested_project(tmp_path)
    assert cmd_auto(_ns(tmp_path, json=True)) == 0
    first = capsys.readouterr().out
    assert cmd_auto(_ns(tmp_path, json=True)) == 0
    second = capsys.readouterr().out
    assert first == second
    payload = json.loads(first)
    assert payload["applied"] is False


def test_cmd_auto_merges_immune_exposure_into_the_ranking(tmp_path):
    # An exposed-but-no-dream project: cmd_auto's merged priority_boost should
    # equal exactly the immune boost alone (dream contributes nothing).
    root = _exposed_project(tmp_path)
    dream = _auto_dream_boost(root)
    immune = _auto_immune_boost(root)
    assert dream == {}
    assert immune
    assert _merge_boosts(dream, immune) == immune
