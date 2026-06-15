from __future__ import annotations

from pathlib import Path

from app.tools.function_length import (
    FunctionLength,
    _function_loc,
    analyze_function_length,
)


def _write(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _loc_of(source: str, name: str = "f") -> int:
    """Parse ``source`` and return the body LOC of the function named ``name``.

    Drives the rule-pinning tests directly against ``_function_loc`` so the
    documented counting rule is verified in isolation.
    """
    import ast

    tree = ast.parse(source)
    lines = source.splitlines()
    node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )
    return _function_loc(node, lines)


# --------------------------------------------------------------------------- #
# LOC-counting rule, pinned with explicit small cases.
# --------------------------------------------------------------------------- #


def test_loc_counts_only_body_statements():
    # def line excluded; three body statements counted.
    source = (
        "def f(x):\n"
        "    a = x + 1\n"
        "    b = a * 2\n"
        "    return b\n"
    )
    assert _loc_of(source) == 3


def test_loc_excludes_blank_lines():
    source = (
        "def f():\n"
        "    a = 1\n"
        "\n"
        "    \n"
        "    b = 2\n"
        "    return a + b\n"
    )
    # 3 real lines; the two blank lines do not count.
    assert _loc_of(source) == 3


def test_loc_excludes_comment_only_lines():
    source = (
        "def f():\n"
        "    # set up\n"
        "    a = 1\n"
        "    # add\n"
        "    return a + 1\n"
    )
    # Two comment-only lines excluded -> 2 real lines.
    assert _loc_of(source) == 2


def test_loc_excludes_leading_docstring_single_line():
    source = (
        "def f():\n"
        '    """One-line doc."""\n'
        "    a = 1\n"
        "    return a\n"
    )
    assert _loc_of(source) == 2


def test_loc_excludes_multiline_docstring_every_line():
    source = (
        "def f():\n"
        '    """\n'
        "    A docstring\n"
        "    spanning lines.\n"
        '    """\n'
        "    a = 1\n"
        "    return a\n"
    )
    # All 4 docstring physical lines excluded -> 2 real body lines.
    assert _loc_of(source) == 2


def test_loc_docstring_only_body_is_zero():
    source = (
        "def f():\n"
        '    """Just a doc, no code."""\n'
    )
    assert _loc_of(source) == 0


def test_loc_one_liner_pass():
    source = "def f(): pass\n"
    assert _loc_of(source) == 1


def test_loc_ellipsis_stub():
    source = "def f(): ...\n"
    assert _loc_of(source) == 1


def test_loc_inner_docstring_string_not_treated_as_docstring():
    # A string expression that is NOT the first statement is a real body line.
    source = (
        "def f():\n"
        "    a = 1\n"
        '    "this is just an expression"\n'
        "    return a\n"
    )
    assert _loc_of(source) == 3


# --------------------------------------------------------------------------- #
# analyze_function_length aggregation.
# --------------------------------------------------------------------------- #


def _make_fn(name: str, body_lines: int) -> str:
    body = "\n".join(f"    x{i} = {i}" for i in range(body_lines))
    return f"def {name}():\n{body}\n"


def test_threshold_count(tmp_path: Path):
    # One function of 60 body lines (> 50), one of 10 (<= 50).
    big = _make_fn("big", 60)
    small = _make_fn("small", 10)
    _write(tmp_path / "app" / "m.py", big + "\n" + small)

    result = analyze_function_length(tmp_path, threshold=50)
    assert result.threshold == 50
    assert result.total_functions == 2
    assert result.over_threshold == 1
    assert result.max == 60


def test_threshold_is_configurable(tmp_path: Path):
    _write(tmp_path / "app" / "m.py", _make_fn("mid", 30))
    over = analyze_function_length(tmp_path, threshold=20)
    under = analyze_function_length(tmp_path, threshold=40)
    assert over.over_threshold == 1
    assert under.over_threshold == 0


def test_histogram_buckets(tmp_path: Path):
    src = (
        _make_fn("tiny", 5)       # 0-10
        + "\n" + _make_fn("smol", 20)   # 11-25
        + "\n" + _make_fn("mid", 40)    # 26-50
        + "\n" + _make_fn("big", 75)    # 51-100
        + "\n" + _make_fn("huge", 150)  # 100+
    )
    _write(tmp_path / "app" / "m.py", src)
    result = analyze_function_length(tmp_path)
    assert result.histogram == {
        "0-10": 1,
        "11-25": 1,
        "26-50": 1,
        "51-100": 1,
        "100+": 1,
    }
    # Histogram totals reconcile with the function count.
    assert sum(result.histogram.values()) == result.total_functions == 5


def test_mean_median_max(tmp_path: Path):
    # Bodies of 10, 20, 30 -> mean 20, median 20, max 30.
    src = (
        _make_fn("a", 10)
        + "\n" + _make_fn("b", 20)
        + "\n" + _make_fn("c", 30)
    )
    _write(tmp_path / "app" / "m.py", src)
    result = analyze_function_length(tmp_path)
    assert result.max == 30
    assert result.mean == 20.0
    assert result.median == 20.0


def test_median_even_count_averages_middle_two(tmp_path: Path):
    # Bodies of 10 and 20 -> median is the average 15.0.
    src = _make_fn("a", 10) + "\n" + _make_fn("b", 20)
    _write(tmp_path / "app" / "m.py", src)
    result = analyze_function_length(tmp_path)
    assert result.median == 15.0


