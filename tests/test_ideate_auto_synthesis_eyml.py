"""``apex ideate --actions --auto`` AUTONOMOUSLY includes every APPLICABLE
synthesis objective — so a user need not memorize/type the eight opt-in flags.

The bridge already gates each opt-in synthesis objective behind its own flag
(``cover_gaps`` / ``wire_exports`` / ... / ``dedup_parameterized``); ``--auto``
turns ON all of them at once. Because each objective's grounding signal already
qualifies ONLY targets the real lander would actually land, "enable all" ==
"include exactly what applies to THIS project": autonomous AND honest. This file
pins that wiring through the public CLI surface and at the bridge level:

  - SURFACING: ``--auto`` (no individual flag) on a project with TWO different
    opportunities (a modernizable module AND an untested module) surfaces BOTH
    objectives' steps.
  - HONEST: ``--auto`` on a project with only ONE kind of opportunity surfaces
    ONLY that kind — the grounding signal still filters, so non-applicable
    objectives never appear.
  - DEFAULT BYTE-IDENTICAL: with NO ``--auto`` (and no individual flag) the
    ``--actions`` JSON is byte-for-byte identical to the same plan run again, so
    the new mode does not shift the default plan; ``--auto`` is recognized and
    defaults OFF.
  - IDEMPOTENT UNION: ``--auto`` plus an explicit flag is still just "all" —
    byte-identical to ``--auto`` alone.
  - BRIDGE LEVEL: ``_enabled_objectives(..., auto=True)`` returns the default
    objectives plus EVERY opt-in row (data-driven over the table, so a future
    opt-in is auto-covered).

All fixtures are tiny isolated ``tmp_path`` projects with no time/random, so the
same project always yields the same plan (determinism preserved).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

import app.cli_ideate as ci
from app.engine.idea_action_bridge import IdeaActionBridge


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
    """A full ``cmd_ideate`` Namespace defaulting every opt-in flag + ``auto`` OFF.

    Mirrors the fields the real argparser produces, so ``cmd_ideate`` runs
    end-to-end against ``target``.
    """
    base = dict(
        target=str(target), objective="", depth=2, breadth=3, max_ideas=20,
        min_relevance=0.0, actions=True, top=0, draft=False, apply=False,
        verify=False, commit=False, max_apply=0, mode="supervised",
        mermaid=False, json=True, out="", kind="", roadmap=False, facets=False,
        facet_depth=1, shape=False, pareto=False, sequence=False, adaptive=False,
        budget=0.0, invest=False, phase="", save=False, diff=False,
        include_discoveries=False, auto=False,
    )
    base.update({name: False for name in ci._OPTIN_SYNTHESIS_FLAGS})
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
# Fixtures: tiny isolated projects.
# ---------------------------------------------------------------------------

def _idiom_project(tmp_path: Path) -> Path:
    """A module carrying stale idioms (``== None`` + empty ``dict()``) the
    ``modernize`` objective rewrites."""
    root = tmp_path / "idiom"
    _write(root, "widget.py",
           'def greet(name):\n    if name == None:\n        return dict()\n'
           '    return f"hi {name}"\n')
    return root


def _two_opportunity_project(tmp_path: Path, name: str = "two") -> Path:
    """TWO distinct opportunities in one project: a modernizable module (stale
    idioms) AND a SEPARATE untested module with a public callable (cover-gaps).

    Kept in two different modules so the two objectives target two different
    files — proving ``--auto`` surfaces BOTH, not just one. ``name`` lets a
    caller build several INDEPENDENT copies (the cover-gaps signal runs the
    suite, writing ``.pytest_cache`` into the tree; a fresh copy per invocation
    keeps two compared plans seeing the SAME clean filesystem)."""
    root = tmp_path / name
    # Modernizable: stale idioms, but already tested (so cover-gaps won't fire).
    _write(root, "stale.py",
           'def greet(name):\n    if name == None:\n        return dict()\n'
           '    return f"hi {name}"\n')
    _write(root, "tests/test_stale.py",
           "from stale import greet\n\n\ndef test_greet():\n"
           "    assert greet('x') == 'hi x'\n")
    # Cover-gappable: untested public callable, idiomatic (so modernize won't fire).
    _write(root, "plain.py", "def area(w, h):\n    return w * h\n")
    return root


def _gappy_only_project(tmp_path: Path) -> Path:
    """ONLY a cover-gaps opportunity: an untested module with a public callable,
    written idiomatically so NO modernize (or other) objective qualifies."""
    root = tmp_path / "gappy"
    _write(root, "shape.py", "def area(w, h):\n    return w * h\n")
    return root


# ---------------------------------------------------------------------------
# RECOGNITION: --auto parses and defaults off.
# ---------------------------------------------------------------------------

def test_auto_flag_recognized_and_defaults_off() -> None:
    """``--auto`` PARSES through the real argparser, defaults False, and a plain
    ``--actions`` parse leaves it off (so the default plan is unchanged)."""
    parser = _build_ideate_parser()
    default = parser.parse_args(["ideate", "--actions"])
    assert default.auto is False
    enabled = parser.parse_args(["ideate", "--actions", "--auto"])
    assert enabled.auto is True
    # --auto sets ONLY auto, not any individual opt-in flag (the union happens
    # in the bridge, not at parse time).
    for name in ci._OPTIN_SYNTHESIS_FLAGS:
        assert getattr(enabled, name) is False


# ---------------------------------------------------------------------------
# SURFACING: --auto includes EVERY applicable objective at once.
# ---------------------------------------------------------------------------

def test_auto_surfaces_both_applicable_objectives(tmp_path: Path) -> None:
    """``--auto`` (no individual flag) on a project with TWO opportunities — a
    modernizable module AND a separate cover-gaps-able module — surfaces BOTH
    objectives' steps, so a user need not name either flag."""
    root = _two_opportunity_project(tmp_path)
    payload = _run_ideate(root, auto=True)
    assert _synthesis_steps(payload, "modernize") == [("stale.py", "Refine")]
    assert _synthesis_steps(payload, "cover_gaps") == [("plain.py", "Stabilize")]


