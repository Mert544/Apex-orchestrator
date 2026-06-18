"""Counterfactual learning — learning failure signatures from rollbacks."""

from __future__ import annotations

import json

from app.engine.counterfactual_learning import (
    failure_signatures,
    module_traits,
    near_miss_insights,
    should_avoid,
)
from app.engine.proof_of_fix import SCHEMA


def _fix(action: str, outcome: str, target: str = "app/m.py") -> dict:
    return {
        "finding": {"label": "x", "action": action, "target": target},
        "outcome": outcome,
        "changed_files": [target],
    }


def _proof(fixes: list[dict]) -> dict:
    return {"schema": SCHEMA, "schema_version": "1.0",
            "generated_at": "2026-01-01T00:00:00+00:00", "fixes": fixes}


# --- module_traits ----------------------------------------------------------


def test_traits_detect_test_init_deep_entrypoint():
    assert "test" in module_traits("tests/test_foo.py")
    assert "test" in module_traits("app/sub/test_bar.py")
    assert "package-init" in module_traits("app/engine/__init__.py")
    assert "deep" in module_traits("a/b/c/d/e.py")
    assert "entrypoint" in module_traits("app/cli.py")


def test_traits_blank_is_generic():
    assert module_traits("") == {"generic"}
    assert module_traits("   ") == {"generic"}


def test_traits_plain_module_is_generic():
    assert module_traits("app/m.py") == {"generic"}


# --- failure_signatures -----------------------------------------------------


def test_signatures_from_rolled_back_records():
    # 3 attempts on a test module, all rolled back -> rate 1.0, avoid True.
    proof = _proof([
        _fix("harden_security", "rolled_back", "tests/test_a.py"),
        _fix("harden_security", "rolled_back", "tests/test_b.py"),
        _fix("harden_security", "blocked", "tests/test_c.py"),
    ])
    sigs = failure_signatures([proof])
    key = "harden_security | test"
    assert sigs[key]["attempts"] == 3
    assert sigs[key]["failures"] == 3
    assert sigs[key]["failure_rate"] == 1.0
    assert sigs[key]["avoid"] is True


def test_signatures_failure_rate_bounded_and_partial():
    proof = _proof([
        _fix("act", "applied", "app/m.py"),
        _fix("act", "rolled_back", "app/m.py"),
        _fix("act", "rolled_back", "app/m.py"),
        _fix("act", "applied", "app/m.py"),
    ])
    sigs = failure_signatures([proof])
    entry = sigs["act | generic"]
    assert entry["attempts"] == 4
    assert entry["failures"] == 2
    assert entry["failure_rate"] == 0.5
    assert 0.0 <= entry["failure_rate"] <= 1.0
    # 0.5 is below the 0.6 threshold -> not avoid.
    assert entry["avoid"] is False


def test_signatures_all_success_avoid_nothing():
    proof = _proof([_fix("act", "applied", "app/m.py") for _ in range(5)])
    sigs = failure_signatures([proof])
    entry = sigs["act | generic"]
    assert entry["failures"] == 0
    assert entry["failure_rate"] == 0.0
    assert entry["avoid"] is False


def test_signatures_high_rate_but_too_few_attempts_not_avoid():
    # 2/2 failures but below _MIN_ATTEMPTS (3) -> not yet avoid.
    proof = _proof([
        _fix("act", "rolled_back", "app/m.py"),
        _fix("act", "blocked", "app/m.py"),
    ])
    entry = failure_signatures([proof])["act | generic"]
    assert entry["failure_rate"] == 1.0
    assert entry["attempts"] == 2
    assert entry["avoid"] is False


def test_signatures_empty_history_is_empty():
    assert failure_signatures([]) == {}
    assert failure_signatures(None) == {}


def test_signatures_tolerates_malformed_rows():
    proof = {"schema": SCHEMA, "fixes": [None, 42, {"outcome": "rolled_back"}]}
    sigs = failure_signatures([proof, "not-a-proof", None])
    # The one dict fix (no action/module) buckets under unknown/generic.
    assert sigs["<unknown> | generic"]["failures"] == 1


def test_signatures_keys_sorted():
    proof = _proof([
        _fix("zeta", "rolled_back", "app/m.py"),
        _fix("alpha", "rolled_back", "app/m.py"),
    ])
    keys = list(failure_signatures([proof]).keys())
    assert keys == sorted(keys)


