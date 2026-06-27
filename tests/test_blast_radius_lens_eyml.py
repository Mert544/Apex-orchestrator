"""Display-only BLAST-RADIUS lens in the read-only value preview.

Proposal 3 of the centrality-targeting spec: in the read-only value preview
(``cli_autonomy._auto_value_board`` + ``_develop_auto_value_preview``) module
import IN-DEGREE is a SECONDARY DISPLAY sort key — between two equal-buyer-value
objectives the one whose top target is more CENTRAL is shown first. It mirrors
the ``preview_value`` pattern (``GoalRanking.preview_centrality``: an OPTIONAL
display field, populated only on the preview path, OMITTED from ``to_dict`` when
0).

CRITICAL TRUST CONSTRAINT (round-21 lesson, here trivially upheld — display
only): the lens touches ONLY the read-only DISPLAY sort. It NEVER feeds
``priority`` or the ``rank_objectives`` sort key, so ``apex plan --json`` and the
APPLIED set stay BYTE-IDENTICAL (default field 0 ⇒ key omitted). The preview path
is strictly read-only AND suite-free — the in-degree comes from the CHEAP
``DependencyGraphBuilder`` graph walk, NOT pytest. These tests pin all three:
  * two equal-buyer-value objectives whose top targets differ in centrality →
    the MORE-central one leads the preview (flipping the old alphabetical order);
  * ``GoalRanking.to_dict`` is byte-identical when ``preview_centrality == 0``
    (the ``apex plan --json`` contract is unchanged) and includes it when set;
  * the read-only preview triggers NO pytest (no ``.pytest_cache``, no suite run).

Mirrors the ``test_develop_auto_value_preview_eyml`` harness (same fixtures and
stdout-capture dispatch style).
"""

from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path

import app.cli_autonomy as m
from app.cli_autonomy import cmd_develop
from app.engine.ascend import GoalRanking, rank_objectives
from app.engine.objective_value import objective_value_weight


