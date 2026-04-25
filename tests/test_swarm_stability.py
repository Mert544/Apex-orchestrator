import time
import threading

from app.agents.swarm_stability import (
    SwarmTimeout,
    GracefulShutdown,
    SwarmStability,
    TimeoutError,
    with_timeout,
)


class TestSwarmTimeout:
    def test_timeout_creates_timer(self):
        timer = SwarmTimeout(default_timeout=30.0)
        callback_called = []

        def callback():
            callback_called.append(True)

        timer.set_timeout("test", 0.5, callback)
        time.sleep(0.6)
        assert len(callback_called) == 1

    def test_cancel_timeout(self):
        timer = SwarmTimeout(default_timeout=30.0)
        callback_called = []

        def callback():
            callback_called.append(True)

        timer.set_timeout("test", 0.5, callback)
        timer.cancel_timeout("test")
        time.sleep(0.6)
        assert len(callback_called) == 0

    def test_cancel_all(self):
        timer = SwarmTimeout(default_timeout=30.0)

        def callback():
            pass

        timer.set_timeout("test1", 0.5, callback)
        timer.set_timeout("test2", 0.5, callback)
        timer.cancel_all()
        assert len(timer._timers) == 0


class TestGracefulShutdown:
    def test_shutdown_request(self):
        shutdown = GracefulShutdown()
        assert shutdown.is_shutdown_requested() is False
        shutdown.request_shutdown()
        assert shutdown.is_shutdown_requested() is True

    def test_wait_for_agents_timeout(self):
        shutdown = GracefulShutdown()
        result = shutdown.wait_for_agents(timeout=0.1)
        assert result is False

    def test_agents_finished(self):
        shutdown = GracefulShutdown()
        shutdown.agents_finished()
        result = shutdown.wait_for_agents(timeout=0.1)
        assert result is True


class TestSwarmStability:
    def test_run_with_timeout_success(self):
        stability = SwarmStability(default_timeout=2.0)

        def slow_func():
            time.sleep(0.1)
            return "success"

        result = stability.run_with_timeout("test", slow_func, 1.0)
        assert result == "success"

    def test_run_with_timeout_timeout(self):
        stability = SwarmStability(default_timeout=0.5)

        def slow_func():
            time.sleep(2.0)
            return "success"

        try:
            stability.run_with_timeout("test", slow_func, 0.3)
            assert False, "Should have raised TimeoutError"
        except TimeoutError as e:
            assert "timed out" in str(e)

    def test_wait_with_shutdown_check(self):
        stability = SwarmStability(default_timeout=2.0)
        check_count = [0]

        def check():
            check_count[0] += 1
            return check_count[0] >= 3

        result = stability.wait_with_shutdown_check(check, timeout=1.0)
        assert result is True


class TestWithTimeoutDecorator:
    def test_decorator_success(self):
        @with_timeout(1.0, "default")
        def quick():
            return "ok"

        assert quick() == "ok"

    def test_decorator_timeout(self):
        @with_timeout(0.2, "default")
        def slow():
            time.sleep(1.0)
            return "ok"

        assert slow() == "default"
