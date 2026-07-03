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
        # P4 (docs/rnd/context-fragile-tests.md #2): wait on the callback's own
        # Event with a hang-guard budget instead of racing a 0.5s timer against a
        # 0.6s sleep — the invariant is fired/not-fired, never fired-within-margin.
        timer = SwarmTimeout(default_timeout=30.0)
        fired = threading.Event()
        callback_called = []

        def callback():
            callback_called.append(True)
            fired.set()

        timer.set_timeout("test", 0.01, callback)
        assert fired.wait(timeout=30.0), "timer callback never fired"
        assert callback_called == [True]

    def test_cancel_timeout(self):
        # P4 (docs/rnd/context-fragile-tests.md #2): a hang-guard-scale interval
        # (60s) makes a spurious fire impossible under any load, and joining the
        # cancelled Timer thread PROVES the callback can no longer run — strictly
        # stronger than sleeping 0.6s and hoping cancel won a 100ms race.
        timer = SwarmTimeout(default_timeout=30.0)
        callback_called = []

        def callback():
            callback_called.append(True)

        timer.set_timeout("test", 60.0, callback)
        timer_obj = timer._timers["test"]
        timer.cancel_timeout("test")
        assert "test" not in timer._timers
        timer_obj.join(timeout=30.0)  # cancelled Timer thread exits without firing
        assert not timer_obj.is_alive()
        assert not callback_called

    def test_cancel_all(self):
        timer = SwarmTimeout(default_timeout=30.0)

        def callback():
            pass

        timer.set_timeout("test1", 0.5, callback)
        timer.set_timeout("test2", 0.5, callback)
        timer.cancel_all()
        assert not timer._timers


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
        # P4 (docs/rnd/context-fragile-tests.md #2): success means "the finished
        # function's result comes back", not "beats a 1s stopwatch under load" —
        # instant worker + hang-guard budget, plus a call-count proof it ran once.
        stability = SwarmStability(default_timeout=2.0)
        calls = []

        def func():
            calls.append(True)
            return "success"

        result = stability.run_with_timeout("test", func, 30.0)
        assert result == "success"
        assert calls == [True]

    def test_run_with_timeout_timeout(self):
        # P4 (docs/rnd/context-fragile-tests.md #2): the worker blocks on an Event
        # the test only releases AFTER the timeout fired, so the timeout MUST
        # trigger regardless of load — no 2.0s-sleep vs 0.3s-join margin.
        stability = SwarmStability(default_timeout=0.5)
        release = threading.Event()

        def blocked():
            release.wait(timeout=60.0)  # hang-guard so the daemon thread always exits
            return "success"

        try:
            try:
                stability.run_with_timeout("test", blocked, 0.05)
                assert False, "Should have raised TimeoutError"
            except TimeoutError as e:
                assert "timed out" in str(e)
        finally:
            release.set()

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
        # P4 (docs/rnd/context-fragile-tests.md #2): hang-guard budget — the
        # contract is "a finished function's value is returned, not the default",
        # not "the worker thread gets scheduled within 1s of wall clock".
        @with_timeout(30.0, "default")
        def quick():
            return "ok"

        assert quick() == "ok"

    def test_decorator_timeout(self):
        # P4 (docs/rnd/context-fragile-tests.md #2): Event-blocked worker — the
        # default MUST come back under any load, because the worker cannot finish
        # until released after the assertion.
        release = threading.Event()

        @with_timeout(0.05, "default")
        def slow():
            release.wait(timeout=60.0)  # hang-guard so the daemon thread always exits
            return "ok"

        try:
            assert slow() == "default"
        finally:
            release.set()
