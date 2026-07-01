"""Mixed Python+JS repo detection — the moat's own FIRST-MATCH-WINS crack.

The empirically-confirmed bug: on a repo shaped like the most common team
project (a Python service with ``pyproject.toml``/``tests/`` AND a JS/TS package
with its own ``package.json``), ``RunTestsSkill._detect_commands`` was
FIRST-MATCH-WINS — it found the pytest signal and ``return``ed immediately,
BEFORE the ``package.json``/npm branch was ever reached. jest never ran, yet
``run()`` still wrote a "verified" ``TestRunSummary`` with ``ok=True`` whenever
the (unrelated) Python suite happened to be green — even while the JS suite was
genuinely RED. A change (or one of Apex's own ``js-*`` objectives) could break
jest and still be reported suite-green: a live crack in the never-fake-green
moat, on the shape most real teams actually have.

The fix: when BOTH a pytest signal AND a ``package.json`` with a genuine
``scripts.test`` entry are present, ``_detect_commands`` returns BOTH command
sets. ``RunTestsSkill.run``'s own aggregation loop (unchanged — it already ANDs
``result.ok`` across every selected command) then makes green mean "every
detected suite is green", closing the hole for every caller that reads
``TestRunSummary.ok`` (the develop session, ``_apply_verify``'s full-suite and
delta-green gates, the idea/maintain bridge, the MCP/automation skills — none of
them had to change).

This file:

  * PINS the hole was real — a self-contained, byte-identical reproduction of
    the OLD (pre-fix) ``_detect_commands`` algorithm, run against the SAME mixed
    fixture, proving it returns ONLY the pytest command (so a red jest suite
    would never even be invoked, let alone charged).
  * PROVES the fix — the crux, non-tautological regression: a mixed fixture
    where jest is RED and pytest is GREEN must aggregate to ``ok=False``.
  * PROVES no over-triggering — a ``package.json`` with no ``scripts.test`` (a
    front-end build-tool config with zero tests) must NOT widen a Python
    project's suite (it would just fail immediately and turn an honest
    pytest-only green into a false red).
  * PROVES single-language behaviour is BYTE-IDENTICAL — a pure-Python and a
    pure-JS fixture each still detect/return exactly one command, unchanged.

Deterministic, offline. The end-to-end (real subprocess) tests need ``node`` +
an installable jest and skip cleanly when unavailable, exactly like the sibling
``test_js_gate_forced_eyml.py`` suite (and share its jest-install cache so the
combined run installs jest at most once).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.skills.execution.run_tests import RunTestsSkill

# --- a self-contained, byte-identical reproduction of the OLD algorithm ------
#
# Pinned from git history (commit b7985f7, the last revision of
# ``run_tests.py`` before this fix) so the "the hole was real" proof does not
# depend on reverting/monkeypatching the live module — it is an independent,
# frozen copy of exactly what used to run.


def _old_detect_commands(root: Path) -> list[list[str]]:
    """FIRST-MATCH-WINS — the exact pre-fix ``_detect_commands`` body."""
    skill = RunTestsSkill()
    if (
        (root / "pytest.ini").exists()
        or (root / "tests").exists()
        or (root / "pyproject.toml").exists()
        or skill._has_flat_pytest_suite(root)
    ):
        return [[skill._python_for(root), "-m", "pytest", "-q"]]
    if (root / "package.json").exists():
        return [["npm", "test", "--", "--runInBand"]]
    return []


def _pytest_cmd(root: Path) -> list[str]:
    return [sys.executable, "-m", "pytest", "-q"]


_JEST_CMD = ["npm", "test", "--", "--runInBand"]


def _mixed_fixture(tmp_path: Path, *, test_script: str = "jest") -> Path:
    """A MIXED repo: a real pytest suite (``tests/test_x.py``, GREEN) AND a
    ``package.json`` declaring ``scripts.test`` — the shape that used to
    fake-green a broken jest suite."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_python_side.py").write_text(
        "def test_trivial():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        '{ "name": "mixed", "version": "1.0.0", "scripts": { "test": "'
        + test_script + '" } }\n', encoding="utf-8")
    return tmp_path


# --- the hole was real: the OLD logic fake-greened this exact shape ----------

