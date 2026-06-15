"""Characterization pins for ``compile_objective`` output.

A behaviour-preserving refactor (extracting cohesive private helpers from the
compile loop) must leave EVERY compiled objective byte-identical. These tests
freeze ``compile_objective(...).to_dict()`` on representative objectives — dry
run, applied, scoped, multi-step, and the unknown / natural-language paths — so
the exact result dict is locked. Construction style mirrors
``test_objective_compiler.py``.
"""
from __future__ import annotations

from pathlib import Path

from app.engine.objective_compiler import compile_objective


def _project(tmp_path: Path, body: str) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(body, encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_import():\n    assert app.m is not None\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


_THREE_DEAD = (
    "def render(text, color=None, width=80):\n"
    "    return text[:width]\n\n\n"
    "def fetch(url, retries=3):\n"
    "    return url\n\n\n"
    "def use():\n"
    "    return render('hi', width=10) + fetch('u', retries=1)\n"
)

_TIDY = (
    "def check(x):\n    if x == None:\n        return dict()\n"
    "    msg = f\"done\"\n    return msg\n"
)


def test_dead_params_dry_run_result_is_pinned(tmp_path):
    _project(tmp_path, _THREE_DEAD)
    r = compile_objective(str(tmp_path), objective="dead-params", apply=False)
    assert r.to_dict() == {
        "objective": "dead-params",
        "fitness_start": 2.0,
        "fitness_end": 2.0,
        "improved": False,
        "moves_applied": 2,
        "steps": [
            {
                "operator": "drop_param",
                "target": "app/m.py:render(color)",
                "description": "drop never-read parameter `color` from render() in app/m.py",
                "fitness_before": 2.0,
                "fitness_after": 1.0,
                "verified": False,
            },
            {
                "operator": "drop_param",
                "target": "app/m.py:fetch(retries)",
                "description": "drop never-read parameter `retries` from fetch() in app/m.py",
                "fitness_before": 2.0,
                "fitness_after": 1.0,
                "verified": False,
            },
        ],
        "blocked": [],
        "applied": False,
    }


def test_dead_params_applied_result_is_pinned(tmp_path):
    _project(tmp_path, _THREE_DEAD)
    r = compile_objective(str(tmp_path), objective="dead-params", apply=True, verify=False)
    assert r.to_dict() == {
        "objective": "dead-params",
        "fitness_start": 2.0,
        "fitness_end": 0.0,
        "improved": True,
        "moves_applied": 2,
        "steps": [
            {
                "operator": "drop_param",
                "target": "app/m.py:render(color)",
                "description": "drop never-read parameter `color` from render() in app/m.py",
                "fitness_before": 2.0,
                "fitness_after": 1.0,
                "verified": False,
            },
            {
                "operator": "drop_param",
                "target": "app/m.py:fetch(retries)",
                "description": "drop never-read parameter `retries` from fetch() in app/m.py",
                "fitness_before": 1.0,
                "fitness_after": 0.0,
                "verified": False,
            },
        ],
        "blocked": [],
        "applied": True,
    }


def test_dead_params_applied_verified_result_is_pinned(tmp_path):
    # The suite-gated path: each landed move reports verified=True.
    _project(tmp_path, _THREE_DEAD)
    r = compile_objective(str(tmp_path), objective="dead-params", apply=True, verify=True)
    assert r.to_dict() == {
        "objective": "dead-params",
        "fitness_start": 2.0,
        "fitness_end": 0.0,
        "improved": True,
        "moves_applied": 2,
        "steps": [
            {
                "operator": "drop_param",
                "target": "app/m.py:render(color)",
                "description": "drop never-read parameter `color` from render() in app/m.py",
                "fitness_before": 2.0,
                "fitness_after": 1.0,
                "verified": True,
            },
            {
                "operator": "drop_param",
                "target": "app/m.py:fetch(retries)",
                "description": "drop never-read parameter `retries` from fetch() in app/m.py",
                "fitness_before": 1.0,
                "fitness_after": 0.0,
                "verified": True,
            },
        ],
        "blocked": [],
        "applied": True,
    }


def test_dead_params_max_steps_one_result_is_pinned(tmp_path):
    # The cap path: one drop lands, one dead param remains.
    _project(tmp_path, _THREE_DEAD)
    r = compile_objective(str(tmp_path), objective="dead-params",
                          apply=True, verify=False, max_steps=1)
    assert r.to_dict() == {
        "objective": "dead-params",
        "fitness_start": 2.0,
        "fitness_end": 1.0,
        "improved": True,
        "moves_applied": 1,
        "steps": [
            {
                "operator": "drop_param",
                "target": "app/m.py:render(color)",
                "description": "drop never-read parameter `color` from render() in app/m.py",
                "fitness_before": 2.0,
                "fitness_after": 1.0,
                "verified": False,
            },
        ],
        "blocked": [],
        "applied": True,
    }


def test_modernize_applied_result_is_pinned(tmp_path):
    _project(tmp_path, _TIDY)
    r = compile_objective(str(tmp_path), objective="modernize", apply=True, verify=False)
    assert r.to_dict() == {
        "objective": "modernize",
        "fitness_start": 3.0,
        "fitness_end": 0.0,
        "improved": True,
        "moves_applied": 3,
        "steps": [
            {
                "operator": "modernize",
                "target": "app/m.py:modernize",
                "description": "modernize None comparisons in app/m.py",
                "fitness_before": 3.0,
                "fitness_after": 2.0,
                "verified": False,
            },
            {
                "operator": "fix_fstring",
                "target": "app/m.py:fix_fstring",
                "description": "drop dead f-string prefixes in app/m.py",
                "fitness_before": 2.0,
                "fitness_after": 1.0,
                "verified": False,
            },
            {
                "operator": "fix_collection",
                "target": "app/m.py:fix_collection",
                "description": "use collection literals in app/m.py",
                "fitness_before": 1.0,
                "fitness_after": 0.0,
                "verified": False,
            },
        ],
        "blocked": [],
        "applied": True,
    }


def test_natural_language_objective_result_is_pinned(tmp_path):
    # "tidy up" resolves to modernize and the result reports the RESOLVED name.
    _project(tmp_path, _TIDY)
    r = compile_objective(str(tmp_path), objective="tidy up the module",
                          apply=True, verify=False)
    assert r.objective == "modernize"
    assert r.fitness_start == 3.0 and r.fitness_end == 0.0
    assert [s["operator"] for s in r.to_dict()["steps"]] == [
        "modernize", "fix_fstring", "fix_collection"]


def test_clean_project_result_is_pinned(tmp_path):
    # No debt → zero fitness, no steps, no blockers.
    _project(tmp_path, "def f(x):\n    return x + 1\n")
    r = compile_objective(str(tmp_path), objective="dead-params", apply=True, verify=False)
    assert r.to_dict() == {
        "objective": "dead-params",
        "fitness_start": 0.0,
        "fitness_end": 0.0,
        "improved": False,
        "moves_applied": 0,
        "steps": [],
        "blocked": [],
        "applied": True,
    }


def test_unknown_objective_result_is_pinned(tmp_path):
    _project(tmp_path, "def f(x):\n    return x\n")
    r = compile_objective(str(tmp_path), objective="make-coffee", apply=True)
    d = r.to_dict()
    assert d["objective"] == "make-coffee"
    assert d["fitness_start"] == 0.0 and d["fitness_end"] == 0.0
    assert d["steps"] == []
    assert len(d["blocked"]) == 1
    assert d["blocked"][0].startswith("unknown objective 'make-coffee' (known: ")
    # applied defaults to False for the early-return block (no campaign ran).
    assert d["applied"] is False


def test_scoped_campaign_result_is_pinned(tmp_path):
    # Scope to one module: only its dead param is dropped; fitness is the scoped
    # move count, not the project-wide fitness.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "hub.py").write_text(
        "def render(text, color=None, width=80):\n    return text[:width]\n", encoding="utf-8")
    (tmp_path / "app" / "other.py").write_text(
        "def fetch(url, retries=3):\n    return url\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.hub import render\nfrom app.other import fetch\n"
        "def test_all():\n    assert render('hi', width=2) == 'hi'\n"
        "    assert fetch('u') == 'u'\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    r = compile_objective(str(tmp_path), objective="dead-params",
                          apply=True, verify=False, scope_module="app/hub.py")
    assert r.to_dict() == {
        "objective": "dead-params",
        "fitness_start": 1.0,
        "fitness_end": 0.0,
        "improved": True,
        "moves_applied": 1,
        "steps": [
            {
                "operator": "drop_param",
                "target": "app/hub.py:render(color)",
                "description": "drop never-read parameter `color` from render() in app/hub.py",
                "fitness_before": 1.0,
                "fitness_after": 0.0,
                "verified": False,
            },
        ],
        "blocked": [],
        "applied": True,
    }
