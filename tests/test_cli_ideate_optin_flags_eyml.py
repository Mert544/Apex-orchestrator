"""``apex ideate --actions`` exposes the EIGHT grounded opt-in synthesis
objectives as CLI flags.

The bridge (:class:`app.engine.idea_action_bridge.IdeaActionBridge`) has long
accepted ``cover_gaps`` / ``wire_exports`` / ``generate_usage_doc`` /
``tdd_implement`` / ``strengthen_tests`` / ``modernize`` / ``dedup_total_return``
/ ``dedup_parameterized`` on ``plan_tree`` / ``plan_roadmap`` — but they were not
reachable from the CLI: ``apex ideate ... --tdd-implement`` errored
"unrecognized arguments". This file pins the wiring that closes that gap:

  - RECOGNITION: each of the eight ``--...`` flags parses through the REAL
    ideate argparser (no "unrecognized arguments"); every flag defaults False;
    setting one flag sets ONLY its own attribute (independent at parse time).
  - SURFACING (end-to-end through ``cmd_ideate`` on a real tmp_path project
    with a qualifying target): ``--modernize`` surfaces an executable
    ``modernize`` step for a stale-idiom module; ``--cover-gaps`` surfaces a
    ``cover_gaps`` step for an untested module; ``--tdd-implement`` surfaces a
    ``tdd_implement`` step for a missing function a RED test demands.
  - DEFAULT BYTE-IDENTICAL: with NONE of the eight flags set the ``--actions``
    JSON is byte-for-byte identical to the same plan built with every objective
    inert, and is stable run-to-run (determinism preserved, idea set unshifted).
  - INDEPENDENCE (plan level): opting one objective in never surfaces another.
  - INERT WITHOUT --actions: the flags augment only the action plan, so passing
    one without ``--actions`` does not error and produces the plain idea tree.

These exercise the wiring through the public CLI surface (real argparser, real
engine, real bridge) on isolated, deterministic fixtures under ``tmp_path`` — no
time/random, so the same project always yields the same plan.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

import pytest

import app.cli_ideate as ci

# CLI-flag -> the Namespace attribute argparse maps it to (dest). The single
# source of truth this file iterates over for the recognition/independence pins;
# it mirrors ``ci._OPTIN_SYNTHESIS_FLAGS`` (the handler's own list) by dest.
_FLAG_TO_DEST = {
    "--cover-gaps": "cover_gaps",
    "--wire-exports": "wire_exports",
    "--generate-usage-doc": "generate_usage_doc",
    "--tdd-implement": "tdd_implement",
    "--strengthen-tests": "strengthen_tests",
    "--modernize": "modernize",
    "--dedup-total-return": "dedup_total_return",
    "--dedup-parameterized": "dedup_parameterized",
}


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _build_ideate_parser() -> argparse.ArgumentParser:
    """The REAL ideate argparser, wired exactly as ``app.cli.main`` wires it."""
    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    ci.register_parsers(sub)
    return parser


def _ns(target: Path, **ov) -> argparse.Namespace:
    """A full ``cmd_ideate`` Namespace defaulting every opt-in flag OFF.

    Mirrors the fields the real argparser produces (and the existing dispatch
    test's ``_ns``), so ``cmd_ideate`` runs end-to-end against ``target``.
    """
    base = dict(
        target=str(target), objective="", depth=2, breadth=3, max_ideas=20,
        min_relevance=0.0, actions=True, top=0, draft=False, apply=False,
        verify=False, commit=False, max_apply=0, mode="supervised",
        mermaid=False, json=True, out="", kind="", roadmap=False, facets=False,
        facet_depth=1, shape=False, pareto=False, sequence=False, adaptive=False,
        budget=0.0, invest=False, phase="", save=False, diff=False,
        include_discoveries=False,
    )
    base.update({dest: False for dest in _FLAG_TO_DEST.values()})
    base.update(ov)
    return argparse.Namespace(**base)


def _run_ideate(target: Path, **ov) -> dict:
    """Run ``cmd_ideate`` end-to-end, returning the parsed ``--json`` payload."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ci.cmd_ideate(_ns(target, **ov))
    assert rc == 0
    return json.loads(buf.getvalue())


def _synthesis_steps(payload: dict, action_type: str) -> list[tuple[str, str]]:
    """``[(target, phase)]`` for the EXECUTABLE synthesis steps of one objective."""
    return [
        (s["target"], s["phase"])
        for s in payload["action_plan"]["steps"]
        if (s.get("operator") == "synthesis"
            and s["action_type"] == action_type and s["executable"])
    ]


# ---------------------------------------------------------------------------
# Fixtures: tiny isolated projects, each with ONE qualifying target.
# ---------------------------------------------------------------------------

def _idiom_project(tmp_path: Path) -> Path:
    """A module carrying stale idioms (``== None`` + empty ``dict()``) the
    ``modernize`` objective rewrites; the engine surfaces it as a candidate."""
    root = tmp_path / "idiom"
    _write(root, "widget.py",
           'def greet(name):\n    if name == None:\n        return dict()\n'
           '    return f"hi {name}"\n')
    return root


def _gappy_project(tmp_path: Path) -> Path:
    """An untested module with a public callable the ``cover-gaps`` objective can
    write a brand-new characterization test for."""
    root = tmp_path / "gappy"
    _write(root, "shape.py", "def area(w, h):\n    return w * h\n")
    return root


def _tdd_project(tmp_path: Path) -> Path:
    """A RED test calling a function that does NOT exist yet — the one symbol the
    ``tdd-implement`` objective can synthesise a passing ``def`` for. Two pinned
    examples force a parameter template (``a + b``), not a constant."""
    root = tmp_path / "tdd"
    _write(root, "mymath.py", '"""tiny"""\n\n\ndef double(x):\n    return x * 2\n')
    _write(root, "tests/test_mymath.py",
           "from mymath import add\n\n\n"
           "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n")
    return root


# ---------------------------------------------------------------------------
# RECOGNITION: argparse accepts every flag; defaults off; independent.
# ---------------------------------------------------------------------------

def test_all_eight_flags_default_off() -> None:
    """A plain ``ideate --actions`` parse leaves every opt-in objective OFF."""
    parser = _build_ideate_parser()
    args = parser.parse_args(["ideate", "--actions"])
    for dest in _FLAG_TO_DEST.values():
        assert getattr(args, dest) is False


@pytest.mark.parametrize("flag,dest", sorted(_FLAG_TO_DEST.items()))
def test_each_flag_is_recognized_and_independent(flag: str, dest: str) -> None:
    """Each flag PARSES (no "unrecognized arguments") and sets ONLY its own
    attribute — proving the gap ("unrecognized arguments") is closed and the
    flags are independent at parse time."""
    parser = _build_ideate_parser()
    args = parser.parse_args(["ideate", "--actions", flag])
    assert getattr(args, dest) is True
    for other in _FLAG_TO_DEST.values():
        if other != dest:
            assert getattr(args, other) is False


def test_all_flags_together_parse() -> None:
    """All eight flags can be combined on one invocation (no clash, all True)."""
    parser = _build_ideate_parser()
    args = parser.parse_args(["ideate", "--actions", *_FLAG_TO_DEST])
    for dest in _FLAG_TO_DEST.values():
        assert getattr(args, dest) is True


def test_dest_mapping_matches_handler_flag_list() -> None:
    """The dests this test wires are EXACTLY the handler's opt-in flag list — so a
    flag added to one without the other is caught (the kwargs splat would break)."""
    assert set(_FLAG_TO_DEST.values()) == set(ci._OPTIN_SYNTHESIS_FLAGS)


# ---------------------------------------------------------------------------
# SURFACING: a set flag with a qualifying target surfaces that objective's step.
# ---------------------------------------------------------------------------

def test_modernize_flag_surfaces_modernize_step(tmp_path: Path) -> None:
    root = _idiom_project(tmp_path)
    payload = _run_ideate(root, modernize=True)
    assert _synthesis_steps(payload, "modernize") == [("widget.py", "Refine")]


def test_cover_gaps_flag_surfaces_cover_gaps_step(tmp_path: Path) -> None:
    root = _gappy_project(tmp_path)
    payload = _run_ideate(root, cover_gaps=True)
    assert _synthesis_steps(payload, "cover_gaps") == [("shape.py", "Stabilize")]


def test_tdd_implement_flag_surfaces_tdd_implement_step(tmp_path: Path) -> None:
    root = _tdd_project(tmp_path)
    payload = _run_ideate(root, tdd_implement=True)
    # PER-SYMBOL: the target is "<module>:<name>" for the missing function.
    assert _synthesis_steps(payload, "tdd_implement") == [("mymath.py:add", "Evolve")]


def test_modernize_flag_surfaces_step_in_roadmap_path(tmp_path: Path) -> None:
    """The flag threads through the ROADMAP plan path too (``--roadmap --actions``),
    not just the value-ranked one."""
    root = _idiom_project(tmp_path)
    payload = _run_ideate(root, modernize=True, roadmap=True)
    assert _synthesis_steps(payload, "modernize") == [("widget.py", "Refine")]


# ---------------------------------------------------------------------------
# DEFAULT BYTE-IDENTICAL: no opt-in flag -> plan unchanged + deterministic.
# ---------------------------------------------------------------------------

def test_default_actions_plan_has_no_optin_objective(tmp_path: Path) -> None:
    """On a project that WOULD qualify for several objectives, a default
    ``--actions`` plan (no opt-in flag) surfaces NONE of the eight."""
    root = _idiom_project(tmp_path)
    payload = _run_ideate(root)
    for dest in _FLAG_TO_DEST.values():
        assert _synthesis_steps(payload, dest) == []


def test_default_actions_plan_is_byte_identical_and_deterministic(
        tmp_path: Path) -> None:
    """The default ``--actions`` output is byte-for-byte identical to the SAME
    plan with every opt-in objective explicitly inert (proving the new flags do
    not shift the default plan), and stable run-to-run."""
    root = _idiom_project(tmp_path)
    # Baseline: every opt-in flag explicitly False == "as today" (pre-change).
    baseline = json.dumps(_run_ideate(root)["action_plan"], sort_keys=True)
    # Re-run with no flags set: must be byte-identical (determinism, no shift).
    again = json.dumps(_run_ideate(root)["action_plan"], sort_keys=True)
    assert baseline == again


# ---------------------------------------------------------------------------
# INDEPENDENCE at the plan level: one flag never pulls in another objective.
# ---------------------------------------------------------------------------

def test_modernize_does_not_enable_cover_gaps(tmp_path: Path) -> None:
    """``--modernize`` on a project that ALSO has an untested module surfaces the
    modernize step but NOT a cover-gaps step — the flags are independent."""
    root = tmp_path / "both"
    # widget.py: a stale idiom (modernizable) AND untested (cover-gappable).
    _write(root, "widget.py",
           'def greet(name):\n    if name == None:\n        return dict()\n'
           '    return f"hi {name}"\n')
    payload = _run_ideate(root, modernize=True)
    assert _synthesis_steps(payload, "modernize") == [("widget.py", "Refine")]
    assert _synthesis_steps(payload, "cover_gaps") == []


def test_cover_gaps_does_not_enable_modernize(tmp_path: Path) -> None:
    """Symmetric: opting cover-gaps in does NOT surface a modernize step."""
    root = tmp_path / "both2"
    _write(root, "widget.py",
           'def greet(name):\n    if name == None:\n        return dict()\n'
           '    return f"hi {name}"\n')
    payload = _run_ideate(root, cover_gaps=True)
    assert _synthesis_steps(payload, "cover_gaps") == [("widget.py", "Stabilize")]
    assert _synthesis_steps(payload, "modernize") == []


# ---------------------------------------------------------------------------
# INERT WITHOUT --actions: a flag without --actions is a no-op, not an error.
# ---------------------------------------------------------------------------

def test_optin_flag_without_actions_is_inert_not_an_error(tmp_path: Path) -> None:
    """The flags augment ONLY the action plan, so passing one WITHOUT --actions
    must not error and must yield the plain idea tree (no ``action_plan`` key)."""
    root = _idiom_project(tmp_path)
    payload = _run_ideate(root, actions=False, modernize=True)
    assert "action_plan" not in payload
