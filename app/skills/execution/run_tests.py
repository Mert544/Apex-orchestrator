from __future__ import annotations

import ast
import json
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
        # target root (FIRST, dropping the caller's entries), so the project's own
        # packages resolve and a caller's same-named package (e.g. Apex's own
        # `app/`) can't shadow the project under test. A separated `src/`/`lib/`
        # layout adds its source dir too, but ONLY when a test imports a module
        # that lives there by bare stem (see ``_import_roots``) — otherwise
        # ``import mod`` is unresolvable, collection errors, and the GREEN baseline
        # is misread as RED so Apex lands nothing.
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(self._import_roots(root))
        # Force the subprocess to start in the target dir, not inherit ours.
        env.pop("PYTEST_ADDOPTS", None)
        # DETERMINISM: never write ``.pyc`` for the project under test. CPython's
        # default (timestamp) bytecode invalidation stores the source mtime as a
        # WHOLE-SECOND integer, so a file rewritten and re-tested within the same
        # second as a cached ``.pyc`` is served STALE bytecode. The develop-loop
        # does exactly that — a move rewrites a module, then the end-of-session
        # regression backstop re-runs the suite — so a stale read could make a
        # real regression INTERMITTENTLY invisible (the rollback fires on one run
        # and not the next on byte-identical input). Writing no cache means every
        # run compiles from the CURRENT source: same input -> same result, and we
        # never litter the user's project with Apex's bytecode either.
        env["PYTHONDONTWRITEBYTECODE"] = "1"

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
        has_pytest_signal = (
            (root / "pytest.ini").exists()
            or (root / "tests").exists()
            or (root / "pyproject.toml").exists()
            or self._has_flat_pytest_suite(root)
        )
        has_js_signal = (root / "package.json").exists()
        if has_pytest_signal and has_js_signal and self._has_npm_test_script(root):
            # MIXED repo — a pytest signal (tests/, pyproject.toml, ...) AND a
            # package.json with a genuine ``scripts.test`` entry both present (the
            # most common team-repo shape: a Python service alongside a JS/TS
            # front end or tool). ``_detect_commands`` used to be FIRST-MATCH-WINS
            # here — it returned the pytest command and never reached this branch,
            # so a jest suite could regress and a "verified" proof was still
            # written (a never-fake-green breach on the moat's own detector).
            # Returning BOTH commands makes ``run()``'s own aggregation loop (it
            # already ANDs ``result.ok`` across every selected command) the single
            # place that decides green — a project is green ONLY when every
            # detected suite is green. The JS command is the SAME one the pure-JS
            # branch below already runs, so pinning it here changes nothing about
            # HOW jest is invoked, only THAT it now runs alongside pytest.
            return [
                [self._python_for(root), "-m", "pytest", "-q"],
                ["npm", "test", "--", "--runInBand"],
            ]
        if has_pytest_signal:
            # Run pytest via the target's own venv interpreter when present (so its
            # deps resolve), else the current interpreter — never a bare `pytest`
            # console script (which can resolve to a different Python without the
            # project's deps, making verify always "fail" and blocking every fix).
            return [[self._python_for(root), "-m", "pytest", "-q"]]
        if has_js_signal:
            return [["npm", "test", "--", "--runInBand"]]
        return []

    @staticmethod
    def _has_npm_test_script(root: Path) -> bool:
        """Whether ``root/package.json`` declares a genuine ``scripts.test`` entry.

        Gates the MIXED-repo branch only (never the pure-JS branch below, which
        stays keyed off ``package.json`` existing alone — byte-identical to
        before): a ``package.json`` with no ``test`` script (e.g. a front-end
        build-tool config with zero tests) must not widen a Python project's
        suite to also spawn ``npm test``, which would just fail immediately and
        turn an honest pytest-only green into a false red. Conservative and
        deterministic — a missing file, malformed JSON, a non-dict ``scripts``,
        or an empty/non-string ``test`` value all read as "no script" (never
        widen on a guess); no clock/random."""
        try:
            data = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(data, dict):
            return False
        scripts = data.get("scripts")
        if not isinstance(scripts, dict):
            return False
        test_script = scripts.get("test")
        return isinstance(test_script, str) and bool(test_script.strip())

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

    def _import_roots(self, root: Path) -> list[str]:
        """The PYTHONPATH entries for the target's tests — root first, then any
        genuine separated source dir (``src``/``lib``).

        The flat shape (``mod.py`` + ``tests/test_mod.py`` doing ``import mod``)
        is already served by ``str(root)`` alone. The SEPARATED shape
        (``src/mod.py`` + ``tests/test_mod.py`` doing ``import mod``) is the
        surviving gap: with only ``root`` on the path, ``import mod`` is
        unresolvable, pytest collection errors, and the GREEN baseline is misread
        as RED — so Apex lands nothing on a whole class of student/company repos.

        A ``src``/``lib`` dir is added ONLY when a test imports a module that
        actually lives there by bare stem, so the path is never blindly widened
        (a soundness guard against shadowing). ``str(root)`` stays FIRST so a
        same-named package under ``src/`` can never shadow the target's own root
        modules or Apex's ``app/``.

        Bounded + deterministic, mirroring ``_has_flat_pytest_suite``: only the
        first-level ``src``/``lib`` dirs and the top-level ``*.py`` modules inside
        them are inspected (no deep walk), via sorted globs, and the result is
        sorted, so the same filesystem always yields the same path."""
        roots = [str(root)]
        imported = self._bare_stem_imports(root)
        if not imported:
            return roots
        extra: list[str] = []
        for name in ("src", "lib"):
            candidate = root / name
            if not candidate.is_dir():
                continue
            if self._dir_supplies_imported_module(candidate, imported):
                extra.append(str(candidate))
        return roots + sorted(extra)

    @staticmethod
    def _dir_supplies_imported_module(directory: Path, imported: set[str]) -> bool:
        """Whether `directory` directly holds a top-level ``*.py`` module whose
        bare stem is in `imported` (bounded to its own first level — no walk)."""
        try:
            modules = sorted(p.stem for p in directory.glob("*.py"))
        except OSError:
            return False
        return any(stem in imported for stem in modules)

    def _bare_stem_imports(self, root: Path) -> set[str]:
        """The set of bare-stem module names imported by the project's tests.

        ``import mod`` / ``from mod import x`` contribute ``mod``; a dotted form
        (``import pkg.mod`` / ``from pkg.mod import x``) does NOT — only a
        top-level ``src/mod.py`` / ``lib/mod.py`` is reachable by adding that dir
        to the path, so dotted imports can't be served this way and are ignored.

        Bounded + deterministic like ``_has_flat_pytest_suite``: only test files
        directly in the root and its immediate first-level subdirectories are
        read (no deep walk), via sorted globs, skipping hidden dirs and the
        target's own virtualenv so a dependency's bundled tests can't widen the
        path for a repo that has none of its own."""
        names: set[str] = set()
        self._collect_imports_from_dir(root, names)
        skip = {".venv", "venv", ".git", "__pycache__", ".tox", "node_modules"}
        try:
            children = sorted(p for p in root.iterdir() if p.is_dir())
        except OSError:
            return names
        for child in children:
            if child.name in skip or child.name.startswith("."):
                continue
            self._collect_imports_from_dir(child, names)
        return names

    def _collect_imports_from_dir(self, directory: Path, names: set[str]) -> None:
        """Add bare-stem imports from the pytest files directly in `directory`."""
        for pattern in ("test_*.py", "*_test.py", "conftest.py"):
            for path in sorted(directory.glob(pattern)):
                names.update(self._bare_imports_in_file(path))

    @staticmethod
    def _bare_imports_in_file(path: Path) -> set[str]:
        """The bare-stem (single-segment) module names imported by `path`.

        AST-parsed so a name in a string/comment never counts; a syntax error or
        read failure yields no names (conservative — never widen the path on a
        guess). Dotted imports are excluded (their top segment is a package, not a
        ``src/mod.py``-style bare module)."""
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            return set()
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "." not in alias.name:
                        names.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module and "." not in node.module:
                    names.add(node.module)
        return names

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