def test_auto_matches_naming_both_flags(tmp_path: Path) -> None:
    """``--auto`` is EQUIVALENT to passing every flag by name: the plan under
    ``--auto`` matches the same plan with all eight opt-in flags set explicitly.

    (``--auto`` == "all flags", not "the two I'd guess apply" — objectives can
    interact within one run, e.g. cover-gaps writes a test that strengthen-tests
    then qualifies; the grounding still filters, so only what applies lands.)"""
    # Independent copies: the cover-gaps signal runs the suite (writing
    # .pytest_cache into the tree), so each invocation gets its own clean copy.
    auto = _run_ideate(_two_opportunity_project(tmp_path, "auto"),
                       auto=True)["action_plan"]
    all_named = _run_ideate(_two_opportunity_project(tmp_path, "named"),
                            **{n: True for n in ci._OPTIN_SYNTHESIS_FLAGS}
                            )["action_plan"]
    # Project-root paths differ by design; compare the plan content.
    assert auto["steps"] == all_named["steps"]
    assert auto["stats"] == all_named["stats"]


def test_auto_surfaces_objective_in_roadmap_path(tmp_path: Path) -> None:
    """``--auto`` threads through the ROADMAP plan path too (``--roadmap
    --actions --auto``), not just the value-ranked one."""
    root = _two_opportunity_project(tmp_path)
    payload = _run_ideate(root, auto=True, roadmap=True)
    assert _synthesis_steps(payload, "modernize") == [("stale.py", "Refine")]
    assert _synthesis_steps(payload, "cover_gaps") == [("plain.py", "Stabilize")]


# ---------------------------------------------------------------------------
# HONEST: --auto does NOT force objectives that do not apply.
# ---------------------------------------------------------------------------

