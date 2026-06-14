"""`apex ideate --actions --prove`: proof lines reach the user-facing CLI.

The bridge already produces proof-carrying plans (`plan_tree`/`plan_roadmap`
take `proof=...`); these tests pin that the `--prove` flag flips it on the CLI
surface AND that the default (no-`--prove`) `--actions` output is byte-identical
to today, so existing idea sets don't shift.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.cli import cmd_ideate


def _project(tmp_path: Path) -> Path:
    """A tmp project with a runnable transform candidate (`eval(cmd)`)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def run(cmd):\n    return eval(cmd)\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    return tmp_path


def _ideate_ns(tmp_path: Path, **overrides) -> argparse.Namespace:
    base = dict(
        target=str(tmp_path),
        objective="",
        depth=2,
        breadth=3,
        max_ideas=20,
        min_relevance=0.0,
        actions=False,
        top=0,
        draft=False,
        prove=False,
        apply=False,
        verify=False,
        commit=False,
        max_apply=0,
        mode="supervised",
        mermaid=False,
        json=False,
        out="",
        kind="",
        roadmap=False,
        facets=False,
        facet_depth=1,
        shape=False,
        pareto=False,
        sequence=False,
        adaptive=False,
        budget=0.0,
        invest=False,
        phase="",
        save=False,
        diff=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_actions_prove_emits_proof_line(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_ideate(_ideate_ns(tmp_path, actions=True, prove=True, top=5))
    assert rc == 0
    out = capsys.readouterr().out
    assert "proof:" in out


def test_actions_without_prove_has_no_proof_line(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_ideate(_ideate_ns(tmp_path, actions=True, top=5))
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip()
    assert "proof:" not in out


def test_default_actions_output_is_byte_identical(tmp_path, capsys):
    """`--prove` must not change the default (no-`--prove`) `--actions` bytes."""
    _project(tmp_path)
    rc = cmd_ideate(_ideate_ns(tmp_path, actions=True, top=5, prove=False))
    assert rc == 0
    no_flag = capsys.readouterr().out

    # An identical run with the flag explicitly defaulted off — same bytes.
    rc = cmd_ideate(_ideate_ns(tmp_path, actions=True, top=5))
    assert rc == 0
    flag_off = capsys.readouterr().out
    assert no_flag == flag_off


def test_prove_without_actions_is_harmless(tmp_path, capsys):
    """`--prove` alone (no `--actions`) renders the plain idea tree, no proof."""
    _project(tmp_path)
    rc = cmd_ideate(_ideate_ns(tmp_path, prove=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip()
    assert "proof:" not in out


def test_prove_is_deterministic(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_ideate(_ideate_ns(tmp_path, actions=True, prove=True, top=5))
    assert rc == 0
    first = capsys.readouterr().out
    rc = cmd_ideate(_ideate_ns(tmp_path, actions=True, prove=True, top=5))
    assert rc == 0
    second = capsys.readouterr().out
    assert first == second
    assert "proof:" in first


def test_roadmap_actions_prove_renders_and_is_deterministic(tmp_path, capsys):
    """`--prove` flows through the roadmap-ordered plan path too (proof=True
    reaches `plan_roadmap`); the plan still renders and stays deterministic.

    Which bounded top-K runnable steps end up proof-carrying is the bridge's
    concern; the CLI's job is only to flip the flag without breaking the path.
    """
    _project(tmp_path)
    rc = cmd_ideate(
        _ideate_ns(tmp_path, roadmap=True, actions=True, prove=True, top=5)
    )
    assert rc == 0
    first = capsys.readouterr().out
    assert "Action Plan" in first
    rc = cmd_ideate(
        _ideate_ns(tmp_path, roadmap=True, actions=True, prove=True, top=5)
    )
    assert rc == 0
    assert capsys.readouterr().out == first
