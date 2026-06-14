from __future__ import annotations

import json
from pathlib import Path

from app.engine.objective_compiler import (
    CompileResult,
    CompileStep,
    _content_plan,
    available_objectives,
    comprehension_fitness,
    compile_all,
    compile_objective,
    dream_confluence_modules,
    import_sort_fitness,
    render_all_markdown,
    render_compile_markdown,
    render_from_dream_markdown,
    unused_import_fitness,
)
from app.engine.objective_compiler import (
    _comprehension_moves,
    _import_sort_moves,
    _unused_import_moves,
)


def _project(tmp_path: Path, body: str, rel: str = "app/m.py") -> Path:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / rel).write_text(body, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


# --- the lesser-covered objective fitness + move generators ------------------

def test_import_sort_fitness_and_move(tmp_path):
    _project(tmp_path, "import sys\nimport os\n\n\ndef f():\n    return os.getcwd() + sys.argv[0]\n")
    assert import_sort_fitness(str(tmp_path)) == 1.0
    moves = _import_sort_moves(str(tmp_path))
    assert [m.operator for m in moves] == ["sort_imports"]
    assert moves[0].target == "app/m.py:sort-imports"


def test_comprehension_fitness_and_move(tmp_path):
    _project(
        tmp_path,
        "def f(xs):\n    out = []\n    for x in xs:\n        out.append(x + 1)\n    return out\n",
    )
    assert comprehension_fitness(str(tmp_path)) == 1.0
    moves = _comprehension_moves(str(tmp_path))
    assert [m.operator for m in moves] == ["simplify_comprehension"]
    assert moves[0].target == "app/m.py:comprehension"


def test_unused_import_fitness_and_move(tmp_path):
    _project(tmp_path, "import os\n\n\ndef f():\n    return 1\n")
    assert unused_import_fitness(str(tmp_path)) == 1.0
    moves = _unused_import_moves(str(tmp_path))
    assert [m.operator for m in moves] == ["remove_unused_imports"]
    assert moves[0].target == "app/m.py:unused-import"


def test_clean_module_has_zero_fitness_for_lesser_objectives(tmp_path):
    _project(tmp_path, "def f(x):\n    return x + 1\n")
    assert import_sort_fitness(str(tmp_path)) == 0.0
    assert comprehension_fitness(str(tmp_path)) == 0.0
    assert unused_import_fitness(str(tmp_path)) == 0.0


# --- _content_plan error paths -----------------------------------------------

def test_content_plan_unreadable_file_returns_empty_plan(tmp_path):
    # OSError reading a missing file -> a plan with no contents and no blockers.
    def never_called(rel, src, title):  # pragma: no cover - must not run
        raise AssertionError("apply_fn should not run when the read fails")

    plan = _content_plan(str(tmp_path), "app/missing.py", never_called, "title")
    assert plan.new_contents == {}
    assert plan.blockers == []


def test_content_plan_transform_raises_returns_empty_plan(tmp_path):
    _project(tmp_path, "x = 1\n")

    def boom(rel, src, title):
        raise ValueError("transform exploded")

    plan = _content_plan(str(tmp_path), "app/m.py", boom, "title")
    assert plan.new_contents == {}


def test_content_plan_no_change_returns_empty_plan(tmp_path):
    _project(tmp_path, "x = 1\n")

    class _Res:
        patch_requests = [{"new_content": "x = 1\n"}]  # identical to source

    plan = _content_plan(str(tmp_path), "app/m.py", lambda r, s, t: _Res(), "title")
    assert plan.new_contents == {}  # new == source -> no edit recorded


def test_content_plan_records_a_real_change(tmp_path):
    _project(tmp_path, "x = 1\n")

    class _Res:
        patch_requests = [{"new_content": "x = 2\n"}]

    plan = _content_plan(str(tmp_path), "app/m.py", lambda r, s, t: _Res(), "title")
    assert plan.new_contents["app/m.py"] == "x = 2\n"
    assert plan.originals["app/m.py"] == "x = 1\n"
    assert plan.edits_by_file["app/m.py"] == 1


# --- dream confluence reading: every degenerate branch -----------------------

def test_dream_confluence_no_file_returns_empty(tmp_path):
    assert dream_confluence_modules(str(tmp_path)) == []


def test_dream_confluence_bad_json_returns_empty(tmp_path):
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "dream-promotions.json").write_text("not json{", encoding="utf-8")
    assert dream_confluence_modules(str(tmp_path)) == []


def test_dream_confluence_non_list_payload_returns_empty(tmp_path):
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "dream-promotions.json").write_text(
        json.dumps({"key": "confluence:app/m.py"}), encoding="utf-8")
    assert dream_confluence_modules(str(tmp_path)) == []


