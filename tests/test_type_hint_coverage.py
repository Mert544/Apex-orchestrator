"""Tests for the deterministic type-hint coverage analyzer.

Covers the headline cases from the spec: a fully-annotated module scores 1.0,
an unannotated one scores low, a mixed one yields the exact fraction, empty /
degenerate trees return safe zero defaults (no ZeroDivisionError), repeated runs
are byte-for-byte identical, and test/fixture files are excluded from the score.
"""

from __future__ import annotations

from app.tools.type_hint_coverage import (
    TypeHintCoverage,
    analyze_type_hint_coverage,
)

FULLY_ANNOTATED = (
    "def add(a: int, b: int) -> int:\n"
    "    return a + b\n"
    "\n"
    "\n"
    "class C:\n"
    "    def m(self, x: str) -> str:\n"
    "        return x\n"
    "\n"
    "    def __init__(self) -> None:\n"
    "        self.v = 0\n"
)

UNANNOTATED = (
    "def add(a, b):\n"
    "    return a + b\n"
    "\n"
    "\n"
    "class C:\n"
    "    def m(self, x):\n"
    "        return x\n"
)


def test_fully_annotated_module_is_ratio_one(tmp_path):
    (tmp_path / "m.py").write_text(FULLY_ANNOTATED, encoding="utf-8")
    cov = analyze_type_hint_coverage(tmp_path)
    assert isinstance(cov, TypeHintCoverage)
    assert cov.overall_ratio == 1.0
    assert cov.total_functions == 3
    assert cov.annotated_functions == 3
    # A perfectly-annotated module is still listed, but at ratio 1.0.
    assert cov.worst_modules == [
        {"module": "m.py", "ratio": 1.0, "annotated": 3, "total": 3}
    ]


def test_unannotated_module_is_low(tmp_path):
    (tmp_path / "m.py").write_text(UNANNOTATED, encoding="utf-8")
    cov = analyze_type_hint_coverage(tmp_path)
    assert cov.overall_ratio == 0.0
    assert cov.total_functions == 2
    assert cov.annotated_functions == 0
    assert cov.worst_modules[0]["module"] == "m.py"
    assert cov.worst_modules[0]["ratio"] == 0.0


