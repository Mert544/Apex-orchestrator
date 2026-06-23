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


# --- second objective: inline single-use helpers -----------------------------

def _inline_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def double(x):\n    return x * 2\n\n\n"
        "def triple(y):\n    return y * 3\n\n\n"
        "def use():\n    return double(5) + triple(2)\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import use\ndef test_use():\n    assert use() == 16\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_inline_fitness_counts_single_use_helpers(tmp_path):
    from app.engine.objective_compiler import inlinable_helper_fitness
    _inline_project(tmp_path)
    # double, triple, use are all single-use → 3.
    assert inlinable_helper_fitness(str(tmp_path)) == 3.0


def test_inline_objective_folds_internal_helpers(tmp_path):
    _inline_project(tmp_path)
    r = compile_objective(str(tmp_path), objective="inline-helpers", apply=True, verify=False)
    # double and triple fold into use(); use() itself is preserved (test-only caller).
    assert len(r.steps) == 2
    assert {s.operator for s in r.steps} == {"inline"}
    src = (tmp_path / "app" / "m.py").read_text()
    assert "def double" not in src and "def triple" not in src
    assert "def use" in src  # the public surface survives


def test_inline_objective_will_not_dissolve_a_public_function_into_a_test(tmp_path):
    # A function whose ONLY caller is a test must never be inlined away — that
    # would empty its module and move real code into a test assertion.
    _inline_project(tmp_path)
    r = compile_objective(str(tmp_path), objective="inline-helpers", apply=True, verify=False)
    assert any("test/fixture" in b for b in r.blocked)
    assert r.fitness_end >= 1.0  # use() remains, honestly counted


def test_inline_objective_dry_run_lists_only_safe_moves(tmp_path):
    _inline_project(tmp_path)
    before = (tmp_path / "app" / "m.py").read_text()
    r = compile_objective(str(tmp_path), objective="inline-helpers", apply=False)
    # Dry run lists the safe folds and never writes.
    assert (tmp_path / "app" / "m.py").read_text() == before
    assert any(s.operator == "inline" for s in r.steps)


# --- dream -> action: scoped campaigns from the nightly discovery -------------

import json as _json


def _dream_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".apex").mkdir()
    (tmp_path / "app" / "hub.py").write_text(
        "def render(text, color=None, width=80):\n    return text[:width]\n", encoding="utf-8")
    (tmp_path / "app" / "other.py").write_text(
        "def fetch(url, retries=3):\n    return url\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.hub import render\nfrom app.other import fetch\n"
        "def test_all():\n    assert render('hi', width=2) == 'hi'\n"
        "    assert fetch('u') == 'u'\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    (tmp_path / ".apex" / "dream-promotions.json").write_text(
        _json.dumps([{"key": "confluence:app/hub.py", "kind": "confluence", "streak": 20}]),
        encoding="utf-8")
    return tmp_path


def test_dream_confluence_modules_reads_promotions(tmp_path):
    from app.engine.dream_landing import dream_confluence_modules
    _dream_project(tmp_path)
    assert dream_confluence_modules(str(tmp_path)) == ["app/hub.py"]


def test_dream_confluence_modules_empty_when_no_store(tmp_path):
    from app.engine.dream_landing import dream_confluence_modules
    assert dream_confluence_modules(str(tmp_path)) == []


def test_dream_confluence_skips_nonexistent_modules(tmp_path):
    from app.engine.dream_landing import dream_confluence_modules
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "dream-promotions.json").write_text(
        _json.dumps([{"key": "confluence:app/ghost.py"}]), encoding="utf-8")
    assert dream_confluence_modules(str(tmp_path)) == []  # ghost.py doesn't exist


def test_scope_module_confines_the_campaign(tmp_path):
    _dream_project(tmp_path)
    # Scoped to hub.py: only its dead param is dropped; other.py is untouched.
    r = compile_objective(str(tmp_path), apply=True, verify=False, scope_module="app/hub.py")
    assert r.fitness_start == 1.0 and r.fitness_end == 0.0
    assert len(r.steps) == 1
    assert all(s.target.startswith("app/hub.py") for s in r.steps)
    assert "color" not in (tmp_path / "app" / "hub.py").read_text()
    assert "retries" in (tmp_path / "app" / "other.py").read_text()  # untouched