def test_old_algorithm_never_reaches_the_js_branch(tmp_path: Path) -> None:
    root = _mixed_fixture(tmp_path)
    # FIRST-MATCH-WINS: the pytest signal alone decides; package.json (present,
    # with a genuine test script) is never even consulted.
    assert _old_detect_commands(root) == [_pytest_cmd(root)]


# --- the fix: detection-level (no subprocess) --------------------------------

def test_mixed_signals_return_both_commands_pytest_first(tmp_path: Path) -> None:
    root = _mixed_fixture(tmp_path)
    cmds = RunTestsSkill()._detect_commands(root)
    assert cmds == [_pytest_cmd(root), _JEST_CMD]


def test_mixed_detection_is_deterministic(tmp_path: Path) -> None:
    root = _mixed_fixture(tmp_path)
    skill = RunTestsSkill()
    assert skill._detect_commands(root) == skill._detect_commands(root)


def test_package_json_without_test_script_does_not_widen_python_suite(
        tmp_path: Path) -> None:
    # A package.json with NO scripts.test (e.g. a bundler config with zero
    # tests) must not spawn `npm test` alongside pytest — that would just fail
    # immediately (no script to run) and turn an honest pytest-only green into
    # a false red. Single-command, byte-identical to a pure-Python repo.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        '{ "name": "toolcfg", "version": "1.0.0" }\n', encoding="utf-8")
    assert RunTestsSkill()._detect_commands(tmp_path) == [_pytest_cmd(tmp_path)]


