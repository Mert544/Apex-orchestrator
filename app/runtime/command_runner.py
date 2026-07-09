from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass
class CommandSpec:
    command: list[str]
    cwd: Path | None = None
    timeout_seconds: int = 600
    env: Mapping[str, str] | None = None


@dataclass
class CommandResult:
    command: list[str]
    cwd: str
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class CommandPolicyError(RuntimeError):
    pass


class CommandRunner:
    DEFAULT_ALLOWED_BINARIES = {
        "git",
        "python",
        "python3",
        "pytest",
        "ruff",
        "mypy",
        "uv",
        "node",
        "npm",
        "pnpm",
        "yarn",
        "java",
    }

    def __init__(self, allowed_binaries: set[str] | None = None) -> None:
        self.allowed_binaries = allowed_binaries or set(self.DEFAULT_ALLOWED_BINARIES)

    def run(self, spec: CommandSpec) -> CommandResult:
        if not spec.command:
            raise ValueError("Command cannot be empty")

        # Match the allowlist by basename so an absolute interpreter path (e.g.
        # sys.executable = /usr/local/bin/python) is permitted when "python" is
        # allowed — without it, robust `sys.executable -m pytest` invocations are
        # wrongly blocked.
        binary = spec.command[0]
        if binary not in self.allowed_binaries and Path(binary).name not in self.allowed_binaries:
            raise CommandPolicyError(f"Binary not allowed by command policy: {binary}")

        cwd = spec.cwd.resolve() if spec.cwd is not None else Path.cwd()
        env = os.environ.copy()
        if spec.env:
            env.update(dict(spec.env))

        started = time.monotonic()
        try:
            completed = subprocess.run(
                spec.command,
                cwd=str(cwd),
                env=env,
                capture_output=True,
                text=True,
                timeout=spec.timeout_seconds,
                check=False,
            )
            return CommandResult(
                command=list(spec.command),
                cwd=str(cwd),
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_seconds=round(time.monotonic() - started, 4),
                timed_out=False,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                command=list(spec.command),
                cwd=str(cwd),
                returncode=124,
                stdout=_timeout_text(exc.stdout),
                stderr=_timeout_text(exc.stderr),
                duration_seconds=round(time.monotonic() - started, 4),
                timed_out=True,
            )


def _timeout_text(captured: object) -> str:
    """Normalize ``TimeoutExpired.stdout``/``.stderr`` to the ``str`` contract.

    CPython hands the timeout exception the RAW captured bytes even when the
    run was opened with ``text=True`` (only the successful-completion path
    decodes), so without this every downstream consumer of a timed-out
    ``CommandResult`` — failing-node parsing, delta-run validity, passed-count
    scans — meets ``bytes`` where the dataclass promises ``str`` and dies on
    ``str + bytes``. Found live by dogfooding ``apex develop --apply`` on
    Apex's own tree, whose backstop-baseline suite run times out."""
    if isinstance(captured, bytes):
        return captured.decode("utf-8", errors="replace")
    return captured or ""