def test_longest_ordering_and_fields(tmp_path: Path):
    src = (
        _make_fn("short", 5)
        + "\n" + _make_fn("longest", 90)
        + "\n" + _make_fn("middle", 40)
    )
    _write(tmp_path / "app" / "pkg" / "mod.py", src)
    result = analyze_function_length(tmp_path)

    names = [e["function"] for e in result.longest]
    assert names == ["longest", "middle", "short"]
    top = result.longest[0]
    assert set(top) == {"module", "function", "loc"}
    assert top["module"] == "app.pkg.mod"
    assert top["loc"] == 90


def test_longest_tiebreak_by_module_then_function(tmp_path: Path):
    # Two functions of equal LOC: ordered by (module, function).
    _write(tmp_path / "app" / "b.py", _make_fn("zeta", 12))
    _write(tmp_path / "app" / "a.py", _make_fn("alpha", 12))
    result = analyze_function_length(tmp_path)
    ordered = [(e["module"], e["function"]) for e in result.longest]
    assert ordered == [("app.a", "alpha"), ("app.b", "zeta")]


def test_longest_capped_at_15(tmp_path: Path):
    src = "\n".join(_make_fn(f"f{i:02d}", 60 + i) for i in range(25))
    _write(tmp_path / "app" / "m.py", src)
    result = analyze_function_length(tmp_path)
    assert result.total_functions == 25
    assert len(result.longest) == 15
    # Descending by loc.
    locs = [e["loc"] for e in result.longest]
    assert locs == sorted(locs, reverse=True)


def test_methods_are_class_qualified(tmp_path: Path):
    source = (
        "class Service:\n"
        "    def run(self):\n"
        "        a = 1\n"
        "        return a\n"
    )
    _write(tmp_path / "app" / "svc.py", source)
    result = analyze_function_length(tmp_path)
    assert result.longest[0]["function"] == "Service.run"


# --------------------------------------------------------------------------- #
# Empty-safety, exclusions, robustness, determinism.
# --------------------------------------------------------------------------- #


def test_empty_tree_is_safe(tmp_path: Path):
    result = analyze_function_length(tmp_path)
    assert isinstance(result, FunctionLength)
    assert result.total_functions == 0
    assert result.over_threshold == 0
    assert result.mean == 0.0
    assert result.median == 0.0
    assert result.max == 0
    assert result.longest == []
    assert result.histogram == {
        "0-10": 0, "11-25": 0, "26-50": 0, "51-100": 0, "100+": 0,
    }


def test_missing_root_is_safe(tmp_path: Path):
    result = analyze_function_length(tmp_path / "does-not-exist")
    assert result.total_functions == 0
    assert result.longest == []


def test_file_with_no_functions_is_safe(tmp_path: Path):
    _write(tmp_path / "app" / "consts.py", "X = 1\nY = 2\n")
    result = analyze_function_length(tmp_path)
    assert result.total_functions == 0


def test_fixtures_and_tests_excluded(tmp_path: Path):
    _write(tmp_path / "app" / "real.py", _make_fn("real_fn", 70))
    _write(tmp_path / "tests" / "test_thing.py", _make_fn("test_fn", 80))
    _write(tmp_path / "app" / "test_helper.py", _make_fn("helper", 80))
    _write(tmp_path / "examples" / "demo.py", _make_fn("demo", 80))
    _write(tmp_path / "fixtures" / "fx.py", _make_fn("fx", 80))

    result = analyze_function_length(tmp_path)
    assert result.total_functions == 1
    assert result.longest[0]["function"] == "real_fn"


def test_skipped_dirs_excluded(tmp_path: Path):
    _write(tmp_path / "app" / "real.py", _make_fn("real_fn", 12))
    # iter_source_files prunes these, but assert the result anyway.
    _write(tmp_path / ".venv" / "lib.py", _make_fn("vendored", 99))
    _write(tmp_path / "node_modules" / "pkg.py", _make_fn("npm_fn", 99))

    result = analyze_function_length(tmp_path)
    assert result.total_functions == 1
    assert result.longest[0]["function"] == "real_fn"


def test_unparsable_file_is_skipped(tmp_path: Path):
    _write(tmp_path / "app" / "good.py", _make_fn("good", 15))
    _write(tmp_path / "app" / "broken.py", "def oops(:\n    pass\n")
    result = analyze_function_length(tmp_path)
    assert result.total_functions == 1
    assert result.longest[0]["function"] == "good"


def test_max_files_cap(tmp_path: Path):
    for i in range(5):
        _write(tmp_path / "app" / f"m{i}.py", _make_fn(f"fn{i}", 10))
    capped = analyze_function_length(tmp_path, max_files=2)
    full = analyze_function_length(tmp_path, max_files=500)
    assert capped.total_functions == 2
    assert full.total_functions == 5


def test_async_functions_counted(tmp_path: Path):
    source = (
        "async def fetch():\n"
        "    a = 1\n"
        "    return a\n"
    )
    _write(tmp_path / "app" / "io.py", source)
    result = analyze_function_length(tmp_path)
    assert result.total_functions == 1
    assert result.longest[0]["function"] == "fetch"
    assert result.longest[0]["loc"] == 2


def test_determinism(tmp_path: Path):
    src = (
        _make_fn("a", 80)
        + "\n" + _make_fn("b", 40)
        + "\n" + _make_fn("c", 12)
    )
    _write(tmp_path / "app" / "x.py", src)
    _write(tmp_path / "app" / "y.py", _make_fn("d", 55))

    first = analyze_function_length(tmp_path)
    second = analyze_function_length(tmp_path)
    assert first == second
    assert first.longest == second.longest
    assert first.histogram == second.histogram
