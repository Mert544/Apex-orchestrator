import subprocess
from pathlib import Path

from app.tools.polyglot_facts import (
    FileFact,
    render_polyglot_attention,
    scan_polyglot_facts,
)
from app.tools.project_profile import ProjectProfiler, render_analysis_scope_line


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True,
                   capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "T")
    _git(root, "config", "commit.gpgsign", "false")


def _commit(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


def _polyglot_tree(root: Path) -> None:
    """3 Python, 2 JS, 1 HTML source files, plus a binary asset and a
    node_modules dir full of JS that must be excluded via is_skipped."""
    (root / "app").mkdir()
    (root / "web").mkdir()
    (root / "app" / "main.py").write_text("def run():\n    return True\n", encoding="utf-8")
    (root / "app" / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (root / "app" / "model.py").write_text("class M:\n    pass\n", encoding="utf-8")
    # app.js: 4 non-blank lines (a blank line in the middle is not counted).
    (root / "web" / "app.js").write_text(
        "const a = 1;\n\nconst b = 2;\nconst c = 3;\nconsole.log(a, b, c);\n",
        encoding="utf-8",
    )
    (root / "web" / "small.js").write_text("console.log(1);\n", encoding="utf-8")
    (root / "web" / "index.html").write_text("<html>\n<body></body>\n</html>\n", encoding="utf-8")
    (root / "web" / "logo.png").write_bytes(b"\x89PNG\r\n")
    nm = root / "node_modules" / "left-pad"
    nm.mkdir(parents=True)
    for i in range(5):
        (nm / f"lib{i}.js").write_text("module.exports = 1;\n", encoding="utf-8")


def test_scans_only_non_python_source_files(tmp_path: Path):
    _polyglot_tree(tmp_path)
    facts = scan_polyglot_facts(str(tmp_path))
    paths = {f.path for f in facts}
    # Non-Python source named; Python and node_modules/.git and the binary
    # asset all excluded.
    assert paths == {"web/app.js", "web/small.js", "web/index.html"}
    assert not any(p.endswith(".py") for p in paths)
    assert not any("node_modules" in p for p in paths)
    assert not any(p.endswith(".png") for p in paths)


def test_loc_counts_non_blank_lines(tmp_path: Path):
    _polyglot_tree(tmp_path)
    by_path = {f.path: f for f in scan_polyglot_facts(str(tmp_path))}
    assert by_path["web/app.js"].loc == 4  # blank middle line not counted
    assert by_path["web/small.js"].loc == 1
    assert by_path["web/index.html"].loc == 3
    assert by_path["web/app.js"].language == "JavaScript"
    assert by_path["web/index.html"].language == "HTML"


def test_ranked_by_churn_then_loc(tmp_path: Path):
    _polyglot_tree(tmp_path)
    _init_repo(tmp_path)
    # small.js gets the MOST commits, so it ranks first despite the fewest LOC —
    # proving churn dominates the ordering.
    _commit(tmp_path, "initial")
    (tmp_path / "web" / "small.js").write_text("console.log(2);\n", encoding="utf-8")
    _commit(tmp_path, "edit small")
    (tmp_path / "web" / "small.js").write_text("console.log(3);\n", encoding="utf-8")
    _commit(tmp_path, "edit small again")

    facts = scan_polyglot_facts(str(tmp_path))
    by_path = {f.path: f for f in facts}
    assert by_path["web/small.js"].churn == 3
    assert by_path["web/app.js"].churn == 1
    assert by_path["web/index.html"].churn == 1
    # small.js first (-churn wins); app.js before index.html (equal churn,
    # higher LOC wins).
    assert [f.path for f in facts] == ["web/small.js", "web/app.js", "web/index.html"]


def test_non_git_dir_yields_churn_zero_no_crash(tmp_path: Path):
    _polyglot_tree(tmp_path)  # no _init_repo: not a git repo
    facts = scan_polyglot_facts(str(tmp_path))
    assert facts  # still found the files
    assert all(f.churn == 0 for f in facts)
    # With all churn equal, ordering falls back to (-loc, path): app.js(4) >
    # index.html(3) > small.js(1).
    assert [f.path for f in facts] == ["web/app.js", "web/index.html", "web/small.js"]


def test_limit_is_respected(tmp_path: Path):
    _polyglot_tree(tmp_path)
    assert len(scan_polyglot_facts(str(tmp_path), limit=2)) == 2
    assert scan_polyglot_facts(str(tmp_path), limit=0) == []


def test_empty_and_all_python_yield_no_facts(tmp_path: Path):
    assert scan_polyglot_facts(str(tmp_path)) == []  # empty dir
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert scan_polyglot_facts(str(tmp_path)) == []  # all-Python


def test_lockfile_is_denied(tmp_path: Path):
    (tmp_path / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "app.js").write_text("x = 1\n", encoding="utf-8")
    paths = {f.path for f in scan_polyglot_facts(str(tmp_path))}
    assert paths == {"app.js"}  # lockfile excluded, real source kept


def test_missing_root_returns_empty(tmp_path: Path):
    assert scan_polyglot_facts(str(tmp_path / "does-not-exist")) == []


def test_determinism_stable_ordering(tmp_path: Path):
    _polyglot_tree(tmp_path)
    _init_repo(tmp_path)
    _commit(tmp_path, "initial")
    first = scan_polyglot_facts(str(tmp_path))
    second = scan_polyglot_facts(str(tmp_path))
    assert first == second
    assert [f.path for f in first] == [f.path for f in second]


def test_render_attention_clause(tmp_path: Path):
    facts = [
        FileFact(path="src/app.js", language="JavaScript", loc=412, churn=8),
        FileFact(path="web/index.html", language="HTML", loc=240, churn=1),
    ]
    clause = render_polyglot_attention(facts)
    assert clause == (
        "Largest / most-active files outside analysis scope: "
        "`src/app.js` (412 LOC, 8 commits), `web/index.html` (240 LOC, 1 commit)"
        " — Apex can't deep-analyse these yet, but they're where the "
        "non-Python risk concentrates."
    )


def test_render_attention_empty_when_no_facts():
    assert render_polyglot_attention([]) == ""


def test_scope_line_byte_identical_on_all_python_repo(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    # All-Python: no out-of-scope content, so the scope line is empty and the
    # attention clause is never appended.
    assert render_analysis_scope_line(profile) == ""


def test_scope_line_gains_attention_clause_on_polyglot_repo(tmp_path: Path):
    _polyglot_tree(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile()
    line = render_analysis_scope_line(profile)
    # The honest counts line is preserved verbatim...
    assert line.startswith(
        "Scope: analysing 50% of the repo (Python). "
        "50% is outside analysis scope — JavaScript 2 files, HTML 1."
    )
    # ...and is now followed by the concrete attention clause naming real files.
    assert "Largest / most-active files outside analysis scope:" in line
    assert "`web/app.js`" in line
    assert "non-Python risk concentrates." in line


def test_scope_line_deterministic_on_polyglot_repo(tmp_path: Path):
    _polyglot_tree(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert render_analysis_scope_line(profile) == render_analysis_scope_line(profile)
