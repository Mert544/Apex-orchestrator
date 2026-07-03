from __future__ import annotations

import time
import urllib.request

import pytest

from app.engine.distributed_swarm import (
    CircuitBreaker,
    CircuitBreakerOpen,
    DistributedSwarmCoordinator,
    DistributedSwarmResult,
    SwarmNode,
    SwarmNodeServer,
)


def _wait_for_server(url: str, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1) as resp:
                return resp.status == 200
        except Exception:
            time.sleep(0.1)
    return False


def test_swarm_node_url():
    node = SwarmNode("node-1", "127.0.0.1", 18765)
    assert node.url("/health") == "http://127.0.0.1:18765/health"
    assert node.url() == "http://127.0.0.1:18765"


def test_distributed_result_to_dict():
    r = DistributedSwarmResult(
        aggregated_output={"k": "v"}, errors=["e"], nodes_completed=1, nodes_failed=0
    )
    d = r.to_dict()
    assert d["nodes_completed"] == 1
    assert d["errors"] == ["e"]


def test_coordinator_no_online_nodes():
    coord = DistributedSwarmCoordinator([SwarmNode("n1", "127.0.0.1", 59998)])
    result = coord.run("scan", [{"item": 1}])
    assert result.nodes_completed == 0
    assert len(result.errors) == 1
    assert "No online nodes" in result.errors[0]


class TestSwarmNodeServer:
    @pytest.fixture(scope="class")
    def swarm_server(self):
        # Use port=0 to let OS assign a free port
        server = SwarmNodeServer("test-node", host="127.0.0.1", port=0)
        server.register_task("echo", lambda p: {"received": p})
        import threading
        t = threading.Thread(target=server.start, daemon=True)
        t.start()
        # Wait for server thread to bind the socket
        for _ in range(50):
            if server.actual_port != 0:
                break
            time.sleep(0.1)
        actual_port = server.actual_port
        url = f"http://127.0.0.1:{actual_port}/health"
        if not _wait_for_server(url, timeout=5.0):
            pytest.fail("SwarmNodeServer did not start in time")
        yield server
        server.stop()
        # P4 (docs/rnd/context-fragile-tests.md #4): join the server thread with a
        # hang-guard instead of a fixed 0.3s sleep — the accept loop has provably
        # exited (and the socket is closed) when join returns.
        t.join(timeout=30.0)

    def test_node_server_health(self, swarm_server):
        port = swarm_server.actual_port
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode("utf-8")
            import json
            body = json.loads(data)
            assert body["status"] == "ok"
            assert body["node_id"] == "test-node"

    def test_node_server_execute(self, swarm_server):
        import json
        port = swarm_server.actual_port
        body = json.dumps({"task": "echo", "payload": {"x": 42}}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/execute",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["node_id"] == "test-node"
            assert data["result"]["received"]["x"] == 42

    def test_node_server_unknown_task(self, swarm_server):
        import json
        port = swarm_server.actual_port
        body = json.dumps({"task": "nope", "payload": {}}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/execute",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert "Unknown task" in data["error"]

    def test_distributed_run_e2e(self, swarm_server):
        port = swarm_server.actual_port
        coord = DistributedSwarmCoordinator([SwarmNode("test-node", "127.0.0.1", port)])
        result = coord.run("echo", [{"x": 1}, {"x": 2}])
        assert result.nodes_completed == 2
        assert result.nodes_failed == 0
        assert len(result.aggregated_output["responses"]) == 2

    def test_distributed_run_with_aggregator(self, swarm_server):
        port = swarm_server.actual_port
        coord = DistributedSwarmCoordinator([SwarmNode("test-node", "127.0.0.1", port)])
        result = coord.run(
            "echo",
            [{"x": 1}, {"x": 2}],
            aggregator=lambda responses: {"total_x": sum(r["result"]["received"]["x"] for r in responses)},
        )
        assert result.nodes_completed == 2
        assert result.aggregated_output.get("total_x") == 3


class TestCircuitBreaker:
    def test_circuit_breaker_success(self):
        cb = CircuitBreaker(failure_threshold=2)
        result = cb.call(lambda: 42)
        assert result == 42
        assert cb.state == cb.CLOSED

    def test_circuit_breaker_opens_after_failures(self):
        cb = CircuitBreaker(failure_threshold=2)
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        assert cb.state == cb.CLOSED
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        assert cb.state == cb.OPEN
        with pytest.raises(CircuitBreakerOpen):
            cb.call(lambda: 42)

    def test_circuit_breaker_half_open_recovery(self):
        # P4 (docs/rnd/context-fragile-tests.md #4): drive the recovery window by
        # rewinding the breaker's recorded failure time instead of sleeping over a
        # 50ms margin — zero clock margin, zero wall time. Also proves (stronger
        # than before) that the OPEN state still rejects BEFORE the window passes.
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        assert cb.state == cb.OPEN
        with pytest.raises(CircuitBreakerOpen):
            cb.call(lambda: 42)  # recovery window not yet passed: still rejecting
        cb.last_failure_time = 0.0  # deterministically move the failure past the window
        result = cb.call(lambda: 42)
        assert result == 42
        assert cb.state == cb.CLOSED

    def test_circuit_breaker_success_resets_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        assert cb.failures == 1
        cb.call(lambda: 42)
        assert cb.failures == 0
        assert cb.state == cb.CLOSED


class TestSwarmNodeServerLifecycle:
    def test_server_start_stop(self):
        server = SwarmNodeServer("lifecycle-node", host="127.0.0.1", port=0)
        import threading
        t = threading.Thread(target=server.start, daemon=True)
        t.start()
        for _ in range(50):
            if server.actual_port != 0:
                break
            time.sleep(0.1)
        actual_port = server.actual_port
        assert _wait_for_server(f"http://127.0.0.1:{actual_port}/health", timeout=3.0)
        server.stop()
        # P4 (docs/rnd/context-fragile-tests.md #4): join the server thread with a
        # hang-guard instead of sleeping 0.3s and hoping stop() took effect — the
        # dead thread PROVES the accept loop exited and the socket is closed, so
        # the negative connect check below is deterministic (connection refused).
        t.join(timeout=30.0)
        assert not t.is_alive()
        assert not _wait_for_server(f"http://127.0.0.1:{actual_port}/health", timeout=0.5)
