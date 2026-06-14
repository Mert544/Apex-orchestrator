from pathlib import Path

from app.tools.project_profile import (
    ProjectProfiler,
    render_analysis_scope_line,
)


def _polyglot_repo(root: Path) -> None:
    """A deterministic mix: 3 Python, 4 JS, 2 HTML, 1 CSS (10 source files),
    plus a binary asset (excluded from the denominator) and a node_modules dir
    (a canonical skip dir that must be ignored entirely)."""
    (root / "app").mkdir()
    (root / "web").mkdir()
    (root / "app" / "main.py").write_text("def run():\n    return True\n", encoding="utf-8")
    (root / "app" / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (root / "app" / "model.py").write_text("class M:\n    pass\n", encoding="utf-8")
    for i in range(4):
        (root / "web" / f"app{i}.js").write_text("console.log(1);\n", encoding="utf-8")
    (root / "web" / "index.html").write_text("<html></html>\n", encoding="utf-8")
    (root / "web" / "about.html").write_text("<html></html>\n", encoding="utf-8")
    (root / "web" / "style.css").write_text("body{}\n", encoding="utf-8")
    # A binary asset — counted as source would be a lie, so it's excluded.
    (root / "web" / "logo.png").write_bytes(b"\x89PNG\r\n")
    # A canonical skip dir: full of JS that must NOT inflate the breakdown.
    nm = root / "node_modules" / "left-pad"
    nm.mkdir(parents=True)
    for i in range(20):
        (nm / f"lib{i}.js").write_text("module.exports = 1;\n", encoding="utf-8")


def test_scope_accounting_on_polyglot_repo(tmp_path: Path):
    _polyglot_repo(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile()

    # Skip dir excluded: only the 10 real source files count, not the 20 in
    # node_modules nor the binary .png asset.
    assert profile.python_file_count == 3
    assert profile.source_file_count == 10
    assert profile.language_breakdown == {"JavaScript": 4, "HTML": 2, "CSS": 1}
    assert profile.analyzed_ratio == 0.3
    assert profile.out_of_scope_ratio == 0.7


def test_render_helper_exact_string_for_known_mix(tmp_path: Path):
    _polyglot_repo(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile()
    line = render_analysis_scope_line(profile)
    assert line == (
        "Scope: analysing 30% of the repo (Python). "
        "70% is outside analysis scope — JavaScript 4 files, HTML 2, CSS 1."
    )


def test_render_helper_empty_when_all_python(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()

    assert profile.python_file_count == 2
    assert profile.source_file_count == 2
    assert profile.language_breakdown == {}
    assert profile.analyzed_ratio == 1.0
    assert profile.out_of_scope_ratio == 0.0
    # An all-Python repo gets no scope clause at all — nothing to disclose.
    assert render_analysis_scope_line(profile) == ""


def test_render_helper_empty_for_empty_repo(tmp_path: Path):
    profile = ProjectProfiler(str(tmp_path)).profile()
    # Guard the divide-by-zero: an empty repo is fully "analysed" and renders
    # no line (there is nothing source-bearing to report).
    assert profile.source_file_count == 0
    assert profile.analyzed_ratio == 1.0
    assert profile.out_of_scope_ratio == 0.0
    assert render_analysis_scope_line(profile) == ""


def test_unmapped_source_extension_folds_into_other(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    # An unmapped but source-bearing extension must be counted, under "other",
    # so the totals never silently undercount the repo.
    (tmp_path / "app" / "build.zig").write_text("// zig\n", encoding="utf-8")
    (tmp_path / "app" / "conf.ini").write_text("[x]\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()

    assert profile.python_file_count == 1
    assert profile.source_file_count == 3
    assert profile.language_breakdown == {"other": 2}
    assert profile.out_of_scope_ratio > 0


def test_scope_breakdown_is_deterministic_and_sorted(tmp_path: Path):
    _polyglot_repo(tmp_path)
    first = ProjectProfiler(str(tmp_path)).profile().language_breakdown
    second = ProjectProfiler(str(tmp_path)).profile().language_breakdown
    # Same input -> same output, and ordering is count-desc then name (stable).
    assert first == second
    assert list(first.items()) == list(second.items())
    assert list(first.items()) == [("JavaScript", 4), ("HTML", 2), ("CSS", 1)]
