from __future__ import annotations

from app.engine.idea_tree_shape import (
    _measured_loc,
)
from app.models.idea import IdeaTreeReport


def _report(ideas, stats=None) -> IdeaTreeReport:
    return IdeaTreeReport(ideas=ideas, stats=stats or {})


# ---- _measured_loc: malformed / boundary loc values --------------------------

def test_measured_loc_missing_metrics_is_empty():
    # No stats / no metrics key -> the safe ("", 0, 0) default.
    assert _measured_loc(IdeaTreeReport(ideas=[])) == ("", 0, 0)


def test_measured_loc_non_dict_metrics_is_empty():
    # A malformed metrics blob (a list, not a dict) short-circuits to default.
    r = _report([], stats={"metrics": ["not", "a", "dict"]})
    assert _measured_loc(r) == ("", 0, 0)


def test_measured_loc_malformed_loc_value_counts_as_zero():
    # A non-numeric loc raises ValueError on int() and is treated as 0 LOC, so
    # the well-formed neighbour wins the heaviest-module tie.
    r = _report([], stats={"metrics": {"a": {"loc": "notanint"}, "b": {"loc": 50}}})
    assert _measured_loc(r) == ("b", 50, 50)


def test_measured_loc_none_entry_counts_as_zero():
    # A None metric entry becomes {} and contributes no LOC (TypeError path).
    r = _report([], stats={"metrics": {"a": None, "b": {"loc": 30}}})
    assert _measured_loc(r) == ("b", 30, 30)


def test_measured_loc_negative_loc_yields_no_heaviest():
    # Only negative LOC -> best_loc never rises above 0, so no heaviest module
    # is named even though the running total is non-zero.
    r = _report([], stats={"metrics": {"a": {"loc": -5}}})
    assert _measured_loc(r) == ("", 0, -5)


def test_measured_loc_all_zero_yields_no_heaviest():
    r = _report([], stats={"metrics": {"a": {"loc": 0}, "b": {"loc": 0}}})
    assert _measured_loc(r) == ("", 0, 0)


def test_measured_loc_tiebreak_prefers_lower_path():
    # Equal LOC -> the first path in sorted order keeps the heaviest slot.
    r = _report([], stats={"metrics": {"z": {"loc": 10}, "a": {"loc": 10}}})
    assert _measured_loc(r) == ("a", 10, 20)


def test_measured_loc_is_deterministic():
    r = _report([], stats={"metrics": {"a": {"loc": 12}, "b": {"loc": 8}}})
    assert _measured_loc(r) == _measured_loc(r)
