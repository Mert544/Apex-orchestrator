"""DISCOVERY-WIRING fix: ``cover-gaps`` (and its Tier-1 landable siblings) reach
the daily ``apex ideate`` / ``apex auto`` entry points.

The ``cover-gaps`` objective already lands real characterization tests for
untested modules — grounded in the honest lander gate
:func:`app.engine.idea_synthesis_signals.cover_gaps_modules` — and the idea
engine has long known how to surface it as a top-ranked, buyer-framed idea root
(``IdeaSeeder._seed_landable_opportunities``, gated on the existing
``landability_aware``/``landability_deep`` engine switches). But neither switch
was ever threaded from a CLI flag on ``apex ideate`` or ``apex auto``, so a
user running the DAILY entry points could never discover it as an idea (only as
a buried, zero-value ``x.syn.cover_gaps.*`` action-plan row reachable via the
separate ``--actions --cover-gaps`` opt-in, or invisibly inside ``apex dream`` /
``apex brief``). This file pins the wiring that closes that gap:

  - ``apex ideate --landable`` threads ``landability_aware=True,
    landability_deep=True`` into the engine, so an untested-but-coverable
    module surfaces a top-ranked ``::landable-cover-gaps`` idea root with a
    buyer-framed title ("a characterization safety net Apex can land").
  - Without ``--landable`` (the default), the idea tree is BYTE-IDENTICAL to
    before this wiring — additive, refusal-safe, no shift to existing users.
  - ``apex auto --deep`` — which ALREADY means "weigh the expensive synthesis
    objectives (cover-gaps, tdd-implement, ...)" for the action plan — now ALSO
    threads the same two switches into the idea-tree ranking config, so the
    recommend narrative (headline / quick wins) that `--deep` promises to
    include is consistent top-to-bottom. Without ``--deep``, byte-identical.
  - Nothing is invented: this reuses the EXISTING, already-tested
    ``cover_gaps_modules`` signal and ``_seed_landable_opportunities`` family
    verbatim — only the CLI-flag -> engine-config last mile is new.

All fixtures are tiny isolated ``tmp_path`` projects with no time/random, so the
same project always yields the same tree (determinism preserved).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

import app.cli_autonomy as ca
import app.cli_ideate as ci


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _gappy_project(tmp_path: Path) -> Path:
    """A small, untested-but-coverable module: no linked test, a plain pure
    function ``plan_cover_gaps`` (the real lander) can honestly characterize."""
    root = tmp_path / "gappy"
    _write(root, "shape.py", "def area(w, h):\n    return w * h\n")
    return root


# --------------------------------------------------------------------------- #
# apex ideate --landable                                                      #
# --------------------------------------------------------------------------- #

def _build_ideate_parser() -> argparse.ArgumentParser:
    """The REAL ideate argparser, wired exactly as ``app.cli.main`` wires it."""
    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    ci.register_parsers(sub)
    return parser


def _run_ideate_json(target: Path, *extra: str) -> dict:
    """Run ``cmd_ideate`` end-to-end through the REAL parser; return the
    parsed ``--json`` payload."""
    parser = _build_ideate_parser()
    args = parser.parse_args(
        ["ideate", "--target", str(target), "--json", *extra])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ci.cmd_ideate(args)
    assert rc == 0
    return json.loads(buf.getvalue())


def _landable_ideas(payload: dict) -> list[dict]:
    return [i for i in payload["ideas"] if "::landable-" in i["subject"]]


def test_landable_flag_is_recognized_and_defaults_off() -> None:
    parser = _build_ideate_parser()
    args = parser.parse_args(["ideate"])
    assert args.landable is False
    args_on = parser.parse_args(["ideate", "--landable"])
    assert args_on.landable is True


def test_ideate_default_surfaces_no_landable_cover_gaps_root(
        tmp_path: Path) -> None:
    """Without ``--landable`` an untested-but-coverable module never earns the
    buyer-framed ``::landable-cover-gaps`` root — the historical gap."""
    root = _gappy_project(tmp_path)
    payload = _run_ideate_json(root)
    assert _landable_ideas(payload) == []


def test_ideate_landable_flag_surfaces_cover_gaps_idea_root(
        tmp_path: Path) -> None:
    """``--landable`` surfaces "Cover the untested module shape.py" as a
    top-ranked idea root, grounded in the real ``cover_gaps_modules`` signal —
    reachable WITHOUT ``--actions`` (an idea, not just a buried action step)."""
    root = _gappy_project(tmp_path)
    payload = _run_ideate_json(root, "--landable")
    landables = _landable_ideas(payload)
    assert any(i["subject"] == "shape.py::landable-cover-gaps"
              for i in landables)
    cg = next(i for i in landables
             if i["subject"] == "shape.py::landable-cover-gaps")
    assert cg["kind"] == "permutation"
    assert "cover" in cg["title"].lower()
    assert "shape.py" in cg["title"]
    # A genuinely top-ranked root, not a value-0 afterthought.
    assert cg["value"] > 0.5


def test_ideate_landable_flag_off_is_byte_identical_default(
        tmp_path: Path) -> None:
    """``--landable`` OFF (the default) produces the exact idea tree the CLI
    produced before this wiring — additive, refusal-safe."""
    root = _gappy_project(tmp_path)
    plain = _run_ideate_json(root)
    explicit_off = _run_ideate_json(root)  # re-run, no flag either time
    assert plain == explicit_off


def test_ideate_landable_flag_reaches_via_actions_plan_too(
        tmp_path: Path) -> None:
    """The new idea root is a REAL root: it also flows into ``--actions`` (the
    ``synthesis`` operator route the seeder documents), proving it is not a
    dead-end recommend-only label."""
    root = _gappy_project(tmp_path)
    payload = _run_ideate_json(root, "--landable", "--actions")
    assert "action_plan" in payload
    landable_steps = [
        s for s in payload["action_plan"]["steps"]
        if "shape.py" in s["target"] and s["action_type"] in
        ("test", "extend", "harden", "simplify", "cover_gaps")
    ]
    assert landable_steps


# --------------------------------------------------------------------------- #
# apex auto --deep                                                            #
# --------------------------------------------------------------------------- #

def _build_auto_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    ca.register_parsers(sub)
    return parser


def _run_auto(target: Path, *extra: str) -> tuple[int, str]:
    parser = _build_auto_parser()
    args = parser.parse_args(["auto", "--target", str(target), *extra])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ca.cmd_auto(args)
    return rc, buf.getvalue()


def test_auto_deep_flag_default_off() -> None:
    parser = _build_auto_parser()
    args = parser.parse_args(["auto"])
    assert args.deep is False


def test_auto_deep_widens_the_module_count_with_a_coverable_module(
        tmp_path: Path) -> None:
    """``apex auto --recommend`` (no changes) on an untested-but-coverable
    module: with ``--deep`` the state headline counts one MORE distinct module
    than without it — the new landable-cover-gaps root joining the tree. Both
    runs are read-only (``--recommend``), so nothing is written either way."""
    root = _gappy_project(tmp_path)
    rc_shallow, out_shallow = _run_auto(root, "--recommend")
    rc_deep, out_deep = _run_auto(root, "--recommend", "--deep")
    assert rc_shallow == 0 and rc_deep == 0

    def _module_count(out: str) -> int:
        line = next(ln for ln in out.splitlines() if ln.startswith("**State:**"))
        # "**State:** N development ideas across M modules · ..."
        return int(line.split("across ")[1].split(" modules")[0])

    assert _module_count(out_deep) > _module_count(out_shallow)


def test_auto_deep_recommend_never_writes(tmp_path: Path) -> None:
    """``apex auto --recommend --deep`` stays read-only: the source file is
    untouched and no test file is written for it."""
    root = _gappy_project(tmp_path)
    before = (root / "shape.py").read_text(encoding="utf-8")
    rc, _ = _run_auto(root, "--recommend", "--deep")
    assert rc == 0
    assert (root / "shape.py").read_text(encoding="utf-8") == before
    assert not (root / "tests").exists()
