from __future__ import annotations

import atexit
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


class ApexDaemon:
    """Periodic background runner for Apex Orchestrator.

    Usage:
        daemon = ApexDaemon(goal="security audit", interval_sec=3600)
        daemon.start()
        # Runs apex every hour; writes PID to .apex/daemon.pid
    """

    def __init__(
        self,
        goal: str,
        interval_sec: float = 3600.0,
        target: str | None = None,
        mode: str = "supervised",
        pid_file: str | None = None,
        autonomous: bool = True,
    ) -> None:
        self.goal = goal
        self.interval = interval_sec
        self.target = target or str(Path.cwd())
        self.mode = mode
        # Autonomous daemons run `apex auto` each cycle, so the AutonomyPolicy
        # decides per-cycle whether to apply safe fixes (clean tree) or just
        # review (dirty tree). Legacy daemons run the older `apex run` pipeline.
        self.autonomous = autonomous
        self.pid_file = Path(pid_file) if pid_file else Path(self.target) / ".apex" / "daemon.pid"
        self._running = False

    def start(self) -> None:
        self._ensure_pid_dir()
        self._write_pid()
        self._register_signal_handlers()
        atexit.register(self._remove_pid)

        self._running = True
        print(f"[daemon] Started. Goal: {self.goal}")
        print(f"[daemon] Interval: {self.interval}s | Target: {self.target}")
        print(f"[daemon] PID: {os.getpid()} | PID file: {self.pid_file}")

        while self._running:
            self._run_apex()
            # Sleep in chunks to allow responsive shutdown
            slept = 0.0
            while slept < self.interval and self._running:
                time.sleep(min(1.0, self.interval - slept))
                slept += 1.0

        self._remove_pid()
        print("[daemon] Shut down gracefully.")

    def stop(self) -> None:
        self._running = False

    def _build_command(self) -> list[str]:
        """The CLI command run each cycle.

        Autonomous: `apex auto --apply` — the daemon is the EXPLICIT opt-in to
        unattended application, so it passes ``--apply`` (the bare `apex auto`
        now PREVIEWS by default, the footgun fix). The covered-only sweep still
        lands only moves a test exercises, and the AutonomyPolicy + git gate keep
        it from clobbering a dirty tree (it commits when mode is autonomous).
        Legacy: the older goal-driven `apex run`.
        """
        if not self.autonomous:
            return [
                sys.executable, "-m", "app.cli", "run",
                "--goal", self.goal, "--target", self.target, "--mode", self.mode,
            ]
        cmd = [sys.executable, "-m", "app.cli", "auto", "--apply",
               "--target", self.target, "--mode", self.mode]
        if self.goal:
            cmd.append(self.goal)
        if self.mode == "autonomous":
            cmd.append("--commit")
        return cmd

    def _build_env(self) -> dict[str, str]:
        """The child-process environment for the per-cycle ``apex`` subprocess.

        Stamps ``APEX_DAEMON=1`` onto the parent's environment so the child
        ``apex auto --apply`` recognises it is running UNATTENDED — no human is
        reviewing the diff between cycles. ``_auto_unattended`` (cli_autonomy.py)
        reads exactly this var to force the ``covered_only`` verification gate
        (via ``resolve_covered_only``), which refuses a green-but-uncovered
        (WEAK) move from landing silently. Without this, the daemon's subprocess
        silently ran the ATTENDED branch — the exact crack this closes. A plain
        dict merge (no clock/random) so it stays deterministic."""
        return {**os.environ, "APEX_DAEMON": "1"}

    def _run_apex(self) -> None:
        cmd = self._build_command()
        env = self._build_env()
        print(f"[daemon] Running: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
            if result.returncode == 0:
                print("[daemon] Run completed successfully.")
            else:
                print(f"[daemon] Run failed (code {result.returncode}): {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            print("[daemon] Run timed out after 300s.")
        except Exception as exc:
            print(f"[daemon] Run error: {exc}")

    def _ensure_pid_dir(self) -> None:
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)

    def _write_pid(self) -> None:
        self.pid_file.write_text(str(os.getpid()))

    def _remove_pid(self) -> None:
        if not (self.pid_file.exists()):
            return
        self.pid_file.unlink()

    def _register_signal_handlers(self) -> None:
        def _handler(signum, _frame):
            print(f"\n[daemon] Received signal {signum}, shutting down...")
            self.stop()

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)

    @classmethod
    def is_running(cls, pid_file: Path | None = None) -> bool:
        default = Path.cwd() / ".apex" / "daemon.pid"
        pf = pid_file or default
        if not pf.exists():
            return False
        try:
            pid = int(pf.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            return True
        except (ValueError, OSError, ProcessLookupError):
            pf.unlink(missing_ok=True)
            return False

    @classmethod
    def stop_running(cls, pid_file: Path | None = None) -> bool:
        default = Path.cwd() / ".apex" / "daemon.pid"
        pf = pid_file or default
        if not pf.exists():
            return False
        try:
            pid = int(pf.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            return True
        except (ValueError, OSError, ProcessLookupError):
            pf.unlink(missing_ok=True)
            return False
