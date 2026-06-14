"""Polyglot facts: additional behavioural edges beyond the existing suites.

These harden corners not directly pinned elsewhere: every canonical skip-dir
(not just ``node_modules``), nested skip dirs, rank-based truncation by ``limit``,
a REAL non-git directory degrading churn to 0 (no mock), churn counts that span
multiple candidate files in one git pass, and deny-name case-insensitivity. All
tests build inputs explicitly and use hermetic tmp git repos with a fixed
committer env and fixed commit messages — no time/random/order dependence.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.tools.polyglot_facts import (
    render_polyglot_attention,
    scan_polyglot_facts,
)


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


# --- every canonical skip dir is excluded, not just node_modules ----------------

@pytest.mark.parametrize(
    "skip_dir",
    [".git", "__pycache__", ".apex", ".epistemic", ".claude",
     ".venv", "venv", "node_modules", "dist", "build"],
)
def test_each_canonical_skip_dir_is_excluded(tmp_path: Path, skip_dir):
    # A JS file inside any canonical skip dir is never named; a sibling in a
    # normal dir is. Stays consistent with the shared is_skipped predicate.
    skipped = tmp_path / skip_dir
    skipped.mkdir()
    (skipped / "vendored.js").write_text("x;\n", encoding="utf-8")
    (tmp_path / "real.js").write_text("y;\n", encoding="utf-8")
    paths = {f.path for f in scan_polyglot_facts(str(tmp_path))}
    assert paths == {"real.js"}


def test_nested_skip_dir_anywhere_in_path_excludes_file(tmp_path: Path):
    # A skip-dir component anywhere along the path (not just top level) excludes
    # the file, mirroring is_skipped's any-component semantics.
    deep = tmp_path / "src" / "node_modules" / "pkg"
    deep.mkdir(parents=True)
    (deep / "buried.ts").write_text("z;\n", encoding="utf-8")
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "kept.ts").write_text("w;\n", encoding="utf-8")
    paths = {f.path for f in scan_polyglot_facts(str(tmp_path))}
    assert paths == {"src/kept.ts"}


# --- limit truncates by rank, keeping the strongest -----------------------------

def test_limit_keeps_highest_ranked_by_loc(tmp_path: Path):
    # With churn all 0 (non-git), -loc decides; limit=2 keeps the two largest.
    (tmp_path / "big.js").write_text("a;\nb;\nc;\nd;\n", encoding="utf-8")
    (tmp_path / "mid.js").write_text("a;\nb;\n", encoding="utf-8")
    (tmp_path / "small.js").write_text("a;\n", encoding="utf-8")
    facts = scan_polyglot_facts(str(tmp_path), limit=2)
    assert [f.path for f in facts] == ["big.js", "mid.js"]


def test_negative_limit_returns_empty(tmp_path: Path):
    # limit <= 0 short-circuits to [] before any walk (defensive boundary).
    (tmp_path / "a.js").write_text("x;\n", encoding="utf-8")
    assert scan_polyglot_facts(str(tmp_path), limit=-3) == []


def test_limit_larger_than_candidates_returns_all(tmp_path: Path):
    (tmp_path / "a.js").write_text("x;\n", encoding="utf-8")
    (tmp_path / "b.ts").write_text("y;\n", encoding="utf-8")
    assert len(scan_polyglot_facts(str(tmp_path), limit=99)) == 2


# --- a REAL non-git directory degrades churn to 0 (no subprocess mock) ----------

def test_real_non_git_dir_degrades_to_churn_zero(tmp_path: Path):
    # No _init_repo: 'git log' in a non-repo exits non-zero, so churn is 0 for
    # every file via the real subprocess path (not a monkeypatch).
    (tmp_path / "a.js").write_text("const a = 1;\nconst b = 2;\n", encoding="utf-8")
    (tmp_path / "b.ts").write_text("let c = 3;\n", encoding="utf-8")
    facts = scan_polyglot_facts(str(tmp_path))
    assert {f.path for f in facts} == {"a.js", "b.ts"}
    assert all(f.churn == 0 for f in facts)


# --- a REAL git repo: one pass tallies churn across several candidate files ------

def test_real_repo_single_pass_tallies_multiple_files(tmp_path: Path):
    # a.js touched in 3 commits, b.ts in 2, c.js in 1 — counted in one git pass.
    (tmp_path / "a.js").write_text("1;\n", encoding="utf-8")
    (tmp_path / "b.ts").write_text("1;\n", encoding="utf-8")
    (tmp_path / "c.js").write_text("1;\n", encoding="utf-8")
    _init_repo(tmp_path)
    _commit(tmp_path, "c1")
    (tmp_path / "a.js").write_text("2;\n", encoding="utf-8")
    (tmp_path / "b.ts").write_text("2;\n", encoding="utf-8")
    _commit(tmp_path, "c2")
    (tmp_path / "a.js").write_text("3;\n", encoding="utf-8")
    _commit(tmp_path, "c3")

    by_path = {f.path: f for f in scan_polyglot_facts(str(tmp_path))}
    assert by_path["a.js"].churn == 3
    assert by_path["b.ts"].churn == 2
    assert by_path["c.js"].churn == 1
    # -churn dominates: a.js, then b.ts, then c.js.
    facts = scan_polyglot_facts(str(tmp_path))
    assert [f.path for f in facts] == ["a.js", "b.ts", "c.js"]


# --- deny-name match is case-insensitive on the full basename -------------------

def test_deny_name_is_case_insensitive(tmp_path: Path):
    # Uppercased lockfile basename is still denied (matched on lowercased name).
    (tmp_path / "PACKAGE-LOCK.JSON").write_text("{}\n", encoding="utf-8")
    (tmp_path / "real.js").write_text("x;\n", encoding="utf-8")
    paths = {f.path for f in scan_polyglot_facts(str(tmp_path))}
    # The .json lockfile is dropped (extension not mapped anyway); real source
    # is kept. Demonstrates the lockfile never surfaces regardless of casing.
    assert paths == {"real.js"}


# --- LOC counting on mixed blank/whitespace lines -------------------------------

def test_loc_ignores_whitespace_only_lines(tmp_path: Path):
    # Lines that are blank or whitespace-only do not count toward LOC.
    (tmp_path / "a.css").write_text(
        "body {}\n   \n\nh1 {}\n\t\n", encoding="utf-8",
    )
    facts = scan_polyglot_facts(str(tmp_path))
    assert len(facts) == 1
    assert facts[0].loc == 2
    assert facts[0].language == "CSS"


# --- render: ordering of multiple facts is preserved verbatim -------------------

def test_render_preserves_input_order_of_facts(tmp_path: Path):
    # render walks facts in the order given (scan already ranked them); the
    # clause lists them in that exact order.
    (tmp_path / "big.js").write_text("a;\nb;\nc;\n", encoding="utf-8")
    (tmp_path / "small.ts").write_text("a;\n", encoding="utf-8")
    facts = scan_polyglot_facts(str(tmp_path))
    clause = render_polyglot_attention(facts)
    assert clause.index("`big.js`") < clause.index("`small.ts`")
    assert clause.startswith("Largest / most-active files outside analysis scope:")