def test_package_json_with_empty_test_script_does_not_widen(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[build-system]\nrequires = []\n")
    (tmp_path / "package.json").write_text(
        '{ "scripts": { "test": "" } }\n', encoding="utf-8")
    assert RunTestsSkill()._detect_commands(tmp_path) == [_pytest_cmd(tmp_path)]


def test_package_json_with_non_dict_scripts_does_not_widen(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[build-system]\nrequires = []\n")
    (tmp_path / "package.json").write_text(
        '{ "scripts": "not-a-dict" }\n', encoding="utf-8")
    assert RunTestsSkill()._detect_commands(tmp_path) == [_pytest_cmd(tmp_path)]


def test_malformed_package_json_does_not_widen(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[build-system]\nrequires = []\n")
    (tmp_path / "package.json").write_text("{ not valid json", encoding="utf-8")
    assert RunTestsSkill()._detect_commands(tmp_path) == [_pytest_cmd(tmp_path)]


# --- _has_npm_test_script: pure unit cover of the gate -----------------------

def test_has_npm_test_script_true_for_string_test_entry(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{ "scripts": { "test": "jest" } }\n', encoding="utf-8")
    assert RunTestsSkill()._has_npm_test_script(tmp_path) is True


def test_has_npm_test_script_false_when_no_package_json(tmp_path: Path) -> None:
    assert RunTestsSkill()._has_npm_test_script(tmp_path) is False


def test_has_npm_test_script_false_when_no_scripts_key(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{ "name": "x" }\n', encoding="utf-8")
    assert RunTestsSkill()._has_npm_test_script(tmp_path) is False


def test_has_npm_test_script_false_when_test_is_not_a_string(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{ "scripts": { "test": 1 } }\n', encoding="utf-8")
    assert RunTestsSkill()._has_npm_test_script(tmp_path) is False


def test_has_npm_test_script_false_when_top_level_is_not_a_dict(
        tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('[1, 2, 3]\n', encoding="utf-8")
    assert RunTestsSkill()._has_npm_test_script(tmp_path) is False


# --- single-language behaviour stays byte-identical --------------------------

def test_pure_python_repo_unchanged(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8")
    assert RunTestsSkill()._detect_commands(tmp_path) == [_pytest_cmd(tmp_path)]


def test_pure_js_repo_unchanged(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{ "name": "d", "scripts": { "test": "jest" } }\n', encoding="utf-8")
    assert RunTestsSkill()._detect_commands(tmp_path) == [_JEST_CMD]


def test_pure_js_repo_with_no_test_script_unchanged(tmp_path: Path) -> None:
    # Preserves the EXISTING no-test-script convention on a pure-JS repo too:
    # package.json alone (no pytest signal at all) already triggers `npm test`
    # regardless of scripts.test — the gate added here narrows ONLY the mixed
    # branch, never this pre-existing single-language one.
    (tmp_path / "package.json").write_text('{"name": "x"}\n', encoding="utf-8")
    assert RunTestsSkill()._detect_commands(tmp_path) == [_JEST_CMD]


def test_neither_signal_stays_no_suite(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
    assert RunTestsSkill()._detect_commands(tmp_path) == []


# --- end-to-end: the real subprocess aggregation (needs node + jest) --------

def _node_ok() -> bool:
    return shutil.which("node") is not None and shutil.which("npm") is not None


_needs_node = pytest.mark.skipif(not _node_ok(), reason="node/npm not available")

_JEST_CACHE: dict[str, Path | None] = {}


def _ensure_jest_node_modules() -> Path | None:
    """A directory holding an installed jest ``node_modules``, or ``None`` when
    the install fails offline (caller then skips). Shares the SAME cache dir as
    ``test_js_gate_forced_eyml.py`` so a combined run installs jest at most
    once across both suites."""
    if "dir" in _JEST_CACHE:
        return _JEST_CACHE["dir"]
    base = Path(os.environ.get("TMPDIR", "/tmp")) / "apex_jest_cache_eyml"
    nm = base / "node_modules"
    if nm.is_dir():
        _JEST_CACHE["dir"] = nm
        return nm
    base.mkdir(parents=True, exist_ok=True)
    (base / "package.json").write_text('{ "name": "c", "version": "1.0.0" }\n',
                                       encoding="utf-8")
    try:
        proc = subprocess.run(
            ["npm", "install", "--prefer-offline", "--no-audit", "--no-fund",
             "jest@30"],
            cwd=str(base), capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        _JEST_CACHE["dir"] = None
        return None
    result = nm if (proc.returncode == 0 and nm.is_dir()) else None
    _JEST_CACHE["dir"] = result
    return result


def _real_mixed_repo(tmp_path: Path, *, jest_test_src: str) -> Path | None:
    """A MIXED repo with a REAL green pytest suite and a REAL jest suite whose
    single test's source is ``jest_test_src`` — installs the cached jest
    ``node_modules`` so ``npm test`` actually runs. ``None`` when jest can't be
    installed offline (caller skips)."""
    root = tmp_path / "demo"
    (root / "tests").mkdir(parents=True)
    (root / "__tests__").mkdir()
    (root / "tests" / "test_python_side.py").write_text(
        "def test_trivial():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    (root / "package.json").write_text(
        '{ "name": "d", "version": "1.0.0", "scripts": { "test": "jest" } }\n',
        encoding="utf-8")
    (root / "__tests__" / "js_side.test.js").write_text(jest_test_src,
                                                         encoding="utf-8")
    cached = _ensure_jest_node_modules()
    if cached is None:
        return None
    shutil.copytree(cached, root / "node_modules")
    return root


@_needs_node
def test_mixed_repo_red_jest_green_pytest_aggregates_not_ok(tmp_path: Path) -> None:
    # THE CRUX regression, non-tautological: pytest is GREEN, jest is RED. The
    # old first-match-wins detection would only ever have run pytest, so the
    # summary would have read ok=True (fake-green). The fix runs BOTH and must
    # aggregate to ok=False.
    root = _real_mixed_repo(
        tmp_path,
        jest_test_src='test("js side", () => { expect(1 + 1).toBe(3); });\n')
    if root is None:
        pytest.skip("jest could not be installed offline")
    summary = RunTestsSkill().run(root)
    assert summary.commands == [_pytest_cmd(root), _JEST_CMD]
    assert len(summary.results) == 2  # BOTH suites actually ran
    assert summary.ok is False  # the fix: red jest sinks the aggregate


@_needs_node
def test_mixed_repo_both_green_aggregates_ok(tmp_path: Path) -> None:
    # The other direction: when jest is ALSO green, the aggregate is green —
    # proves the fix does not over-refuse a genuinely healthy mixed repo.
    root = _real_mixed_repo(
        tmp_path,
        jest_test_src='test("js side", () => { expect(1 + 1).toBe(2); });\n')
    if root is None:
        pytest.skip("jest could not be installed offline")
    summary = RunTestsSkill().run(root)
    assert len(summary.results) == 2
    assert summary.ok is True