def test_compile_from_dream_cleans_only_confluence_modules(tmp_path):
    from app.engine.dream_landing import compile_from_dream
    _dream_project(tmp_path)
    results = compile_from_dream(str(tmp_path), apply=True, verify=False)
    assert len(results) == 1               # one confluence module
    assert results[0].fitness_end == 0.0
    # hub.py cleaned; other.py (not a confluence) left with its dead param.
    assert "color" not in (tmp_path / "app" / "hub.py").read_text()
    assert "retries" in (tmp_path / "app" / "other.py").read_text()


def test_compile_from_dream_empty_when_no_confluence(tmp_path):
    from app.engine.dream_landing import compile_from_dream
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
    assert compile_from_dream(str(tmp_path), apply=False) == []


def test_render_from_dream_markdown(tmp_path):
    from app.engine.dream_landing import (
        compile_from_dream, dream_confluence_modules,
    )
    from app.engine.objective_compiler import render_from_dream_markdown
    _dream_project(tmp_path)
    mods = dream_confluence_modules(str(tmp_path))
    md = render_from_dream_markdown(compile_from_dream(str(tmp_path), apply=False), mods)
    assert "Develop from dream" in md and "app/hub.py" in md


def test_render_from_dream_empty_message():
    from app.engine.objective_compiler import render_from_dream_markdown
    md = render_from_dream_markdown([], [])
    assert "graduated no confluence" in md