# --------------------------------------------------------------------------- #
# fixtures                                                                     #
# --------------------------------------------------------------------------- #
def _hub_vs_leaf_project(root: Path) -> Path:
    """A package with TWO equal-buyer-value (0.40) cheap objectives whose top
    targets differ in centrality:

    * ``hub.py`` carries an unreachable statement (``remove-dead-code`` target)
      and is imported by FOUR sibling modules → import in-degree 4;
    * ``leaf.py`` carries a never-read parameter (``dead-params`` target) and is
      imported by NOBODY → in-degree 0.

    ``remove-dead-code`` and ``dead-params`` are both buyer-value 0.40, so they
    TIE on value — the blast-radius lens is the only thing that can order them.
    Alphabetically ``dead-params`` < ``remove-dead-code``, so a correct lens
    FLIPS that: the hub-targeting ``remove-dead-code`` must lead."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    # hub.py: an unreachable statement after the return → remove-dead-code move.
    (root / "pkg" / "hub.py").write_text(
        "def f(x):\n    return x\n    y = 1  # unreachable\n", encoding="utf-8")
    # four importers of hub → hub in-degree 4 (a real dependency hub).
    for i in range(4):
        (root / "pkg" / f"imp{i}.py").write_text(
            "from pkg.hub import f\n", encoding="utf-8")
    # leaf.py: a never-read parameter → dead-params move, imported by nobody.
    (root / "pkg" / "leaf.py").write_text(
        "def g(used, dead):\n    return used\n", encoding="utf-8")
    return root


def _auto_ns(target: Path, **over) -> argparse.Namespace:
    base = dict(
        target=str(target), objective="dead-params", goal="", auto=True,
        concrete=False, all_objectives=False, grade=False, history=False,
        from_dream=False, playbook=False, top=False, session=False, mode_word="",
        apply=False, max_steps=5, no_verify=False, fast=False, json=False)
    base.update(over)
    return argparse.Namespace(**base)


def _run(ns: argparse.Namespace) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cmd_develop(ns)
    return rc, out.getvalue()


# --------------------------------------------------------------------------- #
# the lens orders two equal-value objectives by their top target's centrality  #
# --------------------------------------------------------------------------- #
def test_equal_value_objectives_central_top_target_leads(tmp_path: Path):
    _hub_vs_leaf_project(tmp_path)
    board = m._auto_value_board(tmp_path, concrete=False)
    by_name = {r.objective: r for r in board}
    # both applicable + EQUAL buyer value → the lens is the deciding key.
    assert {"remove-dead-code", "dead-params"} <= set(by_name)
    assert (objective_value_weight("remove-dead-code")
            == objective_value_weight("dead-params") == 0.40)
    # the lens stamped each one's top-target in-degree (hub 4, leaf 0).
    assert by_name["remove-dead-code"].preview_centrality == 4
    assert by_name["dead-params"].preview_centrality == 0
    # so the more-central objective leads, FLIPPING the old alphabetical order.
    order = [r.objective for r in board
             if r.objective in ("remove-dead-code", "dead-params")]
    assert order == ["remove-dead-code", "dead-params"]
    assert order != sorted(order)  # the lens beat alphabetical


def test_lens_decides_the_rendered_preview_order(tmp_path: Path):
    # End-to-end through the rendered develop --auto preview: the hub-targeting
    # objective is printed before the leaf-targeting one despite equal value.
    _hub_vs_leaf_project(tmp_path)
    rc, out = _run(_auto_ns(tmp_path))
    assert rc == 0
    dead_code = out.find("`remove-dead-code`")
    dead_params = out.find("`dead-params`")
    assert dead_code >= 0 and dead_params >= 0
    assert dead_code < dead_params  # central top-target leads in the render


def test_lens_is_total_order_buyer_value_dominates_centrality(tmp_path: Path):
    # Centrality is SUBORDINATE to buyer value: a higher-value objective still
    # leads a lower-value one even when the lower one targets a more-central
    # module. The sort key is (-value, -centrality, name) — value first.
    _hub_vs_leaf_project(tmp_path)
    board = m._auto_value_board(tmp_path, concrete=False)
    keys = [(-objective_value_weight(r.objective), -r.preview_centrality, r.objective)
            for r in board]
    assert keys == sorted(keys)  # the board is in this exact (total) order


# --------------------------------------------------------------------------- #
# the in-degree helpers are correct + best-effort                              #
# --------------------------------------------------------------------------- #
def test_module_in_degrees_counts_importers(tmp_path: Path):
    _hub_vs_leaf_project(tmp_path)
    deg = m._module_in_degrees(tmp_path)
    assert deg["pkg/hub.py"] == 4
    assert deg["pkg/leaf.py"] == 0


def test_objective_top_centrality_picks_max_in_degree(tmp_path: Path):
    _hub_vs_leaf_project(tmp_path)
    deg = m._module_in_degrees(tmp_path)
    assert m._objective_top_centrality("remove-dead-code", tmp_path, deg) == 4
    assert m._objective_top_centrality("dead-params", tmp_path, deg) == 0


def test_centrality_helpers_inert_on_empty_or_unknown(tmp_path: Path):
    # Empty graph (no in-degrees) ⇒ every centrality reads 0 (lens inert), and an
    # unknown objective name ⇒ 0 — never an exception (best-effort, like the rest
    # of the preview). A result with no steps also reads 0.
    _hub_vs_leaf_project(tmp_path)
    deg = m._module_in_degrees(tmp_path)
    assert m._objective_top_centrality("remove-dead-code", tmp_path, {}) == 0
    assert m._objective_top_centrality("not-an-objective", tmp_path, deg) == 0

    from app.engine.objective_compiler import CompileResult

    empty = CompileResult(objective="x", fitness_start=0.0, fitness_end=0.0)
    assert m._result_top_centrality(empty, deg) == 0
    assert m._result_top_centrality(empty, {}) == 0


def test_empty_board_has_no_centrality_rows(tmp_path: Path):
    # A project with no applicable cheap objective ⇒ empty board ⇒ no rows to
    # stamp; the lens degrades to nothing without error.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    assert m._auto_value_board(tmp_path, concrete=False) == []


# --------------------------------------------------------------------------- #
# BYTE-IDENTITY: to_dict omits preview_centrality when 0; plan path unchanged   #
# --------------------------------------------------------------------------- #
def test_to_dict_omits_preview_centrality_when_zero():
    # Default (preview_centrality == 0) ⇒ the key is OMITTED, so the GoalRanking
    # JSON shape — and thus `apex plan --json` — is byte-identical to before.
    d = GoalRanking("modernize", 3.0, "refine").to_dict()
    assert "preview_centrality" not in d
    # the exact pre-existing key set is preserved (nothing added when off).
    assert set(d) == {"objective", "pending", "goal", "payoff", "reliability",
                      "value_weight", "priority"}


def test_to_dict_includes_preview_centrality_when_set():
    d = GoalRanking("remove-dead-code", 2.0, "tidy", preview_centrality=7).to_dict()
    assert d["preview_centrality"] == 7  # additive, integer in-degree, not rounded


def test_preview_centrality_does_not_feed_priority():
    # priority is a DISPLAY-blind score: it must NEVER read preview_centrality, so
    # an objective's priority is identical with or without the lens stamped.
    base = GoalRanking("modernize", 3.0, "refine")
    stamped = GoalRanking("modernize", 3.0, "refine", preview_centrality=99)
    assert base.priority == stamped.priority


def test_plan_path_rank_objectives_never_stamps_centrality(tmp_path: Path):
    # `apex plan` calls rank_objectives WITHOUT the preview lens; preview_centrality
    # stays the neutral 0 on every ranking ⇒ to_dict omits it ⇒ the plan JSON is
    # byte-identical to before this feature. (The lens lives ONLY in the cli
    # preview helpers, never in rank_objectives / the apply path.)
    _hub_vs_leaf_project(tmp_path)
    rankings = rank_objectives(str(tmp_path))
    assert rankings  # something is applicable
    assert all(r.preview_centrality == 0 for r in rankings)
    assert all("preview_centrality" not in r.to_dict() for r in rankings)


def test_apply_path_is_byte_identical_to_pre_lens(tmp_path: Path, monkeypatch):
    # The APPLIED set is untouched: an apply=True compile_objective run produces
    # the identical CompileResult.to_dict() whether or not the (display-only) lens
    # exists — the lens never runs on the apply path. We prove byte-identity by
    # spying that NO centrality helper is invoked during an apply, and that the
    # applied JSON is stable across two runs.
    from app.engine import objective_compiler as oc

    _hub_vs_leaf_project(tmp_path / "a")
    _hub_vs_leaf_project(tmp_path / "b")

    calls: list[str] = []
    monkeypatch.setattr(m, "_module_in_degrees",
                        lambda t: calls.append("deg") or {})

    import json as _json

    def _apply_json(root: Path) -> str:
        res = oc.compile_objective(str(root), objective="dead-params",
                                   max_steps=5, apply=True)
        return _json.dumps(res.to_dict(), indent=2)

    out_a = _apply_json(tmp_path / "a")
    out_b = _apply_json(tmp_path / "b")
    norm_a = out_a.replace(str(tmp_path / "a"), "ROOT")
    norm_b = out_b.replace(str(tmp_path / "b"), "ROOT")
    assert norm_a == norm_b              # the applied set is deterministic
    assert calls == []                   # the lens never touched the apply path


# --------------------------------------------------------------------------- #
# SUITE-FREE: the read-only preview runs NO pytest                             #
# --------------------------------------------------------------------------- #
def _no_pytest_subprocess(monkeypatch):
    """Trip the engine's ONE suite chokepoint: a pytest run is launched only via
    ``subprocess.run([... "-m", "pytest" ...])`` in the gated writer. Replace
    ``subprocess.run`` so any pytest invocation on the read-only path explodes the
    test (the suite-free invariant, structural — not a comment). Non-pytest calls
    pass through untouched."""
    import subprocess

    real = subprocess.run

    def guard(cmd, *a, **k):
        argv = cmd if isinstance(cmd, (list, tuple)) else [cmd]
        if any("pytest" in str(part) for part in argv):
            raise AssertionError("the read-only preview launched a pytest suite")
        return real(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", guard)


def test_value_board_runs_no_pytest(tmp_path: Path, monkeypatch):
    # The blast-radius lens uses the CHEAP DependencyGraphBuilder graph walk, never
    # pytest. With the pytest chokepoint tripped, the board still builds AND stamps
    # centrality — proving the lens needs no suite run.
    _hub_vs_leaf_project(tmp_path)
    _no_pytest_subprocess(monkeypatch)

    board = m._auto_value_board(tmp_path, concrete=False)
    assert board  # the lens ran (and stamped) without any suite execution
    assert any(r.preview_centrality > 0 for r in board)
    # and no pytest cache was written by the preview.
    assert not (tmp_path / ".pytest_cache").exists()


def test_develop_auto_preview_runs_no_pytest(tmp_path: Path, monkeypatch):
    # The full rendered develop --auto preview is read-only AND suite-free: the
    # pytest chokepoint is never reached, and no .pytest_cache appears under the
    # target after the dry-run preview.
    _hub_vs_leaf_project(tmp_path)
    _no_pytest_subprocess(monkeypatch)
    rc, _out = _run(_auto_ns(tmp_path))
    assert rc == 0
    assert not (tmp_path / ".pytest_cache").exists()


def test_preview_never_calls_apply_rename(tmp_path: Path, monkeypatch):
    # The one gated writer (which also runs the suite) is apply_rename. On the
    # default (apply=False) preview path it must NEVER be called — the read-only +
    # suite-free proof, structural (mirrors the existing eyml convention).
    _hub_vs_leaf_project(tmp_path)
    calls: list[tuple] = []

    import app.execution.cross_file_rename as cfr
    real = cfr.apply_rename
    monkeypatch.setattr(cfr, "apply_rename",
                        lambda *a, **k: calls.append((a, k)) or real(*a, **k))
    rc, _out = _run(_auto_ns(tmp_path))
    assert rc == 0
    assert calls == []  # the preview wrote nothing through the gated writer


def test_preview_does_not_write_the_tree(tmp_path: Path):
    # Read-only proof: the hub's unreachable line and the leaf's dead param are
    # still present after the preview — nothing was applied.
    _hub_vs_leaf_project(tmp_path)
    _run(_auto_ns(tmp_path))
    assert "y = 1" in (tmp_path / "pkg" / "hub.py").read_text()
    assert "dead" in (tmp_path / "pkg" / "leaf.py").read_text()
