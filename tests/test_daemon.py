from __future__ import annotations

from pathlib import Path

import pytest

from app.daemon import ApexDaemon


class TestApexDaemon:
    def test_pid_file_write_and_remove(self, tmp_path: Path):
        pid_file = tmp_path / "daemon.pid"
        daemon = ApexDaemon(goal="test", interval_sec=1.0, target=str(tmp_path), pid_file=str(pid_file))
        daemon._ensure_pid_dir()
        daemon._write_pid()
        assert pid_file.exists()
        assert int(pid_file.read_text().strip()) > 0
        daemon._remove_pid()
        assert not pid_file.exists()

    def test_is_running_false_when_no_pid(self, tmp_path: Path):
        pid_file = tmp_path / "daemon.pid"
        assert ApexDaemon.is_running(pid_file) is False

    def test_is_running_true_when_pid_exists(self, tmp_path: Path):
        pid_file = tmp_path / "daemon.pid"
        import os
        pid_file.write_text(str(os.getpid()))
        assert ApexDaemon.is_running(pid_file) is True

    def test_is_running_cleanup_stale_pid(self, tmp_path: Path, monkeypatch):
        pid_file = tmp_path / "daemon.pid"
        pid_file.write_text("99999")  # Non-existent PID
        import os
        def mock_kill(pid, sig):
            raise ProcessLookupError(pid)
        monkeypatch.setattr(os, "kill", mock_kill)
        assert ApexDaemon.is_running(pid_file) is False
        assert not pid_file.exists()

    def test_stop_running_success(self, tmp_path: Path, monkeypatch):
        pid_file = tmp_path / "daemon.pid"
        import os
        import signal
        pid_file.write_text(str(os.getpid()))
        killed = []
        def mock_kill(pid, sig):
            killed.append((pid, sig))
        monkeypatch.setattr(os, "kill", mock_kill)
        assert ApexDaemon.stop_running(pid_file) is True
        assert len(killed) == 1
        assert killed[0][1] == signal.SIGTERM

    def test_stop_running_no_pid(self, tmp_path: Path):
        pid_file = tmp_path / "daemon.pid"
        assert ApexDaemon.stop_running(pid_file) is False


class TestDaemonRunAndStop:
    def _daemon(self, tmp_path):
        return ApexDaemon(goal="audit", target=str(tmp_path), pid_file=str(tmp_path / "d.pid"))

    def test_stop_sets_flag(self, tmp_path):
        d = self._daemon(tmp_path)
        d._running = True
        d.stop()
        assert d._running is False

    def test_run_apex_success(self, tmp_path, capsys):
        from unittest.mock import patch
        d = self._daemon(tmp_path)

        class _Res:
            returncode = 0
            stderr = ""

        with patch("subprocess.run", return_value=_Res()) as m:
            d._run_apex()
        cmd = m.call_args[0][0]
        assert "app.cli" in cmd and "run" in cmd
        assert "successfully" in capsys.readouterr().out.lower()

    def test_run_apex_failure(self, tmp_path, capsys):
        from unittest.mock import patch
        d = self._daemon(tmp_path)

        class _Res:
            returncode = 2
            stderr = "boom"

        with patch("subprocess.run", return_value=_Res()):
            d._run_apex()
        assert "failed" in capsys.readouterr().out.lower()

    def test_run_apex_timeout(self, tmp_path, capsys):
        import subprocess
        from unittest.mock import patch
        d = self._daemon(tmp_path)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 300)):
            d._run_apex()
        assert "timed out" in capsys.readouterr().out.lower()

    def test_run_apex_generic_error(self, tmp_path, capsys):
        from unittest.mock import patch
        d = self._daemon(tmp_path)
        with patch("subprocess.run", side_effect=RuntimeError("nope")):
            d._run_apex()
        assert "error" in capsys.readouterr().out.lower()
