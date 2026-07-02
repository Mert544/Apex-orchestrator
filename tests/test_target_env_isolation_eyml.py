"""The tool's own root never leaks into a TARGET project's child processes.

``scripts/verify.py`` pins the Apex repo root onto ``PYTHONPATH`` for every
chunk (so APEX-internal grandchildren import ``app`` on a bare environment).
These tests guard the OTHER half of that contract: when Apex spawns a child
for a TARGET project — impacted-test verification, value/doctest/import
oracles, determinism probes — the inherited pin must be scrubbed, because
Apex's ``app`` is a REGULAR package and silently defeats a target NAMESPACE
package of the same name regardless of path order. Before the scrub, a stub
target with ``app/calc.py`` (no ``__init__``) failed every impacted-test run
under the pinned gate (``ModuleNotFoundError: No module named 'app.calc'``)
and every landing rolled back — 17 tests across 4 chunk families went red
while passing in a bare shell. The end-to-end case here reproduces exactly
that geometry and must stay green under BOTH environments.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

from app.execution.target_env import _APEX_ROOT, inherited_pythonpath

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Unit: the scrub itself
# --------------------------------------------------------------------------- #


def test_apex_root_is_dropped(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT))
    assert inherited_pythonpath() == ""


def test_other_entries_survive_in_order(monkeypatch):
    keep_a, keep_b = "/somewhere/else", "relative/path"
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([keep_a, str(REPO_ROOT), keep_b]))
    assert inherited_pythonpath() == os.pathsep.join([keep_a, keep_b])


def test_unset_and_empty_entries(monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    assert inherited_pythonpath() == ""
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(["", str(REPO_ROOT), ""]))
    assert inherited_pythonpath() == ""


def test_unnormalized_apex_root_still_dropped(monkeypatch):
    """The pin may arrive with a trailing slash or ``..`` hops — still ours."""
    sloppy = str(REPO_ROOT / "app" / "..") + os.sep
    monkeypatch.setenv("PYTHONPATH", sloppy)
    assert inherited_pythonpath() == ""


def test_module_root_matches_this_checkout():
    assert _APEX_ROOT == REPO_ROOT


# --------------------------------------------------------------------------- #
# End-to-end: the exact failure geometry (namespace 'app' target under the pin)
# --------------------------------------------------------------------------- #


def _namespace_app_target(tmp_path: Path) -> Path:
    """A target whose top-level package is a NAMESPACE ``app`` (no __init__)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "calc.py").write_text(
        "def total(xs):\n    return sum(xs)\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text(textwrap.dedent("""\
        from app.calc import total

        def test_total():
            assert total([1, 2, 3]) == 6
        """), encoding="utf-8")
    return tmp_path


def test_target_pytest_green_under_pinned_gate_env(tmp_path, monkeypatch):
    """The impacted-test child env (target root + scrubbed tail) collects the
    target's namespace ``app`` even when the parent carries the gate's pin."""
    root = _namespace_app_target(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT))  # the chunk pin, inherited
    env = {**os.environ,
           "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(root) + os.pathsep + inherited_pythonpath()}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
         "tests"],
        cwd=str(root), capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_unscrubbed_pin_reproduces_the_shadowing(tmp_path, monkeypatch):
    """Characterize WHY the scrub exists: with the raw inherited pin appended,
    Apex's regular ``app`` defeats the target's namespace ``app`` and the same
    run fails collection. If CPython's precedence ever changes, this canary
    tells us the scrub became optional rather than silently redundant."""
    root = _namespace_app_target(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT))
    env = {**os.environ,
           "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(root) + os.pathsep + os.environ["PYTHONPATH"]}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
         "tests"],
        cwd=str(root), capture_output=True, text=True, env=env)
    assert proc.returncode != 0
    assert "No module named 'app.calc'" in proc.stdout
