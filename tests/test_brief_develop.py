from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.engine.brief_develop import (
    BriefDevelopResult,
    concern_phrases,
    develop_brief,
    objectives_for_brief,
    render_brief_develop_markdown,
)
from app.engine.idea_brief import Brief


# --- pure mapping helpers (no pipeline) --------------------------------------

def _fake_brief(evidence: dict, plan: list) -> SimpleNamespace:
    return SimpleNamespace(evidence=evidence, plan=plan, subject="app/m.py")


def test_concern_phrases_prefers_evidenced():
    b = _fake_brief({"unreachable": [[3, "x"]]},
                    [("simplify", ["unreachable", "deep nesting"])])
    # Evidenced phrases win — the plan vocabulary is ignored when evidence exists.
    assert concern_phrases(b) == ["unreachable"]


def test_concern_phrases_falls_back_to_plan_when_no_evidence():
    b = _fake_brief({}, [("surface", ["modernize", "none comparison"])])
    assert concern_phrases(b) == ["surface", "modernize", "none comparison"]


def test_concern_phrases_dedups_plan_fallback():
    b = _fake_brief({}, [("modernize", ["modernize"]), ("a", ["modernize"])])
    assert concern_phrases(b) == ["modernize", "a"]


def test_objectives_for_brief_maps_through_facet_bridge():
    b = _fake_brief({"unreachable": [[3, "x"]], "parameterize": [[1, "y"]]}, [])
    # unreachable -> remove-dead-code, parameterize -> dead-params, in order.
    assert objectives_for_brief(b) == ["remove-dead-code", "dead-params"]


def test_objectives_for_brief_empty_when_nothing_maps():
    b = _fake_brief({"a vague wish": [[1, "x"]]}, [])
    assert objectives_for_brief(b) == []


# --- rendering ----------------------------------------------------------------

def test_render_no_objectives_explains_manual():
    md = render_brief_develop_markdown(BriefDevelopResult(
        branch_path="x.o", title="T", subject="app/m.py", objectives=[]))
    assert "Brief → develop" in md and "Carry it out by hand" in md


def test_render_with_objectives_lists_mapping():
    md = render_brief_develop_markdown(BriefDevelopResult(
        branch_path="x.o", title="T", subject="app/m.py",
        objectives=["remove-dead-code"], applied=False,
        check={"branch_path": "x.o", "title": "T", "subject": "app/m.py",
               "resolved": [], "open": [], "measured_total": 0}))
    assert "`remove-dead-code`" in md and "Would apply" in md


# --- integration: the loop closes (brief -> develop -> burndown) -------------

def _dead_code_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def f(x):\n    return x\n    y = 1\n    return y\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import f\ndef test_f():\n    assert f(3) == 3\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _patch_brief(monkeypatch, evidence: dict, plan: list, branch="dc.brief"):
    brief = Brief(branch_path=branch, title="dead code", subject="app/m.py",
                  operator="simplify", evidence=evidence, plan=plan)
    monkeypatch.setattr("app.engine.idea_brief.build_brief",
                        lambda *a, **k: brief)
    return brief


def test_develop_brief_runs_and_burns_down(tmp_path, monkeypatch):
    _dead_code_project(tmp_path)
    _patch_brief(monkeypatch, {"unreachable": [[3, "unreachable code"]]},
                 [("simplify", ["unreachable"])])
    result = develop_brief(str(tmp_path), branch_path="dc.brief",
                           apply=True, verify=False)
    assert result is not None
    assert result.objectives == ["remove-dead-code"]
    assert result.total_moves >= 1
    # The unreachable statement is gone from the live code...
    src = (tmp_path / "app" / "m.py").read_text()
    assert "y = 1" not in src
    # ...and the burndown PROVES the evidenced concern resolved (scan-decided).
    assert result.measured_total == 1
    assert result.resolved == 1


def test_develop_brief_dry_run_writes_nothing(tmp_path, monkeypatch):
    _dead_code_project(tmp_path)
    _patch_brief(monkeypatch, {"unreachable": [[3, "unreachable code"]]},
                 [("simplify", ["unreachable"])])
    before = (tmp_path / "app" / "m.py").read_text()
    result = develop_brief(str(tmp_path), branch_path="dc.brief",
                           apply=False, verify=False)
    assert result is not None and not result.applied
    assert (tmp_path / "app" / "m.py").read_text() == before  # untouched
    assert result.objectives == ["remove-dead-code"]


def test_develop_brief_none_when_no_brief(tmp_path, monkeypatch):
    _dead_code_project(tmp_path)
    monkeypatch.setattr("app.engine.idea_brief.build_brief", lambda *a, **k: None)
    assert develop_brief(str(tmp_path), apply=False) is None


def test_develop_brief_no_mapping_yields_empty_campaign(tmp_path, monkeypatch):
    _dead_code_project(tmp_path)
    _patch_brief(monkeypatch, {"a vague wish": [[1, "x"]]}, [])
    result = develop_brief(str(tmp_path), branch_path="dc.brief",
                           apply=True, verify=False)
    assert result is not None and result.objectives == []
    assert result.total_moves == 0


def test_to_dict_round_trips(tmp_path, monkeypatch):
    _dead_code_project(tmp_path)
    _patch_brief(monkeypatch, {"unreachable": [[3, "u"]]}, [("s", ["unreachable"])])
    result = develop_brief(str(tmp_path), branch_path="dc.brief",
                           apply=True, verify=False)
    d = result.to_dict()
    assert d["objectives"] == ["remove-dead-code"] and d["applied"] is True
    assert d["resolved"] == 1 and d["measured_total"] == 1


# --- CLI flag wiring ----------------------------------------------------------

def test_cmd_brief_develop_flag(tmp_path, monkeypatch, capsys):
    import argparse

    from app.cli_insight import cmd_brief
    _dead_code_project(tmp_path)
    _patch_brief(monkeypatch, {"unreachable": [[3, "u"]]}, [("s", ["unreachable"])])
    rc = cmd_brief(argparse.Namespace(
        target=str(tmp_path), branch="dc.brief", subject="", objective="",
        depth=2, breadth=4, max_ideas=40, check=False, save=False,
        develop=True, apply=True, max_steps=25, no_verify=True, json=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Brief → develop" in out and "remove-dead-code" in out
    assert "y = 1" not in (tmp_path / "app" / "m.py").read_text()


def test_cmd_brief_develop_dry_run_hint(tmp_path, monkeypatch, capsys):
    import argparse

    from app.cli_insight import cmd_brief
    _dead_code_project(tmp_path)
    _patch_brief(monkeypatch, {"unreachable": [[3, "u"]]}, [("s", ["unreachable"])])
    rc = cmd_brief(argparse.Namespace(
        target=str(tmp_path), branch="dc.brief", subject="", objective="",
        depth=2, breadth=4, max_ideas=40, check=False, save=False,
        develop=True, apply=False, max_steps=25, no_verify=True, json=False))
    assert rc == 0
    assert "--develop --apply" in capsys.readouterr().out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
