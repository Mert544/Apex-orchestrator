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


def test_command_runner_timeout_output_is_str(tmp_path):
    # CPython hands TimeoutExpired the RAW captured bytes even under text=True
    # (only the successful-completion path decodes), so without normalization a
    # timed-out result carries bytes where the dataclass promises str and every
    # downstream parser dies on `str + bytes`. Found live: apex develop --apply
    # on Apex's own tree (backstop-baseline suite run times out).
    runner = CommandRunner()
    result = runner.run(CommandSpec(
        command=["python", "-c",
                 "import sys, time; print('partial out'); sys.stdout.flush(); "
                 "sys.stderr.write('partial err'); sys.stderr.flush(); time.sleep(10)"],
        cwd=tmp_path,
        timeout_seconds=1,
    ))
    assert result.timed_out
    assert isinstance(result.stdout, str)
    assert isinstance(result.stderr, str)
    # The pre-timeout output survives the decode — honest partial evidence,
    # not an empty string that would hide what the run managed to say.
    assert "partial out" in result.stdout
    assert "partial err" in result.stderr


def test_timeout_text_normalizes_bytes_none_and_str():
    from app.runtime.command_runner import _timeout_text
    assert _timeout_text(b"caf\xc3\xa9") == "café"
    assert _timeout_text(b"\xff\xfe bad utf8") == "�� bad utf8"
    assert _timeout_text(None) == ""
    assert _timeout_text("already str") == "already str"
