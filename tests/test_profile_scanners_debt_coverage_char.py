"""Characterization tests pinning ``ProjectProfiler._scan_debt_age`` and
``_coverage_checker`` (and their extracted pure helpers) to exact behavior.

Both functions were decomposed into small pure helpers; this module is the
behavioral lock. It pins:

* the end-to-end ``_scan_debt_age`` signal on a git-backed tree (oldest debt
  marker age, anchored to HEAD time so it stays deterministic), plus the
  empty/non-git fallbacks;
* the wrapper-aware ``_coverage_checker`` (direct name, sibling-wrapper, and
  enclosing-scope coverage; whole-suite fallback for untracked modules);
* every extracted helper as a pure unit: ``_oldest_debt_ctime``,
  ``_function_reference_names``, ``_coverage_test_text``.

Determinism and light-mode safety are pinned too: the same tree profiled twice
yields equal output, and light mode leaves the git-only ``debt_marker_ages``
empty while keeping the always-on base-walk fields identical to full mode.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from app.tools.project_profile import ProjectProfiler


def _git(root: Path, *args: str) -> None:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_DATE": "2020-01-01T00:00:00",
            "GIT_COMMITTER_DATE": "2020-01-01T00:00:00",
        }
    )
    subprocess.run(["git", *args], cwd=root, check=True,
                   capture_output=True, text=True, env=env)


def _commit(root: Path, msg: str, when: str) -> None:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "Alice", "GIT_AUTHOR_EMAIL": "alice@example.com",
            "GIT_COMMITTER_NAME": "Alice", "GIT_COMMITTER_EMAIL": "alice@example.com",
            "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when,
        }
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True,
                   capture_output=True, text=True, env=env)
    subprocess.run(["git", "commit", "-m", msg, "--no-gpg-sign"], cwd=root,
                   check=True, capture_output=True, text=True, env=env)


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], check=True,
                       capture_output=True, text=True)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _git_available(), reason="git not available")


@pytest.fixture()
def debt_tree(tmp_path: Path) -> Path:
    """A git tree where one module's debt marker is 10 days older than HEAD."""
    root = tmp_path / "proj"
    (root / "app").mkdir(parents=True)
    # The debt marker line is committed first (older), then an unrelated line
    # is added at HEAD time so HEAD's committer-time is the newer anchor.
    debt = root / "app" / "old.py"
    # >= DEBT_MARKER_THRESHOLD (3) markers so the base walk flags the module.
    debt.write_text(
        "# TODO: ancient debt\n# FIXME: also old\n# XXX: still here\nX = 1\n",
        encoding="utf-8",
    )
    (root / "app" / "clean.py").write_text("Y = 2\n", encoding="utf-8")
    _git(root, "init", "-q")
    _commit(root, "debt", "2020-01-01T00:00:00")
    # HEAD is 10 days later, touching only clean.py so old.py's blame keeps the
    # original committer-time.
    (root / "app" / "clean.py").write_text("Y = 3\n", encoding="utf-8")
    _commit(root, "head", "2020-01-11T00:00:00")
    return root


def test_debt_age_oldest_marker_anchored_to_head(debt_tree: Path) -> None:
    prof = ProjectProfiler(str(debt_tree)).profile(light=False)
    assert prof.debt_marker_modules == ["app/old.py"]
    # 10 whole days between the TODO commit and HEAD.
    assert prof.debt_marker_ages == {"app/old.py": 10}


def test_debt_age_determinism(debt_tree: Path) -> None:
    a = ProjectProfiler(str(debt_tree)).profile(light=False).debt_marker_ages
    b = ProjectProfiler(str(debt_tree)).profile(light=False).debt_marker_ages
    assert a == b == {"app/old.py": 10}


def test_debt_age_light_mode_skips_but_base_walk_identical(debt_tree: Path) -> None:
    light = ProjectProfiler(str(debt_tree)).profile(light=True)
    full = ProjectProfiler(str(debt_tree)).profile(light=False)
    # Git-only field stays empty in light mode.
    assert light.debt_marker_ages == {}
    # Always-on base-walk debt detection is identical between modes.
    assert light.debt_marker_modules == full.debt_marker_modules


def test_debt_age_empty_and_nongit(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert ProjectProfiler(str(empty)).profile(light=False).debt_marker_ages == {}

    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "d.py").write_text(
        "# TODO: x\n# FIXME: y\n# HACK: z\nZ = 1\n", encoding="utf-8"
    )
    prof = ProjectProfiler(str(plain)).profile(light=False)
    # Debt is detected by the base walk, but a non-git tree yields no ages.
    assert prof.debt_marker_modules == ["d.py"]
    assert prof.debt_marker_ages == {}


