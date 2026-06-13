from __future__ import annotations

from pathlib import Path

from app.engine.objective_compiler import (
    CompileResult,
    compile_objective,
    dead_parameter_fitness,
    render_compile_markdown,
)


def _project(tmp_path: Path, body: str) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(body, encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_import():\n    assert app.m is not None\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


_THREE_DEAD = (
    "def render(text, color=None, width=80):\n"
    "    return text[:width]\n\n\n"
    "def fetch(url, retries=3):\n"
    "    return url\n\n\n"
    "def use():\n"
    "    return render('hi', width=10) + fetch('u', retries=1)\n"
)


def test_fitness_counts_dead_parameters(tmp_path):
    _project(tmp_path, _THREE_DEAD)
    # color, retries are never read (width and url are) → fitness 2.
    assert dead_parameter_fitness(str(tmp_path)) == 2.0


def test_clean_project_has_zero_fitness_and_no_moves(tmp_path):
    _project(tmp_path, "def f(x):\n    return x + 1\n")
    r = compile_objective(str(tmp_path), apply=True, verify=False)
    assert r.fitness_start == 0.0
    assert r.steps == []
    assert not r.improved


def test_dry_run_lists_moves_without_writing(tmp_path):
    _project(tmp_path, _THREE_DEAD)
    before = (tmp_path / "app" / "m.py").read_text()
    r = compile_objective(str(tmp_path), apply=False)
    assert not r.applied
    assert len(r.steps) == 2  # color + retries
    # Dry run never touches the tree.
    assert (tmp_path / "app" / "m.py").read_text() == before


def test_apply_composes_drops_to_fixpoint(tmp_path):
    _project(tmp_path, _THREE_DEAD)
    r = compile_objective(str(tmp_path), apply=True, verify=False)
    assert isinstance(r, CompileResult)
    assert r.fitness_start == 2.0
    assert r.fitness_end == 0.0
    assert r.improved
    assert len(r.steps) == 2
    # Fitness decreases monotonically across the composed sequence.
    assert [s.fitness_after for s in r.steps] == [1.0, 0.0]
    src = (tmp_path / "app" / "m.py").read_text()
    assert "color" not in src and "retries" not in src
    # The kept parameters and call sites survive.
    assert "width" in src and "url" in src


def test_apply_with_verification_runs_the_suite(tmp_path):
    # The suite gate is real: each landed move reports verified=True.
    _project(tmp_path, _THREE_DEAD)
    r = compile_objective(str(tmp_path), apply=True, verify=True)
    assert r.fitness_end == 0.0
    assert all(s.verified for s in r.steps)


def test_unknown_objective_is_blocked(tmp_path):
    _project(tmp_path, "def f(x):\n    return x\n")
    r = compile_objective(str(tmp_path), objective="make-coffee", apply=True)
    assert r.steps == []
    assert any("unknown objective" in b for b in r.blocked)


def test_max_steps_caps_the_campaign(tmp_path):
    _project(tmp_path, _THREE_DEAD)
    r = compile_objective(str(tmp_path), apply=True, verify=False, max_steps=1)
    assert len(r.steps) == 1
    assert r.fitness_end == 1.0  # one drop landed, one dead param remains


def test_composition_recorded_to_memory(tmp_path):
    import json
    _project(tmp_path, _THREE_DEAD)
    compile_objective(str(tmp_path), apply=True, verify=False)
    mem = json.loads((tmp_path / ".apex" / "idea-memory.json").read_text())
    # The drop operator is credited, and the drop>drop composition is learned.
    assert mem["by_operator"]["drop_param"]["applied"] == 2
    assert mem["by_sequence"].get("drop_param>drop_param", {}).get("applied") == 1


def test_render_markdown(tmp_path):
    _project(tmp_path, _THREE_DEAD)
    r = compile_objective(str(tmp_path), apply=True, verify=False)
    md = render_compile_markdown(r)
    assert "Objective compile" in md
    assert "Fitness 2 → **0**" in md
    assert "drop never-read parameter" in md
