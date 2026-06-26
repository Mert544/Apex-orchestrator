"""The FORCED jest gate — regression cover for the mixed-repo pytest fake-green.

``js-tdd-implement`` / ``js-implement-from-jsdoc`` accept a synthesised body iff a
throwaway copy's jest suite goes green. They used to run that copy through
:meth:`RunTestsSkill._detect_commands`, which is pytest-FIRST: on a "mixed" repo (a
JS package inside a Python monorepo, or a JS repo with one stray Python test under
``tests/``) the "jest gate" actually ran PYTEST, passed on the unrelated GREEN Python
test, and accepted the FIRST template body WITHOUT jest ever pinning it — a
provably-wrong body landed and was stamped verified (a never-fake-green breach).

:mod:`app.execution.js.js_gate` closes the hole: it FORCES the jest command
(``commands=`` bypasses detection) AND requires positive execution evidence (jest's
``Tests: N passed`` summary, with a non-zero count) so a ``--passWithNoTests`` /
no-tests-found run can't fake green either.

This module pins both halves:

* PURE unit cover of :func:`jest_ran_and_passed` / :data:`JEST_COMMAND` — always
  runs, no node/jest, proving the positive-execution parser and the refusal of every
  vacuous shape.
* The END-TO-END mixed-repo regression — a Python ``tests/test_x.py`` present, a
  ``subtract`` stub whose jest test pins ``a-b``: the wrong ``a+b`` template MUST be
  rejected (before the fix it landed). The legitimate ``a+b`` case still lands (no
  over-refusal). And a vacuous jest run refuses. These skip cleanly when node +
  global ``typescript`` + an installable jest aren't available, exactly like the
  sibling objective suites.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.execution.js.js_gate import (
    JEST_COMMAND,
    jest_ran_and_passed,
    run_jest_gate,
)
from app.execution.objectives.js_tdd_implement import (
    detect_js_stubs,
    plan_js_tdd_implement,
)
# Aliased to a non-``Test*`` name so pytest does not try to COLLECT the imported
# dataclass as a test class (it has an ``__init__``) — the data carrier the pure
# parser tests construct, never a test case.
from app.skills.execution.run_tests import RunTestsSkill
from app.skills.execution.run_tests import TestRunSummary as _RunSummary

from app.execution.js.js_tool import global_node_modules


# --- PURE unit cover of the positive-execution gate (always runs) -------------

def _summary(ok: bool, *, stdout: str = "", stderr: str = "",
             commands: list[list[str]] | None = None) -> _RunSummary:
    """A :class:`TestRunSummary` carrying one command result with the given captured
    text — the seam the parser reads, with no subprocess."""
    s = _RunSummary(project_root="/x",
                    commands=commands if commands is not None else [JEST_COMMAND])
    s.ok = ok
    s.results = [{"stdout": stdout, "stderr": stderr, "ok": ok}]
    return s


def test_jest_command_is_forced_npm_test_runinband():
    # The gate pins the project's OWN sanctioned jest entry point (npm test), NOT a
    # bare `pytest`/auto-detected command, and forwards --runInBand past npm's `--`.
    assert JEST_COMMAND == ["npm", "test", "--", "--runInBand"]


def test_green_with_passed_count_reads_green():
    # jest writes the Tests: summary to stderr; a non-zero passed count + rc=0 -> green.
    assert jest_ran_and_passed(_summary(True, stderr="Tests:       1 passed, 1 total"))


def test_green_with_skipped_and_passed_reads_green():
    assert jest_ran_and_passed(
        _summary(True, stderr="Tests:       1 skipped, 2 passed, 3 total"))


def test_passes_when_summary_is_on_stdout():
    # npm may echo the summary on stdout depending on wrapping — read both streams.
    assert jest_ran_and_passed(_summary(True, stdout="Tests:       4 passed, 4 total"))


def test_no_tests_found_passwithnotests_refuses():
    # The vacuous fake-green: rc=0 but NO Tests: summary line (jest printed
    # "No tests found, exiting with code 0"). Must read NOT green.
    assert not jest_ran_and_passed(
        _summary(True, stderr="No tests found, exiting with code 0"))


def test_zero_passed_summary_refuses():
    # A green run where every test was skipped/filtered (0 passed) proves nothing.
    assert not jest_ran_and_passed(
        _summary(True, stderr="Tests:       3 skipped, 0 of 3 total"))


def test_red_suite_refuses_even_with_a_summary_line():
    # rc!=0 is never green, regardless of any passed count in the failed-run summary.
    assert not jest_ran_and_passed(
        _summary(False, stderr="Tests:       1 failed, 2 passed, 3 total"))


def test_no_command_ran_refuses():
    # An empty command list (no suite ran at all) is never green.
    empty = _RunSummary(project_root="/x")
    empty.ok = True
    assert not jest_ran_and_passed(empty)


def test_takes_the_max_passed_across_results():
    # A multi-result run is read by its richest summary (the max passed count).
    s = _RunSummary(project_root="/x", commands=[JEST_COMMAND])
    s.ok = True
    s.results = [
        {"stdout": "", "stderr": "Tests:       0 passed, 0 total", "ok": True},
        {"stdout": "", "stderr": "Tests:       2 passed, 2 total", "ok": True},
    ]
    assert jest_ran_and_passed(s)


# --- the heavy END-TO-END mixed-repo regression (needs node + jest) -----------

def _node_ok() -> bool:
    """True when ``node`` is on PATH and the global ``typescript`` resolves — the
    minimum for the LLM-free driver (scan/mine/fill) to run."""
    if shutil.which("node") is None:
        return False
    nm = global_node_modules()
    return bool(nm) and (Path(nm) / "typescript").is_dir()


_needs_node = pytest.mark.skipif(not _node_ok(),
                                 reason="node + global typescript not available")

_JEST_CACHE: dict[str, Path | None] = {}


def _ensure_jest_node_modules() -> Path | None:
    """A directory holding an installed jest ``node_modules`` (shared session cache
    with the sibling objective suites so jest installs at most once), or ``None``
    when the install fails — the caller then skips."""
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


_SUBTRACT_JS = (
    "function subtract(a, b) {\n"
    '  throw new Error("Not implemented");\n'
    "}\n"
    "module.exports = { subtract };\n"
)


def _mixed_repo(tmp_path: Path, test_src: str) -> Path | None:
    """A MIXED repo: a JS ``subtract`` stub + its jest test (``test_src``) AND a
    GREEN, unrelated Python ``tests/test_x.py``. The Python ``tests/`` dir is what
    makes ``_detect_commands`` choose pytest-FIRST — the exact shape that used to
    fake-green. ``None`` when jest can't be installed offline (caller skips)."""
    root = tmp_path / "demo"
    (root / "src").mkdir(parents=True)
    (root / "__tests__").mkdir()
    (root / "tests").mkdir()
    (root / "package.json").write_text(
        '{ "name": "d", "version": "1.0.0", "scripts": { "test": "jest" } }\n',
        encoding="utf-8")
    (root / "src" / "calc.js").write_text(_SUBTRACT_JS, encoding="utf-8")
    (root / "__tests__" / "calc.test.js").write_text(test_src, encoding="utf-8")
    # The unrelated GREEN Python test pytest passes on (rc=0) — the fake-green bait.
    (root / "tests" / "test_unrelated.py").write_text(
        "def test_trivial():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    cached = _ensure_jest_node_modules()
    if cached is None:
        return None
    shutil.copytree(cached, root / "node_modules")
    return root


@_needs_node
def test_mixed_repo_rejects_wrong_template_no_pytest_fakegreen(tmp_path: Path):
    # THE REGRESSION. A jest test pins subtract(5,3)===2 (a - b). On a mixed repo
    # the OLD gate ran pytest, passed on the Python test, and accepted the FIRST
    # template `return a + b;` (subtract(5,3)=8 — jest RED). The forced-jest gate
    # rejects `a+b` and lands ONLY the `a-b` body jest actually verifies.
    root = _mixed_repo(
        tmp_path,
        'const { subtract } = require("../src/calc");\n'
        'test("subtract", () => {\n'
        "  expect(subtract(5, 3)).toBe(2);\n"
        "});\n")
    if root is None:
        pytest.skip("jest could not be installed offline")
    mbs = detect_js_stubs(str(root))
    assert [m.stub.name for m in mbs] == ["subtract"]
    plan = plan_js_tdd_implement(str(root), mbs[0])
    body = plan.new_contents.get("src/calc.js")
    assert body is not None, "the a-b template should land (jest verifies it)"
    assert "a - b" in body  # the body jest actually pins
    assert "a + b" not in body  # the fake-green body is REJECTED, never landed


@_needs_node
def test_mixed_repo_refuses_when_no_fixed_template_satisfies_jest(tmp_path: Path):
    # On the SAME mixed repo, a contract no fixed template meets (subtract(5,3)===7
    # is neither a-b=2 nor a+b=8 nor any other template) must REFUSE — the pytest
    # substitution previously would have fake-greened the FIRST template here too.
    root = _mixed_repo(
        tmp_path,
        'const { subtract } = require("../src/calc");\n'
        'test("subtract", () => {\n'
        "  expect(subtract(5, 3)).toBe(7);\n"
        "});\n")
    if root is None:
        pytest.skip("jest could not be installed offline")
    mbs = detect_js_stubs(str(root))
    plan = plan_js_tdd_implement(str(root), mbs[0])
    assert not plan.new_contents  # no fixed template flips jest green -> refuse
    assert not plan.blockers
    assert (root / "src" / "calc.js").read_text(encoding="utf-8") == _SUBTRACT_JS


@_needs_node
def test_mixed_repo_legit_jest_green_still_lands(tmp_path: Path):
    # The other direction: a jest test that passes for the FIRST template (a + b)
    # must STILL land it on the mixed repo — the fix must not OVER-refuse.
    root = _mixed_repo(
        tmp_path,
        'const { subtract } = require("../src/calc");\n'
        'test("acts as add here", () => {\n'
        "  expect(subtract(2, 3)).toBe(5);\n"  # 2 + 3 == 5 -> a+b is correct
        "});\n")
    if root is None:
        pytest.skip("jest could not be installed offline")
    mbs = detect_js_stubs(str(root))
    plan = plan_js_tdd_implement(str(root), mbs[0])
    body = plan.new_contents.get("src/calc.js")
    assert body is not None and "a + b" in body


@_needs_node
def test_run_jest_gate_refuses_vacuous_passwithnotests(tmp_path: Path):
    # A real jest run that finds NO tests but exits 0 (--passWithNoTests) must be
    # read as NOT green by the gate — an empty/vacuous gate can never fake green.
    root = tmp_path / "demo"
    root.mkdir(parents=True)
    (root / "package.json").write_text(
        '{ "name": "d", "version": "1.0.0", '
        '"scripts": { "test": "jest --passWithNoTests" } }\n', encoding="utf-8")
    (root / "src.js").write_text("module.exports = {};\n", encoding="utf-8")
    cached = _ensure_jest_node_modules()
    if cached is None:
        pytest.skip("jest could not be installed offline")
    shutil.copytree(cached, root / "node_modules")
    assert run_jest_gate(root, RunTestsSkill()) is False


@_needs_node
def test_run_jest_gate_green_on_a_real_passing_suite(tmp_path: Path):
    # The positive control: a real jest suite with a passing test reads green
    # through the forced gate (proves the parser sees genuine jest output).
    root = tmp_path / "demo"
    (root / "__tests__").mkdir(parents=True)
    (root / "package.json").write_text(
        '{ "name": "d", "version": "1.0.0", "scripts": { "test": "jest" } }\n',
        encoding="utf-8")
    (root / "__tests__" / "ok.test.js").write_text(
        'test("ok", () => { expect(1 + 1).toBe(2); });\n', encoding="utf-8")
    cached = _ensure_jest_node_modules()
    if cached is None:
        pytest.skip("jest could not be installed offline")
    shutil.copytree(cached, root / "node_modules")
    assert run_jest_gate(root, RunTestsSkill()) is True
