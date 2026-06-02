from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app.runtime.command_runner import CommandResult, CommandRunner, CommandSpec


@dataclass
class TestRunSummary:
    project_root: str
    commands: list[list[str]] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    ok: bool = False


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

        overall_ok = True
        for command in selected:
            result = self.runner.run(CommandSpec(command=command, cwd=root, env=env))
            summary.results.append(self._result_to_dict(result))
            overall_ok = overall_ok and result.ok
        summary.ok = overall_ok
        return summary

    def _detect_commands(self, root: Path) -> list[list[str]]:
        if (root / "pytest.ini").exists() or (root / "tests").exists() or (root / "pyproject.toml").exists():
            return [["pytest", "-q"]]
        if (root / "package.json").exists():
            return [["npm", "test", "--", "--runInBand"]]
        return []

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
