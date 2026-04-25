from __future__ import annotations

import pytest

from app.runtime.command_runner import CommandPolicyError, CommandRunner, CommandSpec


def test_command_runner_allows_allowed_binary(tmp_path):
    runner = CommandRunner()
    result = runner.run(CommandSpec(command=["python", "--version"], cwd=tmp_path))
    assert result.ok


def test_command_runner_blocks_disallowed_binary(tmp_path):
    runner = CommandRunner()
    with pytest.raises(CommandPolicyError, match="not allowed"):
        runner.run(CommandSpec(command=["rm", "-rf", "/"], cwd=tmp_path))


def test_command_runner_rejects_empty_command(tmp_path):
    runner = CommandRunner()
    with pytest.raises(ValueError, match="empty"):
        runner.run(CommandSpec(command=[]))


def test_command_runner_custom_allowed_binaries(tmp_path):
    runner = CommandRunner(allowed_binaries={"python"})
    result = runner.run(CommandSpec(command=["python", "-c", "print('ok')"], cwd=tmp_path))
    assert result.ok


def test_command_runner_captures_stderr(tmp_path):
    runner = CommandRunner()
    result = runner.run(CommandSpec(command=["python", "-c", "import sys; sys.stderr.write('err')"], cwd=tmp_path))
    assert "err" in result.stderr


def test_command_runner_timeout(tmp_path):
    runner = CommandRunner()
    result = runner.run(CommandSpec(
        command=["python", "-c", "import time; time.sleep(10)"],
        cwd=tmp_path,
        timeout_seconds=1,
    ))
    assert result.timed_out
    assert not result.ok


def test_command_spec_dataclass():
    spec = CommandSpec(command=["ls"], cwd=None, timeout_seconds=30)
    assert spec.command == ["ls"]
    assert spec.timeout_seconds == 30
