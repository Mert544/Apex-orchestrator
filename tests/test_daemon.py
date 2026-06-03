from __future__ import annotations

from pathlib import Path


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

    def test_autonomous_command_uses_auto(self, tmp_path):
        d = ApexDaemon(goal="", target=str(tmp_path), mode="supervised",
                       pid_file=str(tmp_path / "d.pid"))  # autonomous=True default
        cmd = d._build_command()
        assert "auto" in cmd and "run" not in cmd
        assert "--commit" not in cmd  # supervised doesn't commit

    def test_autonomous_command_commits_in_autonomous_mode(self, tmp_path):
        d = ApexDaemon(goal="harden", target=str(tmp_path), mode="autonomous",
                       pid_file=str(tmp_path / "d.pid"))
        cmd = d._build_command()
        assert "auto" in cmd and "--commit" in cmd
        assert "harden" in cmd  # goal passed through

    def test_legacy_command_uses_run(self, tmp_path):
        d = ApexDaemon(goal="scan", target=str(tmp_path), mode="report",
                       pid_file=str(tmp_path / "d.pid"), autonomous=False)
        cmd = d._build_command()
        assert "run" in cmd and "auto" not in cmd

    def test_run_apex_success(self, tmp_path, capsys):
        from unittest.mock import patch
        d = self._daemon(tmp_path)

        class _Res:
            returncode = 0
            stderr = ""

        with patch("subprocess.run", return_value=_Res()) as m:
            d._run_apex()
        cmd = m.call_args[0][0]
        # Daemon now drives the autonomous `apex auto` each cycle by default.
        assert "app.cli" in cmd and "auto" in cmd
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

    def test_start_runs_one_cycle_then_stops(self, tmp_path, capsys):
        # Drive the start() loop: stop the daemon from inside the first
        # _run_apex() so the loop exits after a single cycle. This exercises
        # PID write, signal-handler registration, the run/sleep loop, and the
        # graceful-shutdown PID cleanup.
        d = self._daemon(tmp_path)
        d.interval = 0.0  # no sleeping between cycles
        cycles = []

        def _one_cycle():
            cycles.append(True)
            d.stop()

        d._run_apex = _one_cycle
        d.start()

        assert cycles == [True]
        assert d._running is False
        # PID file is removed on graceful shutdown.
        assert not Path(d.pid_file).exists()
        out = capsys.readouterr().out
        assert "Started" in out and "Shut down gracefully" in out

    def test_signal_handler_stops_daemon(self, tmp_path):
        import signal
        prev_term = signal.getsignal(signal.SIGTERM)
        prev_int = signal.getsignal(signal.SIGINT)
        try:
            d = self._daemon(tmp_path)
            d._running = True
            d._register_signal_handlers()
            handler = signal.getsignal(signal.SIGTERM)
            handler(signal.SIGTERM, None)  # simulate SIGTERM delivery
            assert d._running is False
        finally:
            signal.signal(signal.SIGTERM, prev_term)
            signal.signal(signal.SIGINT, prev_int)

    def test_stop_running_corrupt_pid_file(self, tmp_path):
        pid_file = tmp_path / "d.pid"
        pid_file.write_text("not-a-number")
        # Corrupt PID -> ValueError -> file cleaned up, returns False.
        assert ApexDaemon.stop_running(pid_file) is False
        assert not pid_file.exists()
