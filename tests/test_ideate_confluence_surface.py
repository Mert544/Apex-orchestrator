"""Surface the idea engine's convergence/confluence insight in `apex ideate`.

The `confluence` seeding signal names modules where >=3 independent signal
families converge — the highest-leverage development targets. These tests cover
the ADDITIVE "Convergence hotspots" section cmd_ideate renders for them, and
prove the no-confluence path stays byte-identical.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import app.engine.idea_permutation as ipm
from app.cli import cmd_ideate


def _project(tmp_path: Path) -> Path:
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


# The two converging-family entries we inject onto the profile. Family tuples
# arrive already sorted from the profiler; we mirror that here.
_CONFLUENCE = [
    {
        "module": "app/hub.py",
        "family_count": 4,
        "families": ("complexity", "hub", "security", "untested"),
    },
    {
        "module": "app/io.py",
        "family_count": 3,
        "families": ("co-change", "high-churn", "untested"),
    },
]


def _patch_confluence(monkeypatch, entries) -> None:
    """Layer ``entries`` onto whatever profile the real profiler computes.

    The engine still runs normally; only ``confluence_modules`` is overridden,
    so the idea tree is unaffected and the surface section is exercised in
    isolation.
    """
    real_profile = ipm.ProjectProfiler.profile

    def _profile(self):
        prof = real_profile(self)
        prof.confluence_modules = [dict(e) for e in entries]
        return prof

    monkeypatch.setattr(ipm.ProjectProfiler, "profile", _profile)


def test_confluence_section_renders_modules_and_families(tmp_path, capsys, monkeypatch):
    _project(tmp_path)
    _patch_confluence(monkeypatch, _CONFLUENCE)
    rc = cmd_ideate(_ideate_ns(tmp_path))
    assert rc == 0
    out = capsys.readouterr().out
    assert "## Convergence hotspots" in out
    # Development framing, not a single-lens (e.g. security) headline.
    assert "highest-leverage development targets" in out
    assert "Stabilize and test them first" in out
    # Each module appears with its family_count and converging family names.
    assert "`app/hub.py` — 4 converging families: " in out
    assert "complexity, hub, security, untested" in out
    assert "`app/io.py` — 3 converging families: " in out
    assert "co-change, high-churn, untested" in out


def test_no_section_when_no_confluences(tmp_path, capsys, monkeypatch):
    _project(tmp_path)
    _patch_confluence(monkeypatch, [])
    rc = cmd_ideate(_ideate_ns(tmp_path))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Convergence hotspots" not in out


def test_no_confluence_output_byte_identical(tmp_path, capsys, monkeypatch):
    """With no confluences the gated section emits nothing: output is unchanged.

    The expected baseline is reconstructed independently from ``render_markdown``
    over the same engine run, so this asserts the section code path adds exactly
    zero bytes when the signal is empty — byte-for-byte.
    """
    _project(tmp_path)
    _patch_confluence(monkeypatch, [])

    # Independently reconstruct the baseline the default branch prints: the idea
    # tree markdown, then a trailing newline from print(). No confluence section.
    engine = ipm.IdeaPermutationEngine(
        config={
            "max_total_ideas": 20,
            "max_idea_depth": 2,
            "breadth": 3,
            "min_relevance": 0.0,
        },
        project_root=str(tmp_path),
    )
    report = engine.run(objective=None)
    expected = ipm.render_markdown(report) + "\n"
    assert engine.last_profile.confluence_modules == []

    rc = cmd_ideate(_ideate_ns(tmp_path))
    assert rc == 0
    empty_out = capsys.readouterr().out

    assert empty_out == expected
    assert "Convergence hotspots" not in empty_out


def test_json_includes_confluence_array(tmp_path, capsys, monkeypatch):
    _project(tmp_path)
    _patch_confluence(monkeypatch, _CONFLUENCE)
    rc = cmd_ideate(_ideate_ns(tmp_path, json=True))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    # Additive: the existing idea tree is still present.
    assert "ideas" in payload
    assert "confluence" in payload
    assert payload["confluence"] == [
        {
            "module": "app/hub.py",
            "family_count": 4,
            "families": ["complexity", "hub", "security", "untested"],
        },
        {
            "module": "app/io.py",
            "family_count": 3,
            "families": ["co-change", "high-churn", "untested"],
        },
    ]


def test_json_omits_confluence_key_when_empty(tmp_path, capsys, monkeypatch):
    _project(tmp_path)
    _patch_confluence(monkeypatch, [])
    rc = cmd_ideate(_ideate_ns(tmp_path, json=True))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "confluence" not in payload


def test_confluence_section_is_deterministic(tmp_path, capsys, monkeypatch):
    _project(tmp_path)
    _patch_confluence(monkeypatch, _CONFLUENCE)

    rc = cmd_ideate(_ideate_ns(tmp_path))
    assert rc == 0
    first = capsys.readouterr().out

    rc = cmd_ideate(_ideate_ns(tmp_path))
    assert rc == 0
    second = capsys.readouterr().out

    assert first == second
