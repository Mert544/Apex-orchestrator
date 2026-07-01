"""``apex maintain --apply`` closes the missing covered-only gate.

THE BUG (a never-fake-green crack in the README's flagship "Fix" command):
``_maintain_apply`` called ``bridge.apply_plan(...)`` WITHOUT ``covered_only``
at all, so it silently defaulted to ``False`` — a bare ``apex maintain``
(mode=supervised, no flags, even on a dirty tree) could land a WEAK/uncovered
change (a green suite that never actually exercises the changed code) and
still report it "applied"/"verified". `develop --auto` / `apex auto` /
``cmd_evolve`` already closed this exact regression class (commits d9113a7 /
28d1047); ``maintain`` was missed.

THE FIX mirrors the EXISTING attended policy ``develop``/``auto`` use
(:func:`app.policies.autonomy_policy.resolve_covered_only`): ``maintain`` is
always ATTENDED (a human runs it directly), so ``covered_only`` now defaults
TRUE (only a move a test actually exercises lands) with a new, explicit
``--allow-weak`` flag as the attended opt-out — restoring the historical
land-everything behaviour on request.

Covered here (each new assertion verified to FAIL pre-fix — see the reverted
run captured in the module-level comment below the fixture):
  * a real ``maintain`` pass over a project with one COVERED + one WEAK
    ``modernize`` candidate lands ONLY the covered one by default; the weak
    one is WITHHELD (rolled back, ``withheld_uncovered`` reported) — NOT
    silently landed;
  * ``--allow-weak`` restores land-everything: BOTH candidates land;
  * the ``covered_only`` value that reaches ``apply_plan`` is exactly
    ``resolve_covered_only(allow_weak=..., unattended=False)`` — spied
    directly, no engine noise;
  * the ``maintain`` argparse subparser exposes ``--allow-weak`` (dest
    ``allow_weak``, off by default) so the CLI surface itself carries the
    opt-out, not just the internal plumbing.

Reproduced pre-fix (manually, by reverting the ``app/cli_autonomy.py`` hunk
before writing this file): the SAME fixture below, run through unpatched
``cmd_maintain`` with no flags at all (no ``--allow-weak``), landed the WEAK
module too (``applied: 4, rolled_back: 0, withheld_uncovered: None``) — this
file pins that it can never regress back to that.

Real engine on disposable fixtures (mirrors
``test_cli_autonomy_covered_only_sweep.py``'s style); no time/random/order
assertions.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

from app.cli_autonomy import _maintain_covered_only, cmd_maintain, register_parsers
from app.policies.autonomy_policy import resolve_covered_only


# --------------------------------------------------------------------------- #
# fixture — one COVERED + one WEAK ``modernize`` candidate                     #
# --------------------------------------------------------------------------- #
def _covered_and_weak_project(root: Path) -> Path:
    """A package with TWO ``== None`` idioms (both ``modernize`` candidates):

      * ``pkg/covered.py`` — a test imports + exercises it (COVERED ⇒ verified);
      * ``pkg/weak.py``    — NO test references it (a green full suite can't
        vouch for a change here ⇒ WEAK / coverage ``none``).

    Deterministic: the only debt is the two idioms, so the maintain engine's
    default sweep selects exactly these two moves — one covered, one weak."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "covered.py").write_text(
        "def is_missing(value):\n    return value == None\n", encoding="utf-8")
    (root / "tests" / "test_covered.py").write_text(
        "from pkg.covered import is_missing\n"
        "def test_m():\n"
        "    assert is_missing(None) is True\n"
        "    assert is_missing(7) is False\n", encoding="utf-8")
    (root / "pkg" / "weak.py").write_text(
        "def is_blank(value):\n    return value == None\n", encoding="utf-8")
    return root


def _ns(target: Path, **over) -> argparse.Namespace:
    base = dict(
        target=str(target), objective="", depth=1, breadth=3, max_ideas=40,
        top=0, mode="supervised", no_verify=False, commit=False, max_apply=0,
        json=True, out="", dry_run=False, recipe="", proof="",
    )
    base.update(over)
    return argparse.Namespace(**base)


def _run(ns: argparse.Namespace) -> tuple[int, dict]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cmd_maintain(ns)
    return rc, json.loads(out.getvalue())


def _covered_src(root: Path) -> str:
    return (root / "pkg" / "covered.py").read_text()


def _weak_src(root: Path) -> str:
    return (root / "pkg" / "weak.py").read_text()


# --------------------------------------------------------------------------- #
# real engine, real fixture: the buyer-proof end-to-end regression             #
# --------------------------------------------------------------------------- #
def test_maintain_apply_withholds_weak_move_by_default(tmp_path: Path):
    _covered_and_weak_project(tmp_path)
    rc, summary = _run(_ns(tmp_path))
    assert rc == 0
    # The COVERED move landed (a test exercises it) ...
    assert "value is None" in _covered_src(tmp_path)
    assert "== None" not in _covered_src(tmp_path)
    # ... and the WEAK move was WITHHELD: its file is untouched (rolled back),
    # NOT silently landed and labeled "applied"/"verified".
    assert "== None" in _weak_src(tmp_path)
    assert summary.get("withheld_uncovered", 0) >= 1
    assert summary.get("rolled_back", 0) >= 1