def test_cmd_develop_from_dream(tmp_path, capsys):
    import argparse
    from app.cli_autonomy import cmd_develop
    _dream_project(tmp_path)
    rc = cmd_develop(argparse.Namespace(
        target=str(tmp_path), objective="dead-params", from_dream=True,
        apply=True, max_steps=25, no_verify=True, json=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Develop from dream" in out and "app/hub.py" in out
    assert "color" not in (tmp_path / "app" / "hub.py").read_text()


# --- third objective: shrink long functions via extraction -------------------

def _long_fn_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    body = "\n".join(f"    s{i} = start + {i}" for i in range(45))
    (tmp_path / "app" / "m.py").write_text(
        f"def big(start):\n    total = start\n{body}\n    return total + s0\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import big\ndef test_big():\n    assert big(0) == 0\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_long_function_fitness_counts_seams(tmp_path):
    from app.engine.objective_compiler import long_function_fitness
    _long_fn_project(tmp_path)
    assert long_function_fitness(str(tmp_path)) == 1.0


def test_shrink_functions_extracts_one_clean_helper(tmp_path):
    _long_fn_project(tmp_path)
    r = compile_objective(str(tmp_path), objective="shrink-functions",
                          apply=True, verify=False, max_steps=5)
    assert r.fitness_end == 0.0
    src = (tmp_path / "app" / "m.py").read_text()
    defs = [ln for ln in src.splitlines() if ln.startswith("def ")]
    # Exactly one helper extracted; NO cascading _part_part nesting.
    assert "def _big_part(" in src
    assert not any("_part_part" in d for d in defs)
    assert {s.operator for s in r.steps} == {"extract"}


def test_shrink_functions_does_not_cascade_into_generated_helpers(tmp_path):
    # A function already named like the extractor's output is not re-targeted.
    from app.engine.objective_compiler import _extract_suggestions
    (tmp_path / "app").mkdir()
    body = "\n".join(f"    s{i} = x + {i}" for i in range(45))
    (tmp_path / "app" / "m.py").write_text(
        f"def _helper_part(x):\n    t = x\n{body}\n    return t\n", encoding="utf-8")
    # The only long function is a generated-helper-named one → no suggestions.
    assert _extract_suggestions(str(tmp_path)) == []


def test_shrink_functions_dry_run_does_not_write(tmp_path):
    _long_fn_project(tmp_path)
    before = (tmp_path / "app" / "m.py").read_text()
    r = compile_objective(str(tmp_path), objective="shrink-functions", apply=False)
    assert (tmp_path / "app" / "m.py").read_text() == before
    assert any(s.operator == "extract" for s in r.steps)


# --- fourth objective: modernize tidy debt (content transforms) --------------

def _tidy_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def check(x):\n    if x == None:\n        return dict()\n"
        "    msg = f\"done\"\n    return msg\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import check\ndef test_check():\n"
        "    assert check(None) == {}\n    assert check(1) == 'done'\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_modernize_fitness_counts_tidy_debt(tmp_path):
    from app.engine.objective_compiler import modernize_fitness
    _tidy_project(tmp_path)
    # == None + dead f-string + dict() = 3 tidy rewrites.
    assert modernize_fitness(str(tmp_path)) == 3.0


def test_modernize_objective_clears_all_tidy_debt(tmp_path):
    _tidy_project(tmp_path)
    r = compile_objective(str(tmp_path), objective="modernize", apply=True, verify=False)
    assert r.fitness_start == 3.0 and r.fitness_end == 0.0
    src = (tmp_path / "app" / "m.py").read_text()
    assert "is None" in src and "== None" not in src
    assert "return {}" in src and "dict()" not in src
    assert 'msg = "done"' in src  # f-prefix dropped


def test_modernize_dry_run_does_not_write(tmp_path):
    _tidy_project(tmp_path)
    before = (tmp_path / "app" / "m.py").read_text()
    r = compile_objective(str(tmp_path), objective="modernize", apply=False)
    assert (tmp_path / "app" / "m.py").read_text() == before
    assert len(r.steps) == 3


def test_compile_uses_sequence_memory_without_breaking(tmp_path):
    # With a composition-memory file present, the compiler orders candidate
    # moves by learned sequence preference — and still reaches the objective
    # (a regression guard that memory loading/ordering never breaks the loop).
    import json
    _tidy_project(tmp_path)
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "idea-memory.json").write_text(json.dumps({
        "by_operator": {}, "by_label": {},
        "by_sequence": {"modernize>fix_collection": {"applied": 5, "rolled_back": 0, "blocked": 0}},
    }), encoding="utf-8")
    r = compile_objective(str(tmp_path), objective="modernize", apply=True, verify=False)
    assert r.fitness_end == 0.0
    assert len(r.steps) == 3


# --- develop --all: sweep every objective -----------------------------------

def _multi_debt_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def render(text, color=None, width=80):\n"
        "    if text == None:\n        return dict()\n"
        "    msg = f\"out\"\n    return msg + text[:width]\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import render\ndef test_r():\n"
        "    assert render(None) == {}\n    assert render('hi', width=2) == 'outhi'\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_compile_all_sweeps_every_objective(tmp_path):
    from app.engine.objective_compiler import compile_all
    _multi_debt_project(tmp_path)
    results = compile_all(str(tmp_path), apply=True, verify=False)
    # modernize (3) + dead-params (1) had work; shrink/inline had none → skipped.
    objectives = {r.objective for r in results}
    assert "modernize" in objectives and "dead-params" in objectives
    src = (tmp_path / "app" / "m.py").read_text()
    assert "is None" in src and "return {}" in src and 'msg = "out"' in src
    assert "color" not in src


def test_compile_all_clean_project_has_no_work(tmp_path):
    from app.engine.objective_compiler import compile_all
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    assert compile_all(str(tmp_path), apply=True, verify=False) == []


def test_available_objectives_and_all_constant():
    from app.engine.objective_compiler import ALL_OBJECTIVES, available_objectives
    avail = available_objectives()
    assert set(ALL_OBJECTIVES) <= set(avail)
    assert "modernize" in avail and "dead-params" in avail


def test_render_all_markdown_and_empty():
    from app.engine.objective_compiler import render_all_markdown
    md = render_all_markdown([])
    assert "Nothing to do" in md


def test_cmd_develop_all_flag(tmp_path, capsys):
    import argparse
    from app.cli_autonomy import cmd_develop
    _multi_debt_project(tmp_path)
    rc = cmd_develop(argparse.Namespace(
        target=str(tmp_path), objective="dead-params", all_objectives=True,
        from_dream=False, playbook=False, apply=True, max_steps=25,
        no_verify=True, json=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "all objectives" in out.lower()
    assert "color" not in (tmp_path / "app" / "m.py").read_text()


# --- develop --grade: prove the gain -----------------------------------------

def test_cmd_develop_grade_proves_the_gain(tmp_path, capsys):
    import argparse
    from app.cli_autonomy import cmd_develop
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def render(text, color=None, width=80):\n"
        "    if text == None:\n        return dict()\n    return text[:width]\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import render\ndef test_r():\n"
        "    assert render(None) == {}\n    assert render('hi', width=2) == 'hi'\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    rc = cmd_develop(argparse.Namespace(
        target=str(tmp_path), objective="dead-params", all_objectives=True,
        from_dream=False, playbook=False, grade=True, apply=True,
        max_steps=25, no_verify=True, json=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Health grade:" in out and "↑" in out  # the grade rose


def test_grade_proof_silent_without_flag_or_changes(tmp_path, capsys):
    from app.cli_autonomy import _print_grade_proof
    # No baseline → nothing printed.
    _print_grade_proof(str(tmp_path), None, True)
    # Not applied → nothing printed.
    _print_grade_proof(str(tmp_path), 90, False)
    assert capsys.readouterr().out == ""


# --- development trajectory: dev_history wiring + apex shield -----------------

def _graded_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def render(text, color=None, width=80):\n"
        "    if text == None:\n        return dict()\n    return text[:width]\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import render\ndef test_r():\n"
        "    assert render(None) == {}\n    assert render('hi', width=2) == 'hi'\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_develop_grade_logs_to_dev_history(tmp_path, capsys):
    import argparse
    from app.cli_autonomy import cmd_develop
    from app.engine.dev_history import DevHistory
    _graded_project(tmp_path)
    cmd_develop(argparse.Namespace(
        target=str(tmp_path), objective="dead-params", all_objectives=True,
        from_dream=False, playbook=False, history=False, grade=True, apply=True,
        max_steps=25, no_verify=True, json=False))
    capsys.readouterr()
    hist = DevHistory.load(str(tmp_path))
    assert len(hist.runs) == 1 and hist.runs[0].delta > 0
    # --history renders the trajectory.
    cmd_develop(argparse.Namespace(
        target=str(tmp_path), objective="dead-params", all_objectives=False,
        from_dream=False, playbook=False, history=True, grade=False, apply=False,
        max_steps=25, no_verify=True, json=False))
    assert "Development history" in capsys.readouterr().out


def test_cmd_shield_generates_and_applies(tmp_path, capsys):
    import argparse
    from app.cli_autonomy import cmd_shield
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    # Preview: shows the test, writes nothing.
    rc = cmd_shield(argparse.Namespace(target=str(tmp_path), module="app/calc.py",
                                       apply=False, json=False))
    assert rc == 0
    assert "Characterization test" in capsys.readouterr().out
    assert not (tmp_path / "tests" / "test_calc.py").exists()
    # Apply: writes the test.
    rc = cmd_shield(argparse.Namespace(target=str(tmp_path), module="app/calc.py",
                                       apply=True, json=False))
    assert rc == 0
    assert (tmp_path / "tests" / "test_calc.py").exists()


def test_cmd_shield_needs_a_module(capsys):
    import argparse
    from app.cli_autonomy import cmd_shield
    rc = cmd_shield(argparse.Namespace(target="", module="", apply=False, json=False))
    assert rc == 1


# --- fifth objective: remove unreachable code (detection -> action) ----------

def test_remove_dead_code_objective(tmp_path):
    from app.engine.objective_compiler import dead_code_fitness
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def f(x):\n    return x\n    print('dead')\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import f\ndef test_f():\n    assert f(2) == 2\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    assert dead_code_fitness(str(tmp_path)) == 1.0
    r = compile_objective(str(tmp_path), objective="remove-dead-code",
                          apply=True, verify=False)
    assert r.fitness_end == 0.0 and len(r.steps) == 1
    src = (tmp_path / "app" / "m.py").read_text()
    assert "print('dead')" not in src and "return x" in src


def test_remove_dead_code_in_all_objectives():
    from app.engine.objective_compiler import ALL_OBJECTIVES, available_objectives
    assert "remove-dead-code" in ALL_OBJECTIVES
    assert "remove-dead-code" in available_objectives()


# --- apex shield --all: build the whole test safety net ----------------------

def _two_module_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "a.py").write_text("def add(x, y):\n    return x + y\n", encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text("def mul(x, y=2):\n    return x * y\n", encoding="utf-8")
    (tmp_path / "tests" / "test_a.py").write_text(
        "from app.a import add\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_shield_all_dry_run_lists_candidates(tmp_path, capsys):
    import argparse
    from app.cli_autonomy import cmd_shield
    _two_module_project(tmp_path)
    rc = cmd_shield(argparse.Namespace(target=str(tmp_path), module="", all_modules=True,
                                       apply=False, json=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "would build" in out and "app/b.py" in out  # b.py is untested
    assert not (tmp_path / "tests" / "test_b.py").exists()  # dry run writes nothing


def test_shield_all_apply_builds_verified_tests(tmp_path, capsys):
    import argparse
    from app.cli_autonomy import cmd_shield
    _two_module_project(tmp_path)
    rc = cmd_shield(argparse.Namespace(target=str(tmp_path), module="", all_modules=True,
                                       apply=True, json=False))
    assert rc == 0
    assert "Built" in capsys.readouterr().out
    # b.py got a written test that the verifier kept (it passes).
    assert (tmp_path / "tests" / "test_b.py").exists()


# --- sixth objective: dedup (extract copy-pasted blocks to a shared helper) ---

def test_dedup_objective_extracts_shared_helper(tmp_path):
    from app.engine.objective_compiler import duplication_fitness
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    block = "\n".join(["    acc = acc + n", "    acc = acc * 2", "    acc = acc + 1",
                       "    acc = acc - 3", "    acc = acc + 10"])
    (tmp_path / "app" / "m.py").write_text(
        f"def alpha(n):\n    acc = 0\n{block}\n    return acc + 100\n\n\n"
        f"def beta(n):\n    acc = 0\n{block}\n    return acc + 200\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import alpha, beta\ndef test_ab():\n"
        "    assert alpha(5) == 118\n    assert beta(5) == 218\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    assert duplication_fitness(str(tmp_path)) >= 1.0
    r = compile_objective(str(tmp_path), objective="dedup", apply=True, verify=False)
    assert any(s.operator == "dedup_extract" for s in r.steps)
    src = (tmp_path / "app" / "m.py").read_text()
    assert "_shared" in src  # a shared helper was created and called


def test_dedup_in_available_objectives():
    from app.engine.objective_compiler import available_objectives
    assert "dedup" in available_objectives()


# --- seventh objective: simplify boolean returns -----------------------------

def test_simplify_bool_return_objective(tmp_path):
    from app.engine.objective_compiler import bool_return_fitness
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def is_pos(x):\n    if x > 0:\n        return True\n    else:\n        return False\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import is_pos\ndef test_p():\n"
        "    assert is_pos(5) is True\n    assert is_pos(-1) is False\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    assert bool_return_fitness(str(tmp_path)) == 1.0
    r = compile_objective(str(tmp_path), objective="simplify-bool-return",
                          apply=True, verify=False)
    assert r.fitness_end == 0.0 and len(r.steps) == 1
    src = (tmp_path / "app" / "m.py").read_text()
    assert "return bool(x > 0)" in src and "return True" not in src


def test_simplify_bool_return_in_all_objectives():
    from app.engine.objective_compiler import ALL_OBJECTIVES
    assert "simplify-bool-return" in ALL_OBJECTIVES


# --- eighth objective: extract repeated magic literals to named constants -----

def test_extract_constant_objective(tmp_path):
    from app.engine.objective_compiler import magic_constant_fitness
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def a():\n    return 86400 * 2\n\n\ndef b():\n    return 86400 + 1\n\n\n"
        "def c():\n    return 86400 - 5\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import a, b, c\ndef test_abc():\n"
        "    assert a() == 172800 and b() == 86401 and c() == 86395\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    assert magic_constant_fitness(str(tmp_path)) == 1.0
    r = compile_objective(str(tmp_path), objective="extract-constant", apply=True, verify=False)
    assert any(s.operator == "extract_constant" for s in r.steps)
    import re
    src = (tmp_path / "app" / "m.py").read_text()
    assert "= 86400" in src  # the constant's definition (NAME = 86400)
    # The BARE literal 86400 (not part of the CONSTANT_86400 name) now appears
    # exactly once — only in the constant's definition.
    bare = re.findall(r"(?<![A-Za-z0-9_])86400(?![A-Za-z0-9_])", src)
    assert len(bare) == 1


def test_extract_constant_in_available_objectives():
    from app.engine.objective_compiler import available_objectives
    assert "extract-constant" in available_objectives()


# --- cached-parse reuse: fitness scans reuse the source index, not disk --------
# The dominant rank_objectives scans (extract-constant, shrink-functions,
# inline-helpers) read+parse every module ONCE via the source index instead of
# re-reading/re-parsing per module. These tests pin the optimization's contract:
# every result is byte-for-byte identical to the from-scratch (uncached) path.

def _mixed_debt_project(tmp_path: Path) -> Path:
    """A project carrying all three optimized debts at once: a repeated magic
    literal (extract-constant), a long function with a clean seam
    (shrink-functions), and a single-use helper (inline-helpers)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    body = "\n".join(f"    s{i} = start + {i}" for i in range(45))
    (tmp_path / "app" / "m.py").write_text(
        # long function with an extractable seam
        f"def big(start):\n    total = start\n{body}\n    return total + s0\n\n\n"
        # a repeated magic literal
        "def a():\n    return 86400 * 2\n\n\n"
        "def b():\n    return 86400 + 1\n\n\n"
        "def c():\n    return 86400 - 5\n\n\n"
        # a tiny single-use helper plus its one caller
        "def double(x):\n    return x * 2\n\n\n"
        "def use():\n    return double(5)\n", encoding="utf-8")
    (tmp_path / "app" / "other.py").write_text(
        "def plain(y):\n    return y + 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m, app.other\ndef test_import():\n"
        "    assert app.m is not None and app.other is not None\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _from_scratch_magic_constant_modules(root: str) -> list[str]:
    """Reference: the extract-constant scan WITHOUT any cached source — every
    plan reads from disk (the pre-optimization behavior)."""
    from app.engine.objective_compiler import _own_modules
    from app.execution.extract_constant import plan_extract_constant
    return [rel for rel, _src in _own_modules(root)
            if plan_extract_constant(root, rel).new_contents]


def _from_scratch_extract_suggestions(root: str) -> list[tuple[str, dict]]:
    """Reference: the shrink-functions scan re-parsing every module from its
    source text (the pre-optimization behavior)."""
    from app.engine.objective_compiler import _own_modules
    from app.execution.extract_method import suggest_extractions
    out: list[tuple[str, dict]] = []
    for rel, source in _own_modules(root):
        for seam in suggest_extractions(source):  # no tree → re-parse
            if not seam["function"].endswith("_part"):
                out.append((rel, seam))
    return out


def test_extract_constant_fitness_matches_from_scratch(tmp_path):
    from app.engine.objective_compiler import (
        _magic_constant_modules, magic_constant_fitness,
    )
    _mixed_debt_project(tmp_path)
    root = str(tmp_path)
    # The cached-source scan names exactly the modules the disk scan would.
    assert _magic_constant_modules(root) == _from_scratch_magic_constant_modules(root)
    assert magic_constant_fitness(root) == 1.0  # only m.py hides 86400


def test_extract_constant_plan_identical_with_explicit_source(tmp_path):
    # The optional `source=` argument must produce the byte-identical plan the
    # disk-read path produces — same bytes in, same plan out.
    from app.execution.extract_constant import plan_extract_constant
    _mixed_debt_project(tmp_path)
    root = str(tmp_path)
    src = (tmp_path / "app" / "m.py").read_text()
    disk = plan_extract_constant(root, "app/m.py")
    cached = plan_extract_constant(root, "app/m.py", source=src)
    assert disk.new_contents == cached.new_contents
    assert disk.blockers == cached.blockers
    assert disk.edits_by_file == cached.edits_by_file


def test_shrink_functions_fitness_matches_from_scratch(tmp_path):
    from app.engine.objective_compiler import (
        _extract_suggestions, long_function_fitness,
    )
    _mixed_debt_project(tmp_path)
    root = str(tmp_path)
    # Reusing the cached tree yields exactly the seams a fresh re-parse would.
    assert _extract_suggestions(root) == _from_scratch_extract_suggestions(root)
    assert long_function_fitness(root) == 1.0  # only big() has a clean seam


def test_suggest_extractions_tree_arg_matches_reparse(tmp_path):
    # Passing a pre-parsed tree is identical to letting it re-parse the source.
    import ast as _ast

    from app.execution.extract_method import suggest_extractions
    _mixed_debt_project(tmp_path)
    source = (tmp_path / "app" / "m.py").read_text()
    assert suggest_extractions(source, _ast.parse(source)) == suggest_extractions(source)


def test_inline_helper_fitness_matches_from_scratch(tmp_path):
    from app.engine.objective_compiler import inlinable_helper_fitness
    from app.execution.inline_function import suggest_inlines
    _mixed_debt_project(tmp_path)
    root = str(tmp_path)
    # The objective's count equals a direct from-scratch suggest_inlines scan
    # (the one-pass bare-object / call-site hoist preserves every suggestion).
    assert inlinable_helper_fitness(root) == float(len(suggest_inlines(root)))
    assert inlinable_helper_fitness(root) == 1.0  # only double() qualifies


def test_suggest_inlines_one_pass_matches_per_name_scan(tmp_path):
    # The hoisted whole-project scans (`_bare_object_names`,
    # `_call_site_counts`) must be EXACTLY the per-name helpers they replace.
    import ast as _ast

    from app.execution.inline_function import (
        _bare_object_names,
        _call_site_counts,
        _call_sites,
        _has_object_ref,
    )
    _mixed_debt_project(tmp_path)
    trees = {
        "app/m.py": _ast.parse((tmp_path / "app" / "m.py").read_text()),
        "app/other.py": _ast.parse((tmp_path / "app" / "other.py").read_text()),
    }
    bare = _bare_object_names(trees)
    counts = _call_site_counts(trees)
    for name in ("big", "a", "b", "c", "double", "use", "plain", "missing"):
        assert (name in bare) == _has_object_ref(trees, name)
        assert counts.get(name, 0) == len(_call_sites(trees, name))


def test_suggest_inlines_trees_arg_matches_disk_parse(tmp_path):
    # Handing in already-parsed trees yields the same suggestions as parsing the
    # project from disk (the default path).
    from app.execution.cross_file_rename import _py_files
    from app.execution.inline_function import suggest_inlines
    import ast as _ast
    _mixed_debt_project(tmp_path)
    root = str(tmp_path)
    trees = {}
    for rel, text in _py_files(tmp_path):
        try:
            trees[rel] = _ast.parse(text)
        except SyntaxError:
            pass
    assert suggest_inlines(root, trees) == suggest_inlines(root)


def test_optimized_fitness_on_empty_project(tmp_path):
    # The empty / no-debt path: no modules → zero fitness, no crash, and the
    # cached scans agree with the from-scratch scans (both empty).
    from app.engine.objective_compiler import (
        _extract_suggestions,
        _magic_constant_modules,
        inlinable_helper_fitness,
        long_function_fitness,
        magic_constant_fitness,
    )
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    root = str(tmp_path)
    assert magic_constant_fitness(root) == 0.0
    assert long_function_fitness(root) == 0.0
    assert inlinable_helper_fitness(root) == 0.0
    assert _magic_constant_modules(root) == _from_scratch_magic_constant_modules(root) == []
    assert _extract_suggestions(root) == _from_scratch_extract_suggestions(root) == []
