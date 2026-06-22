from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.runtime.command_runner import CommandResult, CommandRunner, CommandSpec

# Defensive backstop. When a pytest command is run under an interpreter that has
# no ``pytest`` installed, the subprocess exits non-zero with a stderr line like
# ``/usr/local/bin/python: No module named pytest`` and an EMPTY stdout — there is
# no ``FAILED``/``ERROR`` node line, so the failing-node parser sees nothing and
# the run is misread as a RED suite. This signature recognises that exact case so
# the run can be flagged ``pytest_missing`` even if the proactive probe was
# bypassed (e.g. caller-supplied ``commands``). Matches optional quoting of the
# module name across Python versions.
_NO_PYTEST_RE = re.compile(r"No module named ['\"]?pytest['\"]?")

# Memoized result of the proactive ``-c "import pytest"`` probe, keyed by the
# interpreter path. Pure function of the interpreter on disk (no clock/random),
# so caching it is deterministic and keeps a session from re-spawning the probe
# once per objective. Cleared only by process exit.
_PYTEST_IMPORTABLE: dict[str, bool] = {}


@dataclass
class TestRunSummary:
    project_root: str
    commands: list[list[str]] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    ok: bool = False
    # HONEST verification-unavailable signal — DISTINCT from a red suite and from
    # a no-suite project. ``True`` only when pytest is not importable under the
    # interpreter Apex invoked (the proactive ``import pytest`` probe failed, or a
    # pytest run failed with the "No module named pytest" signature). A change can
    # never be verified in this state, so the orchestration layers decline rather
    # than misread it as RED and roll every move back. Defaults falsy so a summary
    # for a project WITH pytest is byte-identical to before.
    pytest_missing: bool = False
    # The interpreter path the missing pytest was probed/observed under, so the
    # loud diagnostic can name exactly which Python needs ``pip install pytest``
    # (or be pointed at the project's ``.venv``). Empty unless ``pytest_missing``.
    pytest_interpreter: str = ""


def pytest_importable(python: str) -> bool:
    """Whether ``pytest`` can be imported under interpreter ``python`` — MEMOIZED.

    A proactive ``<python> -c "import pytest"`` probe via the same allowlisted
    :class:`CommandRunner` the test runs use (``python`` is already allowed). The
    boolean is cached per interpreter path: the answer is a pure function of that
    interpreter's installed packages, so a develop session probing it once per
    objective re-uses the first result instead of re-spawning the subprocess.

    Deterministic and offline (no network, no clock, no randomness). Any failure
    to even launch the probe is treated as "not importable" — the conservative,
    never-fake-green reading (if we cannot prove pytest is present, we must not
    claim a run could verify anything)."""
    cached = _PYTEST_IMPORTABLE.get(python)
    if cached is not None:
        return cached
    try:
        result = CommandRunner().run(
            CommandSpec(command=[python, "-c", "import pytest"]))
        ok = bool(result.ok)
    except Exception:
        ok = False
    _PYTEST_IMPORTABLE[python] = ok
    return ok


