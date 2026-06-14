"""The `apex objectives` subcommand: the develop catalog and which objectives
the idea engine can actually reach (a value in FACET_OBJECTIVE_MAP).

Structural assertions only — the exact reachable count moves as the map grows,
so we compute the expectation from the live registries, never hard-code it.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json

from app.cli_insight import cmd_objectives
from app.engine.facet_develop import FACET_OBJECTIVE_MAP
from app.engine.objective_compiler import available_objectives


def _run(**kwargs) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_objectives(argparse.Namespace(**kwargs))
    return rc, buf.getvalue()


def _expected_reachable() -> set[str]:
    # Computed, NOT hard-coded: mapped objectives that are actually registered.
    return set(FACET_OBJECTIVE_MAP.values()) & set(available_objectives())


def test_runs_and_returns_zero():
    rc, out = _run(json=False)
    assert rc == 0
    assert out.strip()


def test_json_runs_and_returns_zero():
    rc, _ = _run(json=True)
    assert rc == 0


def test_every_listed_objective_is_registered():
    rc, out = _run(json=True)
    assert rc == 0
    data = json.loads(out)
    registered = set(available_objectives())
    listed = {o["name"] for o in data["objectives"]}
    assert listed, "expected at least one objective"
    assert listed <= registered
    # The command lists the WHOLE catalog, nothing dropped.
    assert listed == registered


def test_reachable_set_is_map_values_intersect_registered():
    rc, out = _run(json=True)
    assert rc == 0
    data = json.loads(out)
    reported_reachable = {
        o["name"] for o in data["objectives"] if o["reachable"]
    }
    assert reported_reachable == _expected_reachable()
    assert set(data["reachable"]) == _expected_reachable()


def test_reachable_objectives_are_a_subset_of_registered():
    # An objective can only be "reachable" if it is also registered.
    rc, out = _run(json=True)
    data = json.loads(out)
    reachable = {o["name"] for o in data["objectives"] if o["reachable"]}
    assert reachable <= set(available_objectives())


def test_unreachable_is_complement_of_reachable():
    rc, out = _run(json=True)
    data = json.loads(out)
    reachable = {o["name"] for o in data["objectives"] if o["reachable"]}
    unreachable = set(data["unreachable"])
    listed = {o["name"] for o in data["objectives"]}
    assert reachable.isdisjoint(unreachable)
    assert reachable | unreachable == listed


def test_json_has_expected_keys_and_consistent_counts():
    rc, out = _run(json=True)
    data = json.loads(out)
    for key in ("objectives", "total", "reachable", "unreachable",
                "reachable_count", "unreachable_count"):
        assert key in data, f"missing key: {key}"
    assert data["total"] == len(data["objectives"])
    assert data["reachable_count"] == len(data["reachable"])
    assert data["unreachable_count"] == len(data["unreachable"])
    assert data["reachable_count"] + data["unreachable_count"] == data["total"]


def test_deterministic_ordering_alphabetical():
    rc, out = _run(json=True)
    data = json.loads(out)
    names = [o["name"] for o in data["objectives"]]
    assert names == sorted(names)
    # Same input -> same output, byte for byte.
    _, out2 = _run(json=True)
    assert out == out2


def test_text_table_has_summary_line():
    rc, out = _run(json=False)
    expected = _expected_reachable()
    total = len(set(available_objectives()))
    summary = (f"{total} objectives, {len(expected)} reachable from the idea "
               f"engine, {total - len(expected)} not yet wired")
    assert summary in out
    assert "REACHABLE" in out
    assert "unreachable" in out


def test_text_lists_every_registered_objective():
    rc, out = _run(json=False)
    for name in available_objectives():
        assert name in out


def test_registered_via_parser():
    # The subcommand is wired into the insight family's parser table.
    import app.cli_insight as cli_insight

    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    cli_insight.register_parsers(sub)
    assert "objectives" in sub.choices
    assert sub.choices["objectives"].get_default("func") is cmd_objectives
