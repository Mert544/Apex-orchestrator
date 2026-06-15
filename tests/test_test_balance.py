from __future__ import annotations

from pathlib import Path

from app.tools.test_balance import (
    TestBalance,
    analyze_test_balance,
    is_test_file,
)


def _make_project(root: Path) -> None:
    """Plant a synthetic project with known prod + test files.

    Layout:
      app/                  -- production package with a covering test dir
        core.py             (2 prod funcs, 4 LOC; comment line not counted)
        util.py             (1 prod func, 2 LOC)
        tests/test_core.py  (1 test func, 2 LOC)
      lonely/               -- prod code, NO tests  -> under-tested, ratio 0
        thing.py            (1 prod func, 2 LOC)
      tests/test_util.py    (top-level test dir, 1 test func, 2 LOC)

    Also plants a .claude worktree COPY that must never be counted.
    """
    (root / "app" / "tests").mkdir(parents=True)
    (root / "lonely").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / ".claude" / "worktrees" / "wt" / "app").mkdir(parents=True)

    (root / "app" / "core.py").write_text(
        "# a comment line that must not count\n"
        "def a():\n"
        "    return 1\n"
        "def b():\n"
        "    return 2\n",
        encoding="utf-8",
    )
    (root / "app" / "util.py").write_text(
        "def helper():\n"
        "    return 3\n",
        encoding="utf-8",
    )
    (root / "app" / "tests" / "test_core.py").write_text(
        "def test_a():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    (root / "lonely" / "thing.py").write_text(
        "def lonely():\n"
        "    return 4\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_util.py").write_text(
        "def test_helper():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    # A full-repo worktree copy: prod + test that must never count anywhere.
    (root / ".claude" / "worktrees" / "wt" / "app" / "copy.py").write_text(
        "def copy():\n    return 0\n", encoding="utf-8"
    )
    (root / ".claude" / "worktrees" / "wt" / "app" / "test_copy.py").write_text(
        "def test_copy():\n    assert True\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# detection rule
# --------------------------------------------------------------------------- #

def test_is_test_file_recognizes_conventions():
    assert is_test_file("tests/test_x.py")           # top-level tests dir
    assert is_test_file("app/foo/tests/x.py")        # nested tests dir
    assert is_test_file("app/test_foo.py")           # test_*.py basename
    assert is_test_file("app/foo_test.py")           # *_test.py basename
    assert is_test_file("App/TESTS/X.py")            # case-insensitive


def test_is_test_file_rejects_production():
    assert not is_test_file("app/foo.py")
    assert not is_test_file("app/testing.py")        # not test_ / _test
    assert not is_test_file("app/contest.py")        # 'test' as a substring only


# --------------------------------------------------------------------------- #
# core counts & ratios
# --------------------------------------------------------------------------- #

def test_known_counts_and_ratios(tmp_path: Path):
    _make_project(tmp_path)
    bal = analyze_test_balance(tmp_path)

    # Production: core (4) + util (2) + lonely/thing (2) = 8 LOC, 3 files,
    # 2 + 1 + 1 = 4 functions.
    assert bal.prod_loc == 8
    assert bal.prod_files == 3
    assert bal.prod_functions == 4

    # Tests: test_core (2) + test_util (2) = 4 LOC, 2 files, 2 test functions.
    assert bal.test_loc == 4
    assert bal.test_files == 2
    assert bal.test_functions == 2

    # Ratios are test/prod and division-safe.
    assert bal.loc_ratio == round(4 / 8, 4)
    assert bal.file_ratio == round(2 / 3, 4)
    assert bal.function_ratio == round(2 / 4, 4)


def test_worktree_copies_are_excluded(tmp_path: Path):
    _make_project(tmp_path)
    bal = analyze_test_balance(tmp_path)
    # If the .claude worktree copy leaked in, prod_files would be 4, not 3.
    assert bal.prod_files == 3
    assert bal.test_files == 2


# --------------------------------------------------------------------------- #
# per-package under-tested ranking
# --------------------------------------------------------------------------- #

def test_untested_package_flagged_ratio_zero(tmp_path: Path):
    _make_project(tmp_path)
    bal = analyze_test_balance(tmp_path)

    by_pkg = {row["package"]: row for row in bal.under_tested_packages}
    # Only packages with production code appear; both do here.
    assert set(by_pkg) == {"app", "lonely"}

    # 'lonely' has prod code but no tests -> ratio 0, sorted first.
    assert bal.under_tested_packages[0]["package"] == "lonely"
    assert by_pkg["lonely"]["ratio"] == 0.0
    assert by_pkg["lonely"]["test_loc"] == 0
    assert by_pkg["lonely"]["prod_loc"] == 2

    # 'app' has both prod (core+util = 6) and test (2) LOC under it.
    assert by_pkg["app"]["prod_loc"] == 6
    assert by_pkg["app"]["test_loc"] == 2
    assert by_pkg["app"]["ratio"] == round(2 / 6, 4)


def test_packages_sorted_ascending_by_ratio(tmp_path: Path):
    _make_project(tmp_path)
    bal = analyze_test_balance(tmp_path)
    ratios = [row["ratio"] for row in bal.under_tested_packages]
    assert ratios == sorted(ratios)


def test_top_level_test_dir_has_no_production_package(tmp_path: Path):
    _make_project(tmp_path)
    bal = analyze_test_balance(tmp_path)
    # The top-level `tests/` dir is purely tests; it must not appear as a
    # production package in the ranking.
    assert "tests" not in {row["package"] for row in bal.under_tested_packages}


# --------------------------------------------------------------------------- #
# empty / edge / determinism
# --------------------------------------------------------------------------- #

def test_empty_project_is_safe(tmp_path: Path):
    bal = analyze_test_balance(tmp_path)
    assert isinstance(bal, TestBalance)
    assert bal.test_loc == 0
    assert bal.prod_loc == 0
    assert bal.loc_ratio == 0.0      # no division by zero
    assert bal.file_ratio == 0.0
    assert bal.function_ratio == 0.0
    assert bal.under_tested_packages == []


def test_tests_only_no_production(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8"
    )
    bal = analyze_test_balance(tmp_path)
    assert bal.test_files == 1
    assert bal.prod_files == 0
    # Division by zero prod must stay safe.
    assert bal.loc_ratio == 0.0
    assert bal.file_ratio == 0.0
    # No production code -> nothing can be under-tested.
    assert bal.under_tested_packages == []


def test_unparseable_file_counts_loc_not_functions(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "broken.py").write_text(
        "def oops(:\n    pass\n", encoding="utf-8"
    )
    bal = analyze_test_balance(tmp_path)
    assert bal.prod_files == 1
    assert bal.prod_loc == 2          # lines still counted
    assert bal.prod_functions == 0    # but no AST -> no functions


def test_max_files_cap_is_respected(tmp_path: Path):
    (tmp_path / "app").mkdir()
    for i in range(5):
        (tmp_path / "app" / f"m{i}.py").write_text(
            "def f():\n    return 1\n", encoding="utf-8"
        )
    bal = analyze_test_balance(tmp_path, max_files=2)
    assert bal.prod_files == 2


def test_determinism(tmp_path: Path):
    _make_project(tmp_path)
    first = analyze_test_balance(tmp_path).to_dict()
    second = analyze_test_balance(tmp_path).to_dict()
    assert first == second


def test_to_dict_round_trips_fields(tmp_path: Path):
    _make_project(tmp_path)
    bal = analyze_test_balance(tmp_path)
    d = bal.to_dict()
    assert d["test_loc"] == bal.test_loc
    assert d["under_tested_packages"] == bal.under_tested_packages
    # to_dict copies, so mutating the dict must not touch the dataclass.
    d["under_tested_packages"].append({"package": "x"})
    assert len(bal.under_tested_packages) != len(d["under_tested_packages"])
