from __future__ import annotations

import signal
import threading
from typing import Any, Callable


class TimeoutError(Exception):
    """Raised when an operation times out."""

    pass


class SwarmTimeout:
    """Timeout manager for swarm operations."""

    def __init__(self, default_timeout: float = 60.0) -> None:
        self.default_timeout = default_timeout
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def set_timeout(
        self, name: str, timeout: float, callback: Callable[[], None]
    ) -> None:
        """Set a timeout for a named operation."""
        with self._lock:
            if name in self._timers:
                self._timers[name].cancel()
            timer = threading.Timer(timeout, callback)
            self._timers[name] = timer
            timer.start()

    def cancel_timeout(self, name: str) -> None:
        """Cancel a named timeout."""
        with self._lock:
            if name in self._timers:
                self._timers[name].cancel()
                del self._timers[name]

    def cancel_all(self) -> None:
        """Cancel all pending timeouts."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()


class GracefulShutdown:
    """Manages graceful shutdown of swarm operations."""

    def __init__(self) -> None:
        self._shutdown_requested = False
        self._agents_finished = threading.Event()
        self._lock = threading.Lock()

    def request_shutdown(self) -> None:
        """Request graceful shutdown."""
        with self._lock:
            self._shutdown_requested = True

    def is_shutdown_requested(self) -> bool:
        """Check if shutdown was requested."""
        with self._lock:
            return self._shutdown_requested

    def wait_for_agents(self, timeout: float = 30.0) -> bool:
        """Wait for agents to finish. Returns True if agents finished within timeout."""
        return self._agents_finished.wait(timeout=timeout)

    def agents_finished(self) -> None:
        """Signal that all agents have finished."""
        self._agents_finished.set()


class SwarmStability:
    """Manages swarm stability with timeouts and graceful shutdown."""

    def __init__(
        self, default_timeout: float = 60.0, shutdown_timeout: float = 30.0
    ) -> None:
        self.timeout_manager = SwarmTimeout(default_timeout)
        self.shutdown_manager = GracefulShutdown()
        self.default_timeout = default_timeout
        self.shutdown_timeout = shutdown_timeout

    def run_with_timeout(
        self, name: str, func: Callable[[], Any], timeout: float | None = None
    ) -> Any:
        """Run a function with timeout."""
        timeout = timeout or self.default_timeout
        result = None
        exception = None

        def run():
            nonlocal result, exception
            try:
                result = func()
            except Exception as e:
                exception = e

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()
        thread.join(timeout)

        if thread.is_alive():
            self.timeout_manager.cancel_timeout(name)
            raise TimeoutError(f"Operation '{name}' timed out after {timeout}s")

        if exception:
            raise exception
        return result

    def wait_with_shutdown_check(
        self,
        check_func: Callable[[], bool],
        timeout: float | None = None,
    ) -> bool:
        """Wait for condition with shutdown support."""
        timeout = timeout or self.default_timeout
        import time

        waited = 0.0
        interval = 0.1

        while waited < timeout:
            if self.shutdown_manager.is_shutdown_requested():
                return False
            if check_func():
                return True
            time.sleep(interval)
            waited += interval

        return False


def with_timeout(timeout: float, default_return: Any = None):
    """Decorator to add timeout to a function."""

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            stability = SwarmStability(default_timeout=timeout)
            try:
                return stability.run_with_timeout(
                    func.__name__, lambda: func(*args, **kwargs), timeout
                )
            except TimeoutError:
                return default_return

        return wrapper

    return decorator


def with_graceful_shutdown(func: Callable) -> Callable:
    """Decorator to add graceful shutdown support to a function."""

    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        finally:
            if hasattr(self, "_stability") and self._stability:
                self._stability.shutdown_manager.request_shutdown()

    return wrapper
