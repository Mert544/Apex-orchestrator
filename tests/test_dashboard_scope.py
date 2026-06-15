"""Outside-analysis-scope panel in the HTML dashboard.

Apex deep-analyses Python only and has no non-Python transform, so it surfaces
the blind spot honestly: a panel naming the biggest / most-active NON-Python
source files (from ``scan_polyglot_facts``) with language, LOC, churn and a
"(no test found)" flag for untested files. These tests drive the pure render
helper directly and guard the key invariants: gated absence (all-Python repo →
no section, byte-identical page), the untested flag, HTML escaping (XSS), and
determinism. Pattern-matched on tests/test_dashboard_trackrecord.py and
tests/test_dashboard_more_edges.py — fast, offline, no time/random assertions.
"""

import os
import subprocess

from app.reporting import dashboard as D


def _git_repo(root):
    """Init a git repo and commit everything so churn is well-defined."""
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    e = {**os.environ, **env}
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=e)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=e)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"],
        cwd=root, check=True, env=e,
    )


# --- gated absence: all-Python repo -> no section ---------------------------

def test_outscope_absent_for_all_python_repo(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def run():\n    return 1\n")
    assert D._outscope_section(str(tmp_path)) == ""


def test_outscope_absent_for_missing_root(tmp_path):
    assert D._outscope_section(str(tmp_path / "nope")) == ""


# --- renders non-Python files with language / LOC / churn -------------------

def test_outscope_lists_non_python_files(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "app.js").write_text("const a = 1;\nconst b = 2;\n")
    (tmp_path / "web" / "style.css").write_text("body { color: red; }\n")
    _git_repo(tmp_path)

    html_doc = D._outscope_section(str(tmp_path))
    assert "Outside analysis scope" in html_doc
    assert "web/app.js" in html_doc
    assert "JavaScript" in html_doc
    assert "web/style.css" in html_doc
    assert "CSS" in html_doc
    # LOC + churn surfaced.
    assert "<th>LOC</th>" in html_doc
    assert "commit" in html_doc
    # Honest caption present.
    assert "deep-analyses Python" in html_doc
    # No timestamp leaked into the panel.
    assert "UTC" not in html_doc


# --- the "(no test found)" flag ---------------------------------------------

def test_outscope_flags_untested_and_clears_tested(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "web" / "tested.js").write_text("export const x = 1;\n")
    (tmp_path / "web" / "untested.js").write_text("export const y = 2;\n")
    # A test file that references tested.js by basename.
    (tmp_path / "tests" / "test_web.py").write_text(
        "def test_tested():\n    assert 'tested.js'\n")
    _git_repo(tmp_path)

    html_doc = D._outscope_section(str(tmp_path))
    assert "web/untested.js" in html_doc
    assert "web/tested.js" in html_doc
    # The untested file carries the flag; the tested one does not. Check the
    # rows independently so ordering does not matter.
    untested_row = html_doc.split("web/untested.js")[1].split("</tr>")[0]
    tested_row = html_doc.split("web/tested.js")[1].split("</tr>")[0]
    assert "(no test found)" in untested_row
    assert "(no test found)" not in tested_row


def test_outscope_all_untested_when_no_test_files(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "a.js").write_text("const a = 1;\n")
    _git_repo(tmp_path)
    html_doc = D._outscope_section(str(tmp_path))
    assert "(no test found)" in html_doc


# --- HTML escaping / XSS ----------------------------------------------------

def test_outscope_escapes_xss_in_path(tmp_path):
    weird = tmp_path / "web" / "<script>alert(1)</script>"
    weird.parent.mkdir(parents=True)
    weird.mkdir()
    (weird / "evil.js").write_text("const a = 1;\n")
    _git_repo(tmp_path)

    html_doc = D._outscope_section(str(tmp_path))
    assert "evil.js" in html_doc
    # The raw <script> path segment must be escaped, never emitted live.
    assert "<script>alert(1)</script>" not in html_doc
    assert "&lt;script&gt;" in html_doc


# --- determinism ------------------------------------------------------------

def test_outscope_is_deterministic(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "app.js").write_text("const a = 1;\nconst b = 2;\n")
    (tmp_path / "web" / "style.css").write_text("body { color: red; }\n")
    _git_repo(tmp_path)
    a = D._outscope_section(str(tmp_path))
    b = D._outscope_section(str(tmp_path))
    assert a == b


# --- helper: test-corpus collection -----------------------------------------

def test_outscope_test_corpus_missing_root_is_empty(tmp_path):
    assert D._outscope_test_corpus(str(tmp_path / "nope")) == []


def test_outscope_test_corpus_ignores_non_test_files(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("x = 'app.js'\n")  # not a test file
    # No test files at all -> empty corpus.
    assert D._outscope_test_corpus(str(tmp_path)) == []


def test_outscope_test_corpus_collects_test_file_text(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("# refers to APP.JS\n")
    corpus = D._outscope_test_corpus(str(tmp_path))
    # Stored lowercased, so a case-insensitive basename check works.
    assert any("app.js" in text for text in corpus)


# --- full-page integration: gated nav + byte-identical legacy ---------------

def test_full_dashboard_includes_outscope_when_present(tmp_path):
    from app.reporting.dashboard import build_dashboard

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def run():\n    return 1\n")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "app.js").write_text("const a = 1;\nconst b = 2;\n")
    _git_repo(tmp_path)

    html_doc = build_dashboard(str(tmp_path), max_ideas=8, idea_depth=1, breadth=2)
    assert "#outscope" in html_doc
    assert "Outside analysis scope" in html_doc
    assert "web/app.js" in html_doc


def test_no_outscope_section_when_all_python(tmp_path):
    # An all-Python repo has no non-Python files, so the gated out-of-scope
    # section is empty and contributes no panel or nav anchor. Asserted directly
    # (the section is "" and "#outscope" is absent) rather than by double-building
    # the page and byte-comparing — the page carries a minute-grained "generated
    # HH:MM" stamp, so two builds that straddle a minute would differ spuriously.
    from app.reporting.dashboard import _outscope_section, build_dashboard

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def run():\n    return 1\n")

    assert _outscope_section(str(tmp_path)) == ""
    html = build_dashboard(str(tmp_path), max_ideas=8, idea_depth=1, breadth=2)
    assert "#outscope" not in html