def test_dream_confluence_skips_nondict_and_missing_and_nonconfluence(tmp_path):
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "dream-promotions.json").write_text(json.dumps([
        "not-a-dict",
        {"key": "other:app/x.py"},          # wrong prefix
        {"key": "confluence:app/gone.py"},   # module doesn't exist
    ]), encoding="utf-8")
    assert dream_confluence_modules(str(tmp_path)) == []


def test_dream_confluence_returns_existing_modules_sorted_and_deduped(tmp_path):
    _project(tmp_path, "x = 1\n", rel="app/b.py")
    _project(tmp_path, "y = 1\n", rel="app/a.py")
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "dream-promotions.json").write_text(json.dumps([
        {"key": "confluence:app/b.py"},
        {"key": "confluence:app/a.py"},
        {"key": "confluence:app/b.py"},  # duplicate
    ]), encoding="utf-8")
    assert dream_confluence_modules(str(tmp_path)) == ["app/a.py", "app/b.py"]


# --- rendering branches ------------------------------------------------------

def test_render_compile_markdown_blocked_only(tmp_path):
    r = CompileResult(objective="dead-params", fitness_start=3.0, fitness_end=3.0,
                      blocked=["app/m.py: precondition failed"])
    md = render_compile_markdown(r)
    assert "_No improving move available. Fitness: 3._" in md
    assert "## Blocked" in md
    assert "app/m.py: precondition failed" in md


def test_render_compile_markdown_truncates_blocked_to_ten(tmp_path):
    r = CompileResult(objective="x", fitness_start=20.0, fitness_end=20.0,
                      blocked=[f"app/m{n}.py: nope" for n in range(15)])
    md = render_compile_markdown(r)
    assert md.count("- ⛔") == 10  # only the first ten are rendered


def test_render_all_markdown_empty():
    assert "Nothing to do" in render_all_markdown([])


def test_render_all_markdown_aggregates_results():
    step = CompileStep(operator="drop_param", target="app/m.py:f(x)",
                       description="drop x", fitness_before=2.0, fitness_after=1.0,
                       verified=True)
    r = CompileResult(objective="dead-params", fitness_start=2.0, fitness_end=1.0,
                      steps=[step], applied=True)
    md = render_all_markdown([r])
    assert "1 with work" in md
    assert "1 verified move(s)" in md


def test_render_from_dream_markdown_empty_modules():
    assert "graduated no confluence" in render_from_dream_markdown([], [])


def test_render_from_dream_markdown_lists_each_module():
    r = CompileResult(objective="dead-params", fitness_start=1.0, fitness_end=0.0)
    md = render_from_dream_markdown([r], ["app/hub.py"])
    assert "1 confluence module(s)" in md
    assert "`app/hub.py`" in md


# --- dataclass serialization + improved property -----------------------------

def test_compile_step_to_dict_roundtrips_fields():
    s = CompileStep(operator="inline", target="app/m.py:h()", description="fold h",
                    fitness_before=4.0, fitness_after=3.0, verified=True)
    d = s.to_dict()
    assert d == {"operator": "inline", "target": "app/m.py:h()", "description": "fold h",
                 "fitness_before": 4.0, "fitness_after": 3.0, "verified": True}


def test_compile_result_to_dict_and_improved():
    s = CompileStep(operator="drop_param", target="app/m.py:f(x)", description="d",
                    fitness_before=2.0, fitness_after=1.0)
    r = CompileResult(objective="dead-params", fitness_start=2.0, fitness_end=1.0,
                      steps=[s], blocked=["b"], applied=True)
    d = r.to_dict()
    assert d["improved"] is True
    assert d["moves_applied"] == 1
    assert d["steps"][0]["operator"] == "drop_param"
    assert d["blocked"] == ["b"]


def test_compile_result_not_improved_when_flat():
    r = CompileResult(objective="x", fitness_start=2.0, fitness_end=2.0)
    assert r.improved is False


# --- objective registry surface ----------------------------------------------

def test_available_objectives_contains_builtins():
    names = available_objectives()
    for n in ("dead-params", "sort-imports", "remove-unused-imports",
              "simplify-comprehension", "modernize"):
        assert n in names


def test_move_rolled_back_when_suite_fails_is_blocked_with_reason(tmp_path):
    # A real dead-param move exists, but the project's suite fails, so each
    # verified apply rolls back and is recorded as blocked with the suite reason.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def render(text, color=None, width=80):\n    return text[:width]\n"
        "def use():\n    return render('hi', width=3)\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "def test_fail():\n    assert False\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    r = compile_objective(str(tmp_path), objective="dead-params",
                          apply=True, verify=True, max_steps=2)
    assert r.steps == []
    assert any("render(color)" in b for b in r.blocked)


def test_compile_all_skips_objectives_already_at_zero(tmp_path):
    # A clean project has no work for any objective -> empty sweep.
    _project(tmp_path, "def f(x):\n    return x + 1\n")
    results = compile_all(str(tmp_path), apply=False, verify=False)
    assert all(isinstance(r, CompileResult) for r in results)
    assert all(r.steps == [] for r in results)