def test_auto_is_honest_only_applicable_surfaces(tmp_path: Path) -> None:
    """On a project whose ONLY opportunity is cover-gaps, ``--auto`` surfaces the
    cover-gaps step and NONE of the other seven objectives — the grounding signal
    still filters to qualifying targets, so ``--auto`` stays honest."""
    root = _gappy_only_project(tmp_path)
    payload = _run_ideate(root, auto=True)
    assert _synthesis_steps(payload, "cover_gaps") == [("shape.py", "Stabilize")]
    for name in ci._OPTIN_SYNTHESIS_FLAGS:
        if name != "cover_gaps":
            assert _synthesis_steps(payload, name) == []


# ---------------------------------------------------------------------------
# DEFAULT BYTE-IDENTICAL: no --auto -> plan unchanged + deterministic.
# ---------------------------------------------------------------------------

def test_default_no_auto_is_byte_identical_and_deterministic(
        tmp_path: Path) -> None:
    """With NO ``--auto`` (and no individual flag) the ``--actions`` output is
    byte-for-byte identical run-to-run, and surfaces NONE of the eight opt-in
    objectives — proving the new mode does not shift the default plan."""
    # Independent copies so neither default run's engine side effects perturb
    # the other; the default plan writes no synthesis patch, so it is stable.
    baseline = _run_ideate(_two_opportunity_project(tmp_path, "d1"))["action_plan"]
    again = _run_ideate(_two_opportunity_project(tmp_path, "d2"))["action_plan"]
    assert baseline["steps"] == again["steps"]
    assert baseline["stats"] == again["stats"]
    for name in ci._OPTIN_SYNTHESIS_FLAGS:
        assert _synthesis_steps({"action_plan": baseline}, name) == []


# ---------------------------------------------------------------------------
# IDEMPOTENT UNION: --auto + an explicit flag is still just "all".
# ---------------------------------------------------------------------------

def test_auto_plus_explicit_flag_is_idempotent(tmp_path: Path) -> None:
    """``--auto`` plus an explicit flag (already covered by ``--auto``) is still
    just "all": byte-identical to ``--auto`` alone (idempotent union)."""
    # Independent copies (the cover-gaps signal runs the suite, writing
    # .pytest_cache); compare the plan content (project_root differs by design).
    auto = _run_ideate(_two_opportunity_project(tmp_path, "a"),
                       auto=True)["action_plan"]
    auto_plus = _run_ideate(_two_opportunity_project(tmp_path, "b"),
                            auto=True, modernize=True)["action_plan"]
    assert auto["steps"] == auto_plus["steps"]
    assert auto["stats"] == auto_plus["stats"]


# ---------------------------------------------------------------------------
# BRIDGE LEVEL: _enabled_objectives(..., auto=True) returns ALL opt-in rows.
# ---------------------------------------------------------------------------

def test_enabled_objectives_auto_returns_all_optin_rows() -> None:
    """``_enabled_objectives(auto=True)`` returns the default objectives PLUS
    every row in ``_OPTIN_SYNTHESIS_OBJECTIVES`` (data-driven over the table, so a
    future opt-in is auto-covered) — i.e. exactly what passing every flag yields."""
    bridge = IdeaActionBridge
    auto_objectives = bridge._enabled_objectives(
        False, False, auto=True)
    # Every opt-in row is present.
    for rows in bridge._OPTIN_SYNTHESIS_OBJECTIVES.values():
        for row in rows:
            assert row in auto_objectives
    # The defaults are still there, first.
    assert auto_objectives[:len(bridge._SYNTHESIS_OBJECTIVES)] == \
        bridge._SYNTHESIS_OBJECTIVES
    # auto == passing every individual flag True.
    all_flags = bridge._enabled_objectives(
        True, True, True, True, True, True, True, True)
    assert auto_objectives == all_flags


def test_enabled_objectives_auto_false_is_defaults_only() -> None:
    """With ``auto`` False and every flag False, ``_enabled_objectives`` is
    EXACTLY the default objectives — the default plan never shifts."""
    objectives = IdeaActionBridge._enabled_objectives(False, False)
    assert objectives == IdeaActionBridge._SYNTHESIS_OBJECTIVES