# --- should_avoid -----------------------------------------------------------


def _avoidable_sigs():
    proof = _proof([
        _fix("harden_security", "rolled_back", "tests/test_a.py"),
        _fix("harden_security", "rolled_back", "tests/test_b.py"),
        _fix("harden_security", "rolled_back", "tests/test_c.py"),
    ])
    return failure_signatures([proof])


def test_should_avoid_true_only_above_threshold():
    sigs = _avoidable_sigs()
    assert should_avoid(sigs, "harden_security", {"test"}) is True
    # Different trait -> no matching avoid signature.
    assert should_avoid(sigs, "harden_security", {"generic"}) is False
    # Different action -> no match.
    assert should_avoid(sigs, "create_test_stub", {"test"}) is False


def test_should_avoid_accepts_any_iterable_of_traits():
    sigs = _avoidable_sigs()
    assert should_avoid(sigs, "harden_security", ["generic", "test"]) is True
    assert should_avoid(sigs, "harden_security", ("generic",)) is False


def test_should_avoid_empty_signatures_is_false():
    assert should_avoid({}, "anything", {"test"}) is False
    assert should_avoid({}, "", set()) is False


def test_should_avoid_empty_traits_uses_generic():
    proof = _proof([_fix("act", "rolled_back", "app/m.py") for _ in range(3)])
    sigs = failure_signatures([proof])
    assert should_avoid(sigs, "act", set()) is True
    assert should_avoid(sigs, "act", None) is True


def test_should_avoid_below_threshold_signature_is_false():
    proof = _proof([
        _fix("act", "applied", "app/m.py"),
        _fix("act", "rolled_back", "app/m.py"),
        _fix("act", "applied", "app/m.py"),
    ])
    sigs = failure_signatures([proof])
    assert should_avoid(sigs, "act", {"generic"}) is False


# --- near_miss_insights -----------------------------------------------------


def test_insights_correct_text():
    insights = near_miss_insights([_proof([
        _fix("harden_security", "rolled_back", "tests/test_a.py"),
        _fix("harden_security", "rolled_back", "tests/test_b.py"),
        _fix("harden_security", "blocked", "tests/test_c.py"),
        _fix("harden_security", "rolled_back", "tests/test_d.py"),
        _fix("harden_security", "blocked", "tests/test_e.py"),
    ])])
    assert len(insights) == 1
    assert "harden_security" in insights[0]
    assert "test modules 5/5" in insights[0]
    assert "test first" in insights[0]


def test_insights_only_avoidable_signatures():
    # 2/4 failures -> below threshold -> no insight.
    insights = near_miss_insights([_proof([
        _fix("act", "applied", "app/m.py"),
        _fix("act", "rolled_back", "app/m.py"),
        _fix("act", "rolled_back", "app/m.py"),
        _fix("act", "applied", "app/m.py"),
    ])])
    assert insights == []


def test_insights_sorted_worst_first():
    proof = _proof(
        [_fix("low", "rolled_back", "app/m.py") for _ in range(3)]
        + [_fix("low", "applied", "app/m.py")]
        + [_fix("high", "rolled_back", "app/n.py") for _ in range(4)]
    )
    # low: 3/4 = 0.75 (avoid), high: 4/4 = 1.0 (avoid). high first.
    insights = near_miss_insights([proof])
    assert len(insights) == 2
    assert insights[0].startswith("action 'high'")
    assert insights[1].startswith("action 'low'")


def test_insights_empty_history():
    assert near_miss_insights([]) == []
    assert near_miss_insights(None) == []


def test_insights_all_success_is_empty():
    proof = _proof([_fix("act", "applied", "app/m.py") for _ in range(5)])
    assert near_miss_insights([proof]) == []


# --- determinism ------------------------------------------------------------


def test_determinism_same_input_same_output():
    proof = _proof([
        _fix("a", "rolled_back", "tests/test_x.py"),
        _fix("a", "blocked", "tests/test_y.py"),
        _fix("a", "rolled_back", "tests/test_z.py"),
        _fix("b", "applied", "app/m.py"),
    ])
    first = failure_signatures([proof])
    second = failure_signatures([proof])
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert near_miss_insights([proof]) == near_miss_insights([proof])