# --- pure-helper units -----------------------------------------------------

def test_oldest_debt_ctime_picks_minimum_on_marker_lines() -> None:
    blame = (
        "committer-time 200\n"
        "\t# TODO: newer marker\n"
        "committer-time 100\n"
        "\t# FIXME: older marker\n"
        "committer-time 150\n"
        "\tplain code, no marker\n"  # ignored: not a debt line
    )
    assert ProjectProfiler._oldest_debt_ctime(
        blame, ProjectProfiler.DEBT_MARKER_RE
    ) == 100


def test_oldest_debt_ctime_none_without_markers_or_bad_time() -> None:
    # No debt-marker content lines at all.
    assert ProjectProfiler._oldest_debt_ctime(
        "committer-time 100\n\tjust code\n", ProjectProfiler.DEBT_MARKER_RE
    ) is None
    # Malformed committer-time resets state, so its marker line is unanchored.
    assert ProjectProfiler._oldest_debt_ctime(
        "committer-time notanumber\n\t# TODO: x\n", ProjectProfiler.DEBT_MARKER_RE
    ) is None
    assert ProjectProfiler._oldest_debt_ctime("", ProjectProfiler.DEBT_MARKER_RE) is None


def test_function_reference_names_collects_names_and_attrs() -> None:
    src = (
        "def wrapper(x):\n"
        "    return helper(x)\n"
        "def helper(x):\n"
        "    return x.compute()\n"
    )
    refs = ProjectProfiler._function_reference_names(src)
    assert refs["wrapper"] == {"helper", "x"}
    assert refs["helper"] == {"x", "compute"}


def test_function_reference_names_empty_on_syntax_error() -> None:
    assert ProjectProfiler._function_reference_names("def broken(:\n") == {}
    assert ProjectProfiler._function_reference_names("") == {}


def test_coverage_test_text_fallback_for_untracked(tmp_path: Path) -> None:
    root = tmp_path
    (root / "linked_test.py").write_text("names_target\n", encoding="utf-8")
    prof = ProjectProfiler(str(root))
    # Tracked module reads only its linked tests.
    text = prof._coverage_test_text(
        "mod.py", {"mod.py": ["linked_test.py"]}, lambda: "WHOLE"
    )
    assert text == "names_target\n"
    # Untracked module falls back to the whole-suite corpus.
    assert prof._coverage_test_text("other.py", {}, lambda: "WHOLE") == "WHOLE"


# --- _coverage_checker wrapper-aware behavior ------------------------------

def _checker(tmp_path: Path, source: str, test_text: str):
    prof = ProjectProfiler(str(tmp_path))
    # Untracked module path -> whole_suite_text fallback returns our text.
    return prof._coverage_checker("mod.py", source, {}, lambda: test_text)


def test_coverage_checker_direct_name(tmp_path: Path) -> None:
    exercised = _checker(
        tmp_path,
        "def public():\n    return 1\n",
        "def test_it():\n    public()\n",
    )
    assert exercised("public") is True
    assert exercised("missing") is False


def test_coverage_checker_sibling_wrapper(tmp_path: Path) -> None:
    # _helper is named by no test, but its public wrapper is — coverage flows
    # through the sibling reference.
    source = (
        "def wrapper(x):\n    return _helper(x)\n"
        "def _helper(x):\n    return x\n"
    )
    exercised = _checker(tmp_path, source, "def test_w():\n    wrapper(1)\n")
    assert exercised("_helper") is True


def test_coverage_checker_enclosing_scope(tmp_path: Path) -> None:
    # A method is covered when its enclosing class name is named by a test.
    source = "class Thing:\n    def run(self):\n        return 1\n"
    exercised = _checker(tmp_path, source, "def test_c():\n    Thing()\n")
    assert exercised("Thing.run") is True


def test_coverage_checker_whole_word_only(tmp_path: Path) -> None:
    # 'run' must not be covered by 'rerun' (substring, not whole word).
    exercised = _checker(
        tmp_path,
        "def run():\n    return 1\n",
        "def test_x():\n    rerun()\n",
    )
    assert exercised("run") is False


def test_coverage_checker_whole_word_regex_matches_real_token() -> None:
    # Sanity-pin the whole-word semantics the checker relies on.
    assert re.search(r"\brun\b", "call run() now") is not None
    assert re.search(r"\brun\b", "call rerun() now") is None
