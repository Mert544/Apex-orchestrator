from __future__ import annotations

from app.tools.code_metrics import CodeMetrics, ModuleMetrics


def test_measures_loc_symbols_complexity(tmp_path):
    (tmp_path / "m.py").write_text(
        "# a comment\n"
        "\n"
        "import os\n"
        "def f(x):\n"
        "    if x:\n"
        "        for i in range(x):\n"
        "            pass\n"
        "class C:\n"
        "    pass\n",
        encoding="utf-8",
    )
    m = CodeMetrics(tmp_path).for_module("m.py")
    assert isinstance(m, ModuleMetrics)
    # Blank + comment-only lines are excluded from LOC.
    assert m.loc == 7
    assert m.symbols == 2          # f + C
    assert m.complexity == 2       # if + for


def test_non_python_and_missing_return_none(tmp_path):
    assert CodeMetrics(tmp_path).for_module("notes.txt") is None
    assert CodeMetrics(tmp_path).for_module("") is None
    assert CodeMetrics(tmp_path).for_module("ghost.py") is None


def test_unparseable_file_still_reports_loc(tmp_path):
    (tmp_path / "broken.py").write_text("def oops(:\n    pass\n", encoding="utf-8")
    m = CodeMetrics(tmp_path).for_module("broken.py")
    assert m is not None
    assert m.loc == 2
    assert m.symbols == 0 and m.complexity == 0


def test_for_modules_batches_and_dedupes(tmp_path):
    (tmp_path / "a.py").write_text("def a():\n    return 1\n")
    (tmp_path / "b.py").write_text("def b():\n    return 2\n")
    out = CodeMetrics(tmp_path).for_modules(["a.py", "a.py", "b.py", "missing.py"])
    assert set(out) == {"a.py", "b.py"}
    assert out["a.py"].to_dict()["symbols"] == 1


def test_comprehension_and_bool_op_count_as_complexity(tmp_path):
    (tmp_path / "c.py").write_text(
        "def f(xs):\n"
        "    ys = [x for x in xs if x]\n"
        "    return xs and ys\n",
        encoding="utf-8",
    )
    m = CodeMetrics(tmp_path).for_module("c.py")
    # comprehension + its `if` + the BoolOp -> at least 2 branch nodes.
    assert m.complexity >= 2