class RunTestsSkill:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner()

    def run(self, project_root: str | Path, commands: list[list[str]] | None = None) -> TestRunSummary:
        root = Path(project_root).resolve()
        selected = commands or self._detect_commands(root)
        summary = TestRunSummary(project_root=str(root), commands=selected)
        if not selected:
            return summary

        # Run tests in the target project's own isolation. Set PYTHONPATH to the
        # target root ONLY, dropping the caller's entries, so the project's own
        # packages resolve and a caller's same-named package (e.g. Apex's own
        # `app/`) can't shadow the project under test.
        env = dict(os.environ)
        env["PYTHONPATH"] = str(root)
        # Force the subprocess to start in the target dir, not inherit ours.
        env.pop("PYTEST_ADDOPTS", None)

        # PROACTIVE verification-availability probe. When the selected command is
        # a ``<python> -m pytest`` invocation, confirm pytest is importable under
        # that interpreter BEFORE running it. A missing pytest would otherwise exit
        # non-zero with an empty stdout and be misread as a RED suite (and the
        # impact-scoping probes that follow can't import pytest EITHER), so every
        # landing is wrongly rolled back. Flagging it here lets the orchestration
        # layers decline honestly. Memoized per interpreter, so it costs at most
        # one extra probe subprocess per interpreter per process.
        interp = self._pytest_interpreter_of(selected)
        if interp and not pytest_importable(interp):
            summary.pytest_missing = True
            summary.pytest_interpreter = interp

        overall_ok = True
        for command in selected:
            result = self.runner.run(CommandSpec(command=command, cwd=root, env=env))
            summary.results.append(self._result_to_dict(result))
            overall_ok = overall_ok and result.ok
            # DEFENSIVE backstop: even if the proactive probe was bypassed (e.g. a
            # caller passed ``commands`` for a non-detected interpreter), a pytest
            # run that failed with the "No module named pytest" signature still
            # flags the state — never let it pass as a real RED suite.
            if not result.ok and not summary.pytest_missing:
                self._note_missing_from_stderr(summary, command, result)
        summary.ok = overall_ok
        return summary

    @staticmethod
    def _pytest_interpreter_of(commands: list[list[str]]) -> str:
        """The interpreter of the first ``<python> -m pytest`` command, or "".

        Pure inspection of the selected command list — the proactive probe runs
        only for a pytest invocation (a bare ``npm test`` has no Python to probe).
        Deterministic; no clock/random."""
        for cmd in commands:
            if len(cmd) >= 3 and cmd[1] == "-m" and cmd[2] == "pytest":
                return cmd[0]
        return ""

    @staticmethod
    def _note_missing_from_stderr(
        summary: TestRunSummary, command: list[str], result: CommandResult
    ) -> None:
        """Flag ``pytest_missing`` from a failed run's "No module named pytest"
        stderr signature (the backstop for a bypassed proactive probe)."""
        if _NO_PYTEST_RE.search(result.stderr or ""):
            summary.pytest_missing = True
            summary.pytest_interpreter = command[0] if command else ""

    def _python_for(self, root: Path) -> str:
        """The interpreter to run the target's tests with.

        Prefer the *target project's own* virtualenv so its dependencies resolve
        — this is what lets Apex verify fixes on an external project whose deps
        aren't installed in Apex's environment. Fall back to the current
        interpreter (sys.executable), never a bare `pytest` that could resolve to
        an unrelated Python.
        """
        candidates = (
            root / ".venv" / "bin" / "python",
            root / "venv" / "bin" / "python",
            root / ".venv" / "Scripts" / "python.exe",
            root / "venv" / "Scripts" / "python.exe",
        )
        for cand in candidates:
            if cand.exists():
                return str(cand)
        return sys.executable

    def _detect_commands(self, root: Path) -> list[list[str]]:
        if (
            (root / "pytest.ini").exists()
            or (root / "tests").exists()
            or (root / "pyproject.toml").exists()
            or self._has_flat_pytest_suite(root)
        ):
            # Run pytest via the target's own venv interpreter when present (so its
            # deps resolve), else the current interpreter — never a bare `pytest`
            # console script (which can resolve to a different Python without the
            # project's deps, making verify always "fail" and blocking every fix).
            return [[self._python_for(root), "-m", "pytest", "-q"]]
        if (root / "package.json").exists():
            return [["npm", "test", "--", "--runInBand"]]
        return []

    def _has_flat_pytest_suite(self, root: Path) -> bool:
        """True when the rootdir holds pytest-discoverable tests but no config.

        The most common student/flat-repo shape is `calc.py` + `test_calc.py`
        at the root with no `pyproject.toml`/`pytest.ini`/`tests/` — which
        `pytest` collects fine via its own default discovery, yet the existing
        config-only triggers miss, so the develop loop wrongly sees NO suite and
        marks every landed change `no-suite`. Mirror pytest's default discovery
        (`test_*.py` / `*_test.py`, plus a root `conftest.py`) at the rootdir and
        the obvious top-level package dirs.

        Bounded + deterministic: only the root and its immediate first-level
        subdirectories are scanned (no unbounded deep walk), via sorted globs so
        the same filesystem always yields the same verdict. Hidden dirs and the
        target's own virtualenv are skipped so a dependency's bundled tests can't
        false-trigger a suite for a repo that has none of its own.
        """
        if self._dir_has_pytest_files(root):
            return True
        skip = {".venv", "venv", ".git", "__pycache__", ".tox", "node_modules"}
        try:
            children = sorted(p for p in root.iterdir() if p.is_dir())
        except OSError:
            return False
        for child in children:
            if child.name in skip or child.name.startswith("."):
                continue
            if self._dir_has_pytest_files(child):
                return True
        return False

    @staticmethod
    def _dir_has_pytest_files(directory: Path) -> bool:
        """Whether `directory` directly contains a pytest-discoverable file."""
        for pattern in ("test_*.py", "*_test.py", "conftest.py"):
            if any(directory.glob(pattern)):
                return True
        return False

    def _result_to_dict(self, result: CommandResult) -> dict:
        return {
            "command": result.command,
            "cwd": result.cwd,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_seconds": result.duration_seconds,
            "timed_out": result.timed_out,
            "ok": result.ok,
        }
