"""Additional branch / edge coverage for app.engine.idea_roadmap.

Closes the gaps the existing roadmap suites leave open:

  - ``estimate_impact``: a ``theme:`` fact whose text has no ``(N modules)``
    parenthetical (the regex misses, so the module-span boost is skipped).
  - ``_outcome_adjustment``: every arm — empty rates (no-op), a sub-threshold
    sample count (ignored), a perfect/abysmal landing rate (positive/negative
    nudge), exactly 0.5 (neutral), the root-node ``_first_label`` key path, and
    the unknown-key path.

All inputs are constructed explicitly (small IdeaNode instances and plain
dicts); no time, randomness, or order-dependent assertions.
"""

from __future__ import annotations

from app.engine.idea_roadmap import (
    _OUTCOME_MAX_ADJUST,
    _outcome_adjustment,
    estimate_impact,
)
from app.models.idea import IdeaNode


def _node(**kw) -> IdeaNode:
    # Mirror the existing roadmap fixtures: realistic sub-1.0 structural axes so
    # the impact seed isn't saturated by the model defaults.
    base = dict(id="i", title="t", subject="s", relevance=0.5, novelty=0.5,
                value=0.6, feasibility=0.6, depth=1)
    base.update(kw)
    return IdeaNode(**base)


# --- estimate_impact: theme fact without a (N modules) span -------------------

def test_theme_fact_without_module_count_skips_span_boost():
    # The theme branch runs (a "theme:" fact is present) but the
    # `(N modules)` regex finds no match, so the module-span boost is skipped
    # (the 189->191 branch falls through). Impact must match a node carrying no
    # theme fact at all.
    themed = _node(source_facts=["theme: systemic cleanup with no count"])
    plain = _node(source_facts=["entrypoint: app/cli.py"])
    assert estimate_impact(themed) == estimate_impact(plain)


def test_theme_fact_with_module_count_adds_span_boost():
    # Control: the same theme label WITH a parenthetical count earns the boost,
    # confirming the no-count case above is genuinely the missed-regex arm.
    with_count = _node(source_facts=["theme: systemic cleanup (5 modules)"])
    without = _node(source_facts=["theme: systemic cleanup with no count"])
    assert estimate_impact(with_count) > estimate_impact(without)


# --- _outcome_adjustment: every arm ------------------------------------------

def test_outcome_adjustment_empty_rates_is_noop():
    # No memory -> rates is {} -> a true no-op, returns 0.0.
    assert _outcome_adjustment(_node(operator="harden"), {}) == 0.0


def test_outcome_adjustment_below_min_samples_is_ignored():
    # An entry below _OUTCOME_MIN_SAMPLES (3) is ignored entirely so a fluke
    # can't move the ranking.
    rates = {"harden": {"success_rate": 1.0, "samples": 2}}
    assert _outcome_adjustment(_node(operator="harden"), rates) == 0.0


def test_outcome_adjustment_missing_key_is_ignored():
    # The dominant key isn't in the map -> no opinion -> 0.0.
    rates = {"simplify": {"success_rate": 1.0, "samples": 9}}
    assert _outcome_adjustment(_node(operator="harden"), rates) == 0.0


def test_outcome_adjustment_high_landing_rate_boosts():
    # A perfect landing rate (1.0) with enough samples yields the full positive
    # nudge: (1.0 - 0.5) * 2 * MAX == +MAX.
    rates = {"harden": {"success_rate": 1.0, "samples": 5}}
    assert _outcome_adjustment(_node(operator="harden"), rates) == round(_OUTCOME_MAX_ADJUST, 4)


def test_outcome_adjustment_low_landing_rate_penalizes():
    # An abysmal landing rate (0.0) yields the full negative nudge: -MAX.
    rates = {"harden": {"success_rate": 0.0, "samples": 5}}
    assert _outcome_adjustment(_node(operator="harden"), rates) == round(-_OUTCOME_MAX_ADJUST, 4)


def test_outcome_adjustment_neutral_landing_rate_is_zero():
    # Exactly 0.5 is neutral.
    rates = {"harden": {"success_rate": 0.5, "samples": 5}}
    assert _outcome_adjustment(_node(operator="harden"), rates) == 0.0


def test_outcome_adjustment_root_node_keys_on_first_label():
    # A root idea has operator "root", so the dominant key is its seeding fact
    # label (here "untested"), not the operator.
    node = _node(operator="root", source_facts=["untested: app/m.py"])
    rates = {"untested": {"success_rate": 1.0, "samples": 4}}
    assert _outcome_adjustment(node, rates) == round(_OUTCOME_MAX_ADJUST, 4)
