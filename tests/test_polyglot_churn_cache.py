"""Characterization + memoisation tests for the git-churn path of
``app.tools.polyglot_facts``.

The churn computation is the build hotspot: a full-history ``git log
--name-only`` walk. It is now memoised per ``(repo, HEAD)`` so the several
entry points that scan one build's repo state pay the walk once. These tests
PIN the churn output on a hermetic tmp git repo (identical before/after the
optimisation), prove the cache collapses repeated full-history passes into one,
and prove the cache invalidates the instant HEAD moves — so output stays exactly
as a non-cached run for any given repo state.

Every test builds inputs explicitly with a fixed committer env and fixed commit
messages — no time/random/order dependence. The whole module skips cleanly when
git is unavailable rather than failing.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import app.tools.polyglot_facts as pf
from app.tools.polyglot_facts import _git_churn, scan_polyglot_facts

# Guard the whole module: no git binary -> skip cleanly (the production code
# degrades to empty churn there, which the non-git tests already cover).
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not available"
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


@pytest.fixture(autouse=True)
def _clear_churn_cache():
    """Each test starts with an empty process-level churn cache, so cache
    population is observable and tests don't leak state into one another."""
    pf._CHURN_CACHE.clear()
    yield
    pf._CHURN_CACHE.clear()


def _build_repo(root: Path) -> None:
    """A small polyglot repo: a.js in 3 commits, b.ts in 2, c.js in 1."""
    (root / "a.js").write_text("1;\n", encoding="utf-8")
    (root / "b.ts").write_text("1;\n", encoding="utf-8")
    (root / "c.js").write_text("1;\n", encoding="utf-8")
    _init_repo(root)
    _commit(root, "c1")
    (root / "a.js").write_text("2;\n", encoding="utf-8")
    (root / "b.ts").write_text("2;\n", encoding="utf-8")
    _commit(root, "c2")
    (root / "a.js").write_text("3;\n", encoding="utf-8")
    _commit(root, "c3")


# --- PINNED churn output (identical before/after the optimisation) --------------

def test_churn_output_is_pinned(tmp_path: Path):
    _build_repo(tmp_path)
    by_path = {f.path: f for f in scan_polyglot_facts(str(tmp_path))}
    assert by_path["a.js"].churn == 3
    assert by_path["b.ts"].churn == 2
    assert by_path["c.js"].churn == 1
    # -churn dominates the ranking: a.js, then b.ts, then c.js.
    facts = scan_polyglot_facts(str(tmp_path))
    assert [f.path for f in facts] == ["a.js", "b.ts", "c.js"]


def test_git_churn_filters_to_candidates_only(tmp_path: Path):
    # _git_churn returns ONLY the requested candidates that were ever committed,
    # with their exact full-history commit counts — identical to a fresh pass
    # that tallies only those candidates.
    _build_repo(tmp_path)
    churn = _git_churn(tmp_path, {"a.js", "b.ts"})
    assert churn == {"a.js": 3, "b.ts": 2}  # c.js not requested -> absent
    # An unknown candidate is simply absent (churn 0 at the call site).
    churn2 = _git_churn(tmp_path, {"a.js", "missing.js"})
    assert churn2 == {"a.js": 3}


def test_empty_candidate_set_does_no_git_work(tmp_path: Path, monkeypatch):
    # With no candidates, _git_churn returns {} WITHOUT shelling out at all.
    _build_repo(tmp_path)

    def _boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("git should not be invoked for empty candidates")

    monkeypatch.setattr(pf.subprocess, "run", _boom)
    assert _git_churn(tmp_path, set()) == {}


# --- the cache collapses repeated full-history passes into ONE -------------------

def test_full_history_pass_runs_once_per_head(tmp_path: Path, monkeypatch):
    _build_repo(tmp_path)
    calls = {"n": 0}
    real = pf._compute_full_churn_map

    def _counting(root):
        calls["n"] += 1
        return real(root)

    monkeypatch.setattr(pf, "_compute_full_churn_map", _counting)

    # Three scans of the SAME repo state (mimicking the several build entry
    # points) trigger exactly ONE expensive full-history walk.
    a = scan_polyglot_facts(str(tmp_path))
    b = scan_polyglot_facts(str(tmp_path))
    c = scan_polyglot_facts(str(tmp_path))
    assert calls["n"] == 1
    # ...and every scan yields byte-identical facts.
    assert a == b == c


def test_cache_keyed_and_reused_across_candidate_sets(tmp_path: Path, monkeypatch):
    # Different callers pass different candidate sets; the full map is computed
    # once and filtered per call. Output for each subset is exactly right.
    _build_repo(tmp_path)
    calls = {"n": 0}
    real = pf._compute_full_churn_map

    def _counting(root):
        calls["n"] += 1
        return real(root)

    monkeypatch.setattr(pf, "_compute_full_churn_map", _counting)

    assert _git_churn(tmp_path, {"a.js"}) == {"a.js": 3}
    assert _git_churn(tmp_path, {"b.ts", "c.js"}) == {"b.ts": 2, "c.js": 1}
    assert _git_churn(tmp_path, {"a.js", "b.ts", "c.js"}) == {
        "a.js": 3, "b.ts": 2, "c.js": 1,
    }
    assert calls["n"] == 1  # single full-history pass shared by all three


# --- cache invalidates the instant HEAD moves (output tracks repo state) --------

def test_new_commit_moves_head_and_refreshes_churn(tmp_path: Path):
    _build_repo(tmp_path)
    before = {f.path: f.churn for f in scan_polyglot_facts(str(tmp_path))}
    assert before["c.js"] == 1

    # A new commit touching c.js moves HEAD; the cache key changes, so the next
    # scan reflects the new state instead of a stale cached map.
    (tmp_path / "c.js").write_text("2;\n", encoding="utf-8")
    _commit(tmp_path, "c4")
    after = {f.path: f.churn for f in scan_polyglot_facts(str(tmp_path))}
    assert after["c.js"] == 2  # refreshed, not the stale 1
    assert after["a.js"] == 3  # unchanged files keep their counts

    # Two distinct HEADs are now cached (the build state before and after).
    assert len(pf._CHURN_CACHE) == 2


def test_determinism_repeated_scans_identical(tmp_path: Path):
    _build_repo(tmp_path)
    first = scan_polyglot_facts(str(tmp_path))
    second = scan_polyglot_facts(str(tmp_path))
    assert first == second


# --- graceful degradation: git failure -> empty, never cached -------------------

def test_non_git_dir_degrades_to_empty_and_caches_nothing(tmp_path: Path):
    # No _init_repo: rev-parse HEAD fails, so churn is empty and no cache entry
    # is created (a later commit must compute fresh).
    (tmp_path / "a.js").write_text("x;\n", encoding="utf-8")
    facts = scan_polyglot_facts(str(tmp_path))
    assert facts and all(f.churn == 0 for f in facts)
    assert pf._CHURN_CACHE == {}


def test_log_failure_after_head_succeeds_degrades_to_empty(
    tmp_path: Path, monkeypatch
):
    # If HEAD resolves but the full-history pass fails, _git_churn degrades to
    # {} and does NOT poison the cache with an empty map.
    _build_repo(tmp_path)
    monkeypatch.setattr(pf, "_compute_full_churn_map", lambda root: None)
    assert _git_churn(tmp_path, {"a.js"}) == {}
    assert pf._CHURN_CACHE == {}
