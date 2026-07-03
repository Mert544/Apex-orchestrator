"""`apex dream --land` is the project's ONLY unattended landing surface — no
human reviews the diff between chain steps the way an ``apex develop``/
``apex assist --apply`` session would. Before this change, ``dream_develop``
never threaded ``covered_only`` into its ``compile_objective`` calls, so the
permissive default (``objective_compiler.compile_objective``'s
``covered_only=False``) governed the chain: a move whose green suite exercised
NOTHING (``coverage == "none"``) could still land unattended, overnight, with no
one reviewing it. This mirrors the SAME bug class closed for ``apex evolve``
(#115, ``app/engine/evolution.py`` forcing ``resolve_covered_only(unattended=
True)``) for the dream chain's landing surface.

These tests pin, layer by layer:

  1. ``dream_develop(covered_only=...)`` threads the flag to EVERY
     ``compile_objective`` call it makes (default False = byte-identical to
     before this parameter existed);
  2. ``_cmd_dream_land`` (``apex dream --land``) computes ``covered_only`` via
     ``resolve_covered_only(allow_weak=False, unattended=True)`` — the SAME
     single-source-of-truth policy ``apex evolve``/the daemon use — and forces
     it True UNCONDITIONALLY, dry run or apply;
  3. the effect is genuinely DEMOTE-ONLY: a real green-but-uncovered move is
     WITHHELD when armed, and landed when not — never the reverse;
  4. the PREVIEW path (no ``--apply``) is byte-identical regardless, because a
     dry run never reaches the gated apply loop where ``covered_only`` matters.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import app.engine.dream_develop as dream_develop_mod
from app.engine.dream_develop import DreamChainReport, dream_develop, render_dream_chain_markdown
from app.engine.objective_compiler import CompileResult
from app.policies.autonomy_policy import resolve_covered_only


# --- fixtures ----------------------------------------------------------------

def _stub_project(tmp_path: Path) -> Path:
    """A whole-tree project with a test-pinned fillable stub (mirrors the
    existing ``dream_develop`` test fixtures)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "s.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_s.py").write_text(
        "from app.s import add\ndef test_add():\n"
        "    assert add(1, 2) == 3\n    assert add(5, 7) == 12\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _covered_and_friendless_project(tmp_path: Path) -> Path:
    """Two modules for ``wire-module-exports``: ``hub.py`` has a linked test
    (module-level coverage), ``friendless.py`` has NO test anywhere referencing
    it (coverage ``"none"``) — the real demote-only split ``covered_only``
    distinguishes. Both already have real bodies (no stub-fill needed), so
    ``wire-module-exports`` is the first objective in the chain with candidate
    moves for them."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "hub.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "app" / "friendless.py").write_text(
        "def mul(a, b):\n    return a * b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_hub.py").write_text(
        "from app.hub import add\ndef test_add():\n"
        "    assert add(1, 2) == 3\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _spy_compile_objective(monkeypatch) -> list[dict]:
    """Replace ``compile_objective`` with a spy recording every call's kwargs;
    nothing is planned/applied and no suite runs."""
    calls: list[dict] = []

    def _fake(*args, **kwargs):
        calls.append(kwargs)
        return CompileResult(objective=kwargs.get("objective", ""),
                             fitness_start=0.0, fitness_end=0.0,
                             applied=bool(kwargs.get("apply", False)))

    monkeypatch.setattr(dream_develop_mod, "compile_objective", _fake)
    return calls


# --------------------------------------------------------------------------- #
# 1. dream_develop threads covered_only to EVERY compile_objective call        #
# --------------------------------------------------------------------------- #
def test_default_covered_only_false_threads_to_compile_objective(monkeypatch):
    calls = _spy_compile_objective(monkeypatch)
    dream_develop("/does-not-exist", apply=True)  # covered_only omitted
    assert calls  # the chain attempted at least one objective
    assert all(c["covered_only"] is False for c in calls)


def test_covered_only_true_threads_to_every_call_across_objectives_and_scopes(
        monkeypatch):
    # Force TWO chain objectives and TWO confluence scopes so the nested loop
    # (objectives x scopes) produces several calls — every single one must carry
    # covered_only=True, never just the first.
    monkeypatch.setattr(dream_develop_mod, "_chain_objectives",
                        lambda value_led=True: ["obj-a", "obj-b"])
    monkeypatch.setattr(dream_develop_mod, "_chain_scope",
                        lambda root, value_ranked=False: ["m1.py", "m2.py"])
    calls = _spy_compile_objective(monkeypatch)

    dream_develop("/does-not-exist", apply=True, covered_only=True)

    assert len(calls) == 4  # 2 objectives x 2 scopes
    assert all(c["covered_only"] is True for c in calls)


# --------------------------------------------------------------------------- #
# 2. _cmd_dream_land forces covered_only True via resolve_covered_only         #
#    (unattended=True) — regardless of --apply.                                #
# --------------------------------------------------------------------------- #
def _land_ns(tmp_path: Path, **over) -> argparse.Namespace:
    base = dict(target=str(tmp_path), curate=False, land=True, apply=False,
               fast=False, json=False)
    base.update(over)
    return argparse.Namespace(**base)


def _spy_dream_develop(monkeypatch) -> dict:
    captured: dict = {}

    def _fake(project_root, max_steps=25, verify=True, apply=False, fast=False,
              value_ranked=False, max_modules=None, preview_skip_mutation=False,
              covered_only=False):
        captured["covered_only"] = covered_only
        captured["apply"] = apply
        return DreamChainReport(goal="ship-value", objectives=[], applied=apply)

    monkeypatch.setattr("app.engine.dream_develop.dream_develop", _fake)
    return captured


def test_cmd_dream_land_forces_covered_only_true_dry_run(tmp_path, monkeypatch, capsys):
    from app import cli_insight

    captured = _spy_dream_develop(monkeypatch)
    rc = cli_insight.cmd_dream(_land_ns(tmp_path, apply=False))
    capsys.readouterr()
    assert rc == 0
    assert captured["covered_only"] is True


def test_cmd_dream_land_forces_covered_only_true_on_apply(tmp_path, monkeypatch, capsys):
    from app import cli_insight

    captured = _spy_dream_develop(monkeypatch)
    rc = cli_insight.cmd_dream(_land_ns(tmp_path, apply=True))
    capsys.readouterr()
    assert rc == 0
    assert captured["covered_only"] is True


def test_cmd_dream_land_calls_resolve_covered_only_with_unattended_true(
        tmp_path, monkeypatch, capsys):
    """Non-tautological wiring proof: spy on ``resolve_covered_only`` ITSELF and
    confirm ``_cmd_dream_land`` calls it with the exact unattended contract
    (``allow_weak=False, unattended=True``) — not some other combination that
    happens to also return True today."""
    from app import cli_insight

    resolve_calls: list[dict] = []

    def _fake_resolve(*, allow_weak, unattended):
        resolve_calls.append({"allow_weak": allow_weak, "unattended": unattended})
        return True

    monkeypatch.setattr("app.policies.autonomy_policy.resolve_covered_only",
                        _fake_resolve)
    captured = _spy_dream_develop(monkeypatch)
    rc = cli_insight.cmd_dream(_land_ns(tmp_path))
    capsys.readouterr()
    assert rc == 0
    assert resolve_calls == [{"allow_weak": False, "unattended": True}]
    assert captured["covered_only"] is True


def test_cmd_dream_land_forwards_whatever_the_policy_returns(
        tmp_path, monkeypatch, capsys):
    """Proves ``_cmd_dream_land`` genuinely FORWARDS the policy's verdict rather
    than hardcoding True somewhere else: a stubbed ``resolve_covered_only``
    returning a distinctive sentinel reaches ``dream_develop`` verbatim."""
    from app import cli_insight

    monkeypatch.setattr("app.policies.autonomy_policy.resolve_covered_only",
                        lambda *, allow_weak, unattended: "SENTINEL")
    captured = _spy_dream_develop(monkeypatch)
    rc = cli_insight.cmd_dream(_land_ns(tmp_path))
    capsys.readouterr()
    assert rc == 0
    assert captured["covered_only"] == "SENTINEL"


# --------------------------------------------------------------------------- #
# 3. Genuinely DEMOTE-ONLY: a real green-but-uncovered move is withheld when   #
#    armed, landed when not — proven end-to-end with no compile_objective spy. #
# --------------------------------------------------------------------------- #
def test_dream_develop_covered_only_withholds_real_uncovered_move(
        tmp_path, monkeypatch):
    _covered_and_friendless_project(tmp_path)
    # Isolate ONE chain objective so an earlier objective (cover-gaps) doesn't
    # auto-heal the friendless module's coverage before wire-module-exports runs
    # — keeps the fixture a surgical, deterministic covered-vs-uncovered split.
    monkeypatch.setattr(dream_develop_mod, "_chain_objectives",
                        lambda value_led=True: ["wire-module-exports"])

    report = dream_develop(str(tmp_path), apply=True, verify=True, fast=True,
                           covered_only=True)
    targets = {s.target for r in report.results for s in r.steps}
    assert "app/hub.py:wire-module-exports" in targets       # covered -> landed
    assert "app/friendless.py:wire-module-exports" not in targets  # uncovered -> withheld
    assert any("friendless.py" in w for r in report.results for w in r.withheld)
    # The withheld module's file is restored untouched.
    assert "__all__" not in (tmp_path / "app" / "friendless.py").read_text(
        encoding="utf-8")


def test_dream_develop_default_lands_the_same_uncovered_move(tmp_path, monkeypatch):
    # Off (the historical default): BOTH modules land, byte-for-byte as before
    # this feature existed — proving covered_only is additive, never subtractive
    # by default.
    _covered_and_friendless_project(tmp_path)
    monkeypatch.setattr(dream_develop_mod, "_chain_objectives",
                        lambda value_led=True: ["wire-module-exports"])

    report = dream_develop(str(tmp_path), apply=True, verify=True, fast=True)
    targets = {s.target for r in report.results for s in r.steps}
    assert {"app/hub.py:wire-module-exports",
            "app/friendless.py:wire-module-exports"} <= targets
    assert "__all__" in (tmp_path / "app" / "friendless.py").read_text(
        encoding="utf-8")


def test_dream_land_apply_end_to_end_withholds_uncovered_module(
        tmp_path, monkeypatch, capsys):
    """Full-stack proof through the REAL CLI dispatch (``_cmd_dream_land``'s own
    forced covered_only), no compile_objective/dream_develop spy at all — only
    the same objective isolation the direct-call tests above use to keep the
    fixture surgical."""
    from app import cli_insight

    _covered_and_friendless_project(tmp_path)
    monkeypatch.setattr(dream_develop_mod, "_chain_objectives",
                        lambda value_led=True: ["wire-module-exports"])

    rc = cli_insight.cmd_dream(_land_ns(tmp_path, apply=True, fast=True))
    capsys.readouterr()
    assert rc == 0
    assert "__all__" in (tmp_path / "app" / "hub.py").read_text(encoding="utf-8")
    assert "__all__" not in (tmp_path / "app" / "friendless.py").read_text(
        encoding="utf-8")


# --------------------------------------------------------------------------- #
# 4. PREVIEW stays byte-identical: a dry run never reaches the gated apply     #
#    loop, so covered_only has ZERO observable effect without --apply.        #
# --------------------------------------------------------------------------- #
def test_dry_run_report_byte_identical_regardless_of_covered_only(tmp_path):
    _stub_project(tmp_path)
    off = dream_develop(str(tmp_path), apply=False, verify=False,
                        covered_only=False)
    on = dream_develop(str(tmp_path), apply=False, verify=False,
                       covered_only=True)
    assert on.to_dict() == off.to_dict()
    assert render_dream_chain_markdown(on) == render_dream_chain_markdown(off)


def test_cmd_dream_land_preview_matches_pre_change_default_rendering(
        tmp_path, capsys):
    """The CLI now ALWAYS forces covered_only=True — even for a dry run. This
    proves that forcing has NO observable effect on the preview: the rendered
    markdown is exactly what a direct ``dream_develop`` call at the historical
    default (``covered_only`` did not exist, i.e. False) produces."""
    from app import cli_insight

    _stub_project(tmp_path)
    direct = dream_develop(str(tmp_path), apply=False, verify=False)
    rc = cli_insight.cmd_dream(_land_ns(tmp_path, apply=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip() == render_dream_chain_markdown(direct).strip()


def test_resolve_covered_only_unattended_is_unconditionally_true():
    """Anchor: the exact policy call ``_cmd_dream_land`` makes always resolves
    True, with or without allow_weak (there is no ``--allow-weak`` flag on
    ``dream --land`` — the chain is unattended by construction)."""
    assert resolve_covered_only(allow_weak=False, unattended=True) is True
    assert resolve_covered_only(allow_weak=True, unattended=True) is True
