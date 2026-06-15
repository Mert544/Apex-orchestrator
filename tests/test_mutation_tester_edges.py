"""Edge/behavioral coverage for the mutation tester.

These tests pin paths the existing suites leave open:

* the number- and return-literal site collectors' ``end > len(line)`` guard
  (reached by handing ``_collect_sites`` a source-line list shorter than the
  span the tree reports), and
* the end-to-end ``mutation_score`` outcomes — a module with NO mutable sites,
  an all-KILLED run, an all-SURVIVED run, and the per-mutant TIMEOUT-counts-as-
  killed path — plus the markdown renderer's no-survivors and total==0 shapes.

The synthetic projects live in ``tmp_path`` (one tiny module + one tiny test)
so the per-mutant pytest runs stay fast. Nothing asserts on time, randomness,
or unordered iteration order.
"""

from __future__ import annotations

import ast
import subprocess

from app.engine.mutation_tester import (
    _collect_sites,
    mutation_score,
    render_mutation_markdown,
)


def _write_project(root, module_src, test_src, module_rel="mod.py"):
    """Lay down a minimal pytest project: one module + one test."""
    (root / module_rel).write_text(module_src, encoding="utf-8")
    (root / "test_mod.py").write_text(test_src, encoding="utf-8")
    return module_rel


# --- _collect_sites: number literal whose span overruns the source line ----

def test_number_site_skipped_when_span_overruns_line():
    # The tree reports a number literal spanning cols [4, 7) ("100"), but the
    # source-line list we hand in is truncated to "x = 1" so end (7) > len(5):
    # the ``end > len(line)`` guard skips the site without emitting it.
    tree = ast.parse("x = 100\n")
    sites = _collect_sites(tree, ["x = 1\n"])
    assert not any(s.operator.startswith("number:") for s in sites)


# --- _collect_sites: return value whose span overruns the source line ------

def test_return_site_skipped_when_span_overruns_line():
    tree = ast.parse("def f():\n    return abc\n")
    # Truncated second line -> the return-value span end exceeds len(line).
    sites = _collect_sites(tree, ["def f():\n", "    ret\n"])
    assert not any(s.operator == "return:value>None" for s in sites)


# --- mutation_score: a module with no mutable sites scores 0.0 -------------

def test_no_mutable_sites_yields_empty_zero_score(tmp_path):
    # A module of only pass/docstring has no operators/constants to seed.
    rel = _write_project(
        tmp_path,
        '"""doc."""\n\n\ndef noop():\n    pass\n',
        "from mod import noop\n\n\ndef test_noop():\n    assert noop() is None\n",
    )
    result = mutation_score(tmp_path, rel, scope_tests=False)
    assert result.total == 0
    assert result.killed == 0
    assert result.survived == 0
    assert result.score == 0.0
    assert result.survivors == []


# --- mutation_score: a strong suite kills every mutant ---------------------

def test_all_mutants_killed_by_strong_suite(tmp_path):
    # The test pins both the True and False branches, so every seeded fault in
    # the comparison/return is observed by the suite.
    rel = _write_project(
        tmp_path,
        "def is_equal(a, b):\n    return a == b\n",
        "from mod import is_equal\n\n\n"
        "def test_equal():\n"
        "    assert is_equal(1, 1) is True\n"
        "    assert is_equal(1, 2) is False\n",
    )
    result = mutation_score(tmp_path, rel, scope_tests=False)
    assert result.total > 0
    assert result.killed == result.total
    assert result.survived == 0
    assert result.score == 1.0
    assert result.survivors == []


# --- mutation_score: a blind suite lets every mutant survive ----------------

def test_all_mutants_survive_when_suite_is_blind(tmp_path):
    # The test never calls the module function, so no seeded fault is observable
    # — every mutant survives and the score floors at 0.0.
    rel = _write_project(
        tmp_path,
        "def is_equal(a, b):\n    return a == b\n",
        "def test_unrelated():\n    assert 1 + 1 == 2\n",
    )
    result = mutation_score(tmp_path, rel, scope_tests=False)
    assert result.total > 0
    assert result.killed == 0
    assert result.survived == result.total
    assert result.score == 0.0
    assert len(result.survivors) == result.total


# --- mutation_score: a per-mutant timeout counts the mutant as killed -------

def test_timeout_counts_mutant_as_killed(tmp_path, monkeypatch):
    rel = _write_project(
        tmp_path,
        "def is_equal(a, b):\n    return a == b\n",
        "from mod import is_equal\n\n\ndef test_equal():\n    assert is_equal(1, 1)\n",
    )

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = mutation_score(tmp_path, rel, scope_tests=False)
    # Every mutant's verify run "hangs" -> all counted as killed.
    assert result.total > 0
    assert result.killed == result.total
    assert result.survived == 0
    assert result.score == 1.0


# --- render_mutation_markdown: the no-survivors and total==0 shapes ---------

def test_render_markdown_no_survivors_section(tmp_path):
    rel = _write_project(
        tmp_path,
        "def is_equal(a, b):\n    return a == b\n",
        "from mod import is_equal\n\n\n"
        "def test_equal():\n"
        "    assert is_equal(1, 1) is True\n"
        "    assert is_equal(1, 2) is False\n",
    )
    result = mutation_score(tmp_path, rel, scope_tests=False)
    md = render_mutation_markdown(result)
    assert "_No survivors — the suite caught every seeded fault._" in md
    assert "Mutation score 100.0%" in md


def test_render_markdown_total_zero(tmp_path):
    rel = _write_project(
        tmp_path,
        '"""doc."""\n\n\ndef noop():\n    pass\n',
        "from mod import noop\n\n\ndef test_noop():\n    assert noop() is None\n",
    )
    result = mutation_score(tmp_path, rel, scope_tests=False)
    md = render_mutation_markdown(result)
    assert "No mutable sites found" in md