def test_mixed_module_yields_exact_fraction(tmp_path):
    # 1 fully annotated, 1 missing a param hint, 1 missing the return hint.
    src = (
        "def good(a: int) -> int:\n"
        "    return a\n"
        "\n"
        "\n"
        "def no_param_hint(a) -> int:\n"
        "    return a\n"
        "\n"
        "\n"
        "def no_return_hint(a: int):\n"
        "    return a\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    cov = analyze_type_hint_coverage(tmp_path)
    assert cov.total_functions == 3
    assert cov.annotated_functions == 1
    assert cov.overall_ratio == round(1 / 3, 4)
    assert cov.worst_modules[0]["ratio"] == round(1 / 3, 4)


def test_self_and_cls_receivers_not_required(tmp_path):
    # The self/cls receiver carries no hint, yet both methods count as annotated.
    src = (
        "class C:\n"
        "    def inst(self) -> int:\n"
        "        return 1\n"
        "\n"
        "    @classmethod\n"
        "    def klass(cls) -> int:\n"
        "        return 2\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    cov = analyze_type_hint_coverage(tmp_path)
    assert cov.overall_ratio == 1.0
    assert cov.annotated_functions == 2


def test_varargs_and_kwargs_must_be_annotated(tmp_path):
    src = (
        "def hinted(*args: int, **kwargs: str) -> None:\n"
        "    return None\n"
        "\n"
        "\n"
        "def bare(*args, **kwargs) -> None:\n"
        "    return None\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    cov = analyze_type_hint_coverage(tmp_path)
    assert cov.total_functions == 2
    assert cov.annotated_functions == 1


def test_no_param_function_needs_only_return_hint(tmp_path):
    src = (
        "def with_return() -> None:\n"
        "    return None\n"
        "\n"
        "\n"
        "def without_return():\n"
        "    return None\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    cov = analyze_type_hint_coverage(tmp_path)
    assert cov.annotated_functions == 1
    assert cov.total_functions == 2


def test_empty_project_safe_defaults(tmp_path):
    cov = analyze_type_hint_coverage(tmp_path)
    assert cov.overall_ratio == 0.0
    assert cov.total_functions == 0
    assert cov.annotated_functions == 0
    assert cov.worst_modules == []


def test_missing_root_safe_defaults(tmp_path):
    cov = analyze_type_hint_coverage(tmp_path / "does-not-exist")
    assert cov == TypeHintCoverage()
    assert cov.overall_ratio == 0.0


def test_module_with_no_functions_excluded(tmp_path):
    # Constants-only module: no functions → no ratio, no worst entry, no crash.
    (tmp_path / "const.py").write_text("X = 1\nY = 2\n", encoding="utf-8")
    cov = analyze_type_hint_coverage(tmp_path)
    assert cov.total_functions == 0
    assert cov.overall_ratio == 0.0
    assert cov.worst_modules == []


def test_unparseable_file_skipped(tmp_path):
    (tmp_path / "broken.py").write_text("def oops(:\n    pass\n", encoding="utf-8")
    (tmp_path / "ok.py").write_text(FULLY_ANNOTATED, encoding="utf-8")
    cov = analyze_type_hint_coverage(tmp_path)
    # Only the parseable module contributes; the broken one is silently dropped.
    assert cov.total_functions == 3
    assert cov.overall_ratio == 1.0


def test_tests_and_fixtures_excluded(tmp_path):
    # Shipped surface: fully annotated.
    (tmp_path / "app.py").write_text(FULLY_ANNOTATED, encoding="utf-8")
    # Each of these is unannotated but must NOT drag the score down.
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text(UNANNOTATED, encoding="utf-8")
    (tests_dir / "conftest.py").write_text(UNANNOTATED, encoding="utf-8")
    (tmp_path / "thing_test.py").write_text(UNANNOTATED, encoding="utf-8")
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "sample.py").write_text(UNANNOTATED, encoding="utf-8")
    # A top-level test_*.py at the root is excluded too.
    (tmp_path / "test_root.py").write_text(UNANNOTATED, encoding="utf-8")

    cov = analyze_type_hint_coverage(tmp_path)
    assert cov.overall_ratio == 1.0
    assert cov.total_functions == 3
    assert {m["module"] for m in cov.worst_modules} == {"app.py"}


def test_skipped_dirs_not_walked(tmp_path):
    # A .claude worktree-style copy must not be counted (canonical skip set).
    (tmp_path / "app.py").write_text(FULLY_ANNOTATED, encoding="utf-8")
    worktree = tmp_path / ".claude" / "worktrees" / "agent-1"
    worktree.mkdir(parents=True)
    (worktree / "app.py").write_text(UNANNOTATED, encoding="utf-8")
    cov = analyze_type_hint_coverage(tmp_path)
    assert cov.total_functions == 3
    assert cov.overall_ratio == 1.0


def test_worst_modules_sorted_and_capped(tmp_path):
    # 12 modules at descending ratios; expect lowest-first, capped at 10.
    for i in range(12):
        # module i has i annotated of 11 → ratio i/11, all distinct.
        annotated = "".join(
            f"def a{j}(x: int) -> int:\n    return x\n\n\n" for j in range(i)
        )
        bare = "".join(
            f"def b{j}(x):\n    return x\n\n\n" for j in range(11 - i)
        )
        (tmp_path / f"m{i:02d}.py").write_text(annotated + bare, encoding="utf-8")
    cov = analyze_type_hint_coverage(tmp_path)
    assert len(cov.worst_modules) == 10
    ratios = [m["ratio"] for m in cov.worst_modules]
    assert ratios == sorted(ratios)  # ascending = worst first
    assert cov.worst_modules[0]["ratio"] == 0.0


def test_tie_break_larger_module_ranks_worse(tmp_path):
    # Two modules both at ratio 0.0; the bigger one (more functions) ranks first.
    small = "def a(x):\n    return x\n"
    big = "".join(f"def a{j}(x):\n    return x\n\n\n" for j in range(5))
    (tmp_path / "small.py").write_text(small, encoding="utf-8")
    (tmp_path / "big.py").write_text(big, encoding="utf-8")
    cov = analyze_type_hint_coverage(tmp_path)
    assert cov.worst_modules[0]["module"] == "big.py"
    assert cov.worst_modules[1]["module"] == "small.py"


def test_max_files_cap_bounds_scan(tmp_path):
    (tmp_path / "a.py").write_text(FULLY_ANNOTATED, encoding="utf-8")
    (tmp_path / "b.py").write_text(FULLY_ANNOTATED, encoding="utf-8")
    cov = analyze_type_hint_coverage(tmp_path, max_files=1)
    # Only one of the two files is scanned (3 functions each).
    assert cov.total_functions == 3


def test_deterministic_repeated_runs(tmp_path):
    (tmp_path / "a.py").write_text(FULLY_ANNOTATED, encoding="utf-8")
    (tmp_path / "b.py").write_text(UNANNOTATED, encoding="utf-8")
    (tmp_path / "c.py").write_text("X = 1\n", encoding="utf-8")
    first = analyze_type_hint_coverage(tmp_path)
    second = analyze_type_hint_coverage(tmp_path)
    assert first == second
    assert first.to_dict() == second.to_dict()


def test_to_dict_round_trips_fields(tmp_path):
    (tmp_path / "m.py").write_text(FULLY_ANNOTATED, encoding="utf-8")
    cov = analyze_type_hint_coverage(tmp_path)
    d = cov.to_dict()
    assert d["overall_ratio"] == 1.0
    assert d["annotated_functions"] == 3
    assert d["total_functions"] == 3
    assert d["worst_modules"] == cov.worst_modules
