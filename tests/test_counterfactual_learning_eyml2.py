"""Counterfactual learning — module fallback + skipped-fix exclusion (eyml2 wave).

Targets the two branches the first wave left uncovered: ``_module_of`` falling
back to the first changed file when a finding names no target, and ``_tally``
dropping a ``skipped_learned`` fix so a declined fix never feeds the failure
stats. Deterministic, offline.
"""

from __future__ import annotations

from app.engine.counterfactual_learning import (
    _module_of,
    failure_signatures,
)


def test_module_of_falls_back_to_first_changed_file():
    # Finding present but carries no target -> use the first changed file.
    fix = {"finding": {"action": "harden"}, "changed_files": ["app/x/y.py"]}
    assert _module_of(fix) == "app/x/y.py"


def test_module_of_uses_changed_files_when_no_finding():
    fix = {"changed_files": ["pkg/mod.py", "pkg/other.py"]}
    assert _module_of(fix) == "pkg/mod.py"


def test_module_of_empty_when_nothing_names_a_module():
    assert _module_of({"finding": {"action": "a"}}) == ""
    assert _module_of({"changed_files": []}) == ""


def test_skipped_learned_fix_contributes_no_evidence():
    # The skipped fix (never attempted) must not inflate attempts/failures — only
    # the rolled_back fix counts.
    history = [{"fixes": [
        {"finding": {"action": "harden", "target": "app/m.py"},
         "outcome": "skipped_learned", "changed_files": ["app/m.py"]},
        {"finding": {"action": "harden", "target": "app/m.py"},
         "outcome": "rolled_back", "changed_files": ["app/m.py"]},
    ]}]
    sigs = failure_signatures(history)
    entry = sigs["harden | generic"]
    assert entry["attempts"] == 1
    assert entry["failures"] == 1


def test_all_skipped_learned_yields_no_signatures():
    history = [{"fixes": [
        {"finding": {"action": "harden", "target": "app/m.py"},
         "outcome": "skipped_learned", "changed_files": ["app/m.py"]},
    ]}]
    assert failure_signatures(history) == {}