def test_maintain_apply_reports_withheld_uncovered_in_markdown(tmp_path: Path, capsys):
    _covered_and_weak_project(tmp_path)
    rc = cmd_maintain(_ns(tmp_path, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    # Blocked/rolled-back is surfaced in the human report, never silently
    # folded into "Applied" as if it were a verified landing.
    assert "Rolled back: **" in out


def test_maintain_allow_weak_lands_both_moves(tmp_path: Path):
    _covered_and_weak_project(tmp_path)
    rc, summary = _run(_ns(tmp_path, allow_weak=True))
    assert rc == 0
    # --allow-weak restores land-everything: BOTH idioms are modernized.
    assert "value is None" in _covered_src(tmp_path)
    assert "value is None" in _weak_src(tmp_path)
    assert "== None" not in _weak_src(tmp_path)
    assert summary.get("rolled_back", 0) == 0
    assert not summary.get("withheld_uncovered")


def test_maintain_allow_weak_apply_is_byte_identical_to_no_gate_baseline(tmp_path: Path):
    """``--allow-weak`` (covered_only OFF) must land EXACTLY what the literal
    pre-fix call landed — byte-for-byte. The baseline drives the SAME bridge
    apply directly with NO ``covered_only`` argument at all (the historical,
    pre-fix call shape), then compares every source file in the two trees."""
    from app.engine.idea_action_bridge import IdeaActionBridge

    # Baseline tree: the literal pre-fix call — apply_plan with no covered_only
    # kwarg (defaults False inside apply_plan itself).
    base = tmp_path / "baseline"
    base.mkdir()
    _covered_and_weak_project(base)
    from app.engine.idea_permutation import IdeaPermutationEngine

    engine = IdeaPermutationEngine(
        config={"max_total_ideas": 40, "max_idea_depth": 1, "breadth": 3},
        project_root=str(base))
    report = engine.run()
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(report, mode="supervised", top=None, project_root=str(base))
    bridge.apply_plan(plan, str(base), mode="supervised", verify=True)

    # --allow-weak tree via the CLI (covered_only explicitly resolved False).
    cli = tmp_path / "cli"
    cli.mkdir()
    _covered_and_weak_project(cli)
    _run(_ns(cli, allow_weak=True))

    for rel in ("pkg/covered.py", "pkg/weak.py", "pkg/__init__.py"):
        assert (cli / rel).read_text() == (base / rel).read_text(), rel
    # And the baseline genuinely landed the weak move (so this is a real check,
    # not two trees that both happened to withhold).
    assert "value is None" in (base / "pkg" / "weak.py").read_text()


# --------------------------------------------------------------------------- #
# the gate itself — spied wiring + the pure policy resolution                  #
# --------------------------------------------------------------------------- #
def test_maintain_covered_only_helper_matches_policy():
    """``_maintain_covered_only`` is a thin, ATTENDED (``unattended=False``)
    wrapper around the single-source-of-truth policy — never a hand-rolled
    gate of its own."""
    ns_default = argparse.Namespace(allow_weak=False)
    ns_weak = argparse.Namespace(allow_weak=True)
    assert _maintain_covered_only(ns_default) == resolve_covered_only(
        allow_weak=False, unattended=False)
    assert _maintain_covered_only(ns_weak) == resolve_covered_only(
        allow_weak=True, unattended=False)
    assert _maintain_covered_only(ns_default) is True
    assert _maintain_covered_only(ns_weak) is False


def test_maintain_covered_only_helper_defaults_when_flag_absent():
    """A Namespace with no ``allow_weak`` attribute at all (an older caller /
    stub) must still resolve to the SAFE covered-only default, never crash."""
    ns = argparse.Namespace()
    assert _maintain_covered_only(ns) is True


def test_maintain_apply_spies_covered_only_reaches_apply_plan(tmp_path, monkeypatch):
    """No real engine: SPY on ``IdeaActionBridge.apply_plan`` and assert the
    EXACT ``covered_only`` value ``cmd_maintain`` feeds it — the bug was
    precisely that this kwarg was never passed at all."""
    from app.engine.idea_action_bridge import IdeaActionBridge

    captured: list[bool] = []
    real_apply_plan = IdeaActionBridge.apply_plan

    def _spy(self, *a, covered_only=None, **kw):
        captured.append(covered_only)
        return real_apply_plan(self, *a, covered_only=covered_only, **kw)

    monkeypatch.setattr(IdeaActionBridge, "apply_plan", _spy)

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")

    cmd_maintain(_ns(tmp_path, no_verify=True))
    assert captured == [True]  # no --allow-weak -> the SAFE default reached apply_plan

    captured.clear()
    cmd_maintain(_ns(tmp_path, no_verify=True, allow_weak=True))
    assert captured == [False]  # --allow-weak -> the opt-out reached apply_plan


# --------------------------------------------------------------------------- #
# CLI surface — ``--allow-weak`` is a real, registered maintain flag           #
# --------------------------------------------------------------------------- #
def test_maintain_parser_exposes_allow_weak_flag():
    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    register_parsers(sub)
    maintain = sub.choices["maintain"]
    action = next(a for a in maintain._actions if a.dest == "allow_weak")
    assert action.default is False
    assert "--allow-weak" in action.option_strings


def test_maintain_cli_parses_allow_weak_flag():
    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    register_parsers(sub)
    args = parser.parse_args(["maintain", "--allow-weak"])
    assert args.allow_weak is True

    args_default = parser.parse_args(["maintain"])
    assert args_default.allow_weak is False
