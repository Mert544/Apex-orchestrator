"""Edge / error-path tests for distributed_swarm.

Covers the except branches and degenerate paths of the coordinator and the
node server that the happy-path tests in test_distributed_swarm.py don't reach:
circuit-breaker-open dispatch, error responses, raw HTTP parsing of malformed
requests, and the server lifecycle teardown branches.
"""

from __future__ import annotations

import json
import socket

from app.engine.distributed_swarm import (
    CircuitBreaker,
    DistributedSwarmCoordinator,
    SwarmNode,
    SwarmNodeServer,
)


# --- coordinator register / dispatch error paths -----------------------------

def test_register_node_appends():
    coord = DistributedSwarmCoordinator()
    node = SwarmNode("n1", "127.0.0.1", 1)
    coord.register_node(node)
    assert coord.nodes == [node]


def test_execute_on_node_returns_error_dict_on_exception():
    """A failed urllib call is caught and returned as an {'error': ...} dict."""
    coord = DistributedSwarmCoordinator()
    node = SwarmNode("dead", "127.0.0.1", 59997)
    resp = coord._execute_on_node(node, "scan", {})
    assert "error" in resp


def test_execute_on_node_circuit_breaker_open_returns_error():
    """When the node's breaker is already OPEN, dispatch short-circuits."""
    coord = DistributedSwarmCoordinator()
    node = SwarmNode("flaky", "127.0.0.1", 59996)
    # Pre-open the breaker for this node id (threshold default 3).
    cb = CircuitBreaker(failure_threshold=1)
    cb.state = cb.OPEN
    cb.last_failure_time = float("inf")  # never recovers within test
    coord._circuits[node.node_id] = cb
    resp = coord._execute_on_node(node, "scan", {})
    assert resp == {"error": f"Circuit breaker OPEN for {node.node_id}"}


def test_run_records_failed_node_with_error(monkeypatch):
    """An online node whose execute returns an error increments nodes_failed
    and appends the formatted error string (lines 163-165)."""
    coord = DistributedSwarmCoordinator([SwarmNode("n1", "127.0.0.1", 1)])
    monkeypatch.setattr(coord, "_is_online", lambda node: True)
    monkeypatch.setattr(
        coord, "_execute_on_node", lambda node, task, item: {"error": "boom"}
    )
    result = coord.run("scan", [{"x": 1}])
    assert result.nodes_failed == 1
    assert result.nodes_completed == 0
    assert result.errors == ["n1: boom"]


def test_run_aggregator_receives_successful_responses(monkeypatch):
    coord = DistributedSwarmCoordinator([SwarmNode("n1", "127.0.0.1", 1)])
    monkeypatch.setattr(coord, "_is_online", lambda node: True)
    monkeypatch.setattr(
        coord, "_execute_on_node", lambda node, task, item: {"ok": item["x"]}
    )
    result = coord.run(
        "scan",
        [{"x": 1}, {"x": 2}],
        aggregator=lambda rs: {"total": sum(r["ok"] for r in rs)},
    )
    assert result.nodes_completed == 2
    assert result.aggregated_output == {"total": 3}


def test_is_online_false_when_unreachable():
    coord = DistributedSwarmCoordinator()
    assert coord._is_online(SwarmNode("n", "127.0.0.1", 59995)) is False


# --- raw HTTP request parsing edge paths -------------------------------------

class _FakeConn:
    """Minimal socket stand-in: feeds canned bytes, captures sendall output."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self.sent = b""
        self.closed = False

    def recv(self, _n: int) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def close(self) -> None:
        self.closed = True


def test_handle_request_empty_data_returns_early():
    """No bytes at all -> early return, nothing sent, conn closed (lines 204/207)."""
    server = SwarmNodeServer("n", host="127.0.0.1", port=0)
    conn = _FakeConn([b""])
    server._handle_request(conn)
    assert conn.sent == b""
    assert conn.closed is True


def test_handle_request_unknown_path_returns_404():
    """A GET to an unknown path yields a 404 response (line 246)."""
    server = SwarmNodeServer("n", host="127.0.0.1", port=0)
    conn = _FakeConn([b"GET /nope HTTP/1.1\r\n\r\n"])
    server._handle_request(conn)
    assert b"404 Not Found" in conn.sent
    assert b"Not found" in conn.sent
    assert conn.closed is True


def test_handle_request_health_responds_ok():
    server = SwarmNodeServer("hn", host="127.0.0.1", port=0)
    conn = _FakeConn([b"GET /health HTTP/1.1\r\n\r\n"])
    server._handle_request(conn)
    assert b"200 OK" in conn.sent
    body = conn.sent.split(b"\r\n\r\n", 1)[1]
    assert json.loads(body.decode())["node_id"] == "hn"


def test_handle_request_execute_bad_json_returns_error(monkeypatch):
    """A POST /execute with invalid JSON body is caught (lines 241-242)."""
    server = SwarmNodeServer("n", host="127.0.0.1", port=0)
    raw = (
        b"POST /execute HTTP/1.1\r\n"
        b"Content-Length: 3\r\n\r\n"
        b"{ x"
    )
    conn = _FakeConn([raw])
    server._handle_request(conn)
    assert b"200 OK" in conn.sent
    body = conn.sent.split(b"\r\n\r\n", 1)[1]
    assert "error" in json.loads(body.decode())


def test_handle_request_execute_unknown_task():
    server = SwarmNodeServer("n", host="127.0.0.1", port=0)
    payload = json.dumps({"task": "missing", "payload": {}}).encode()
    raw = (
        b"POST /execute HTTP/1.1\r\n"
        + f"Content-Length: {len(payload)}\r\n\r\n".encode()
        + payload
    )
    conn = _FakeConn([raw])
    server._handle_request(conn)
    body = conn.sent.split(b"\r\n\r\n", 1)[1]
    assert "Unknown task" in json.loads(body.decode())["error"]


# --- server lifecycle teardown branches --------------------------------------

def test_actual_port_falls_back_to_configured_when_unbound():
    server = SwarmNodeServer("n", host="127.0.0.1", port=4242)
    assert server.server is None
    assert server.actual_port == 4242


def test_stop_without_start_is_noop():
    """stop() before start() must not raise (server is None, line guard)."""
    server = SwarmNodeServer("n", host="127.0.0.1", port=0)
    server.stop()
    assert server._running is False
    assert server.server is None


def test_stop_swallows_shutdown_oserror(monkeypatch):
    """If shutdown() raises OSError, stop() swallows it and still closes (300-301)."""
    server = SwarmNodeServer("n", host="127.0.0.1", port=0)

    class _Sock:
        def __init__(self) -> None:
            self.closed = False

        def shutdown(self, _how: int) -> None:
            raise OSError("already disconnected")

        def close(self) -> None:
            self.closed = True

    sock = _Sock()
    server.server = sock
    server.stop()
    assert sock.closed is True
    assert server.server is None


def test_register_task_adds_to_registry():
    server = SwarmNodeServer("n", host="127.0.0.1", port=0)
    server.register_task("echo", lambda p: p)
    assert "echo" in server.task_registry


def test_http_response_includes_content_length():
    body = json.dumps({"a": 1})
    resp = SwarmNodeServer._http_response(200, body)
    assert "Content-Length:" in resp
    assert resp.endswith(body)


def test_start_swallows_so_linger_unsupported(monkeypatch):
    """If SO_LINGER setsockopt raises, start() ignores it and still binds (274-275)."""
    import threading

    real_setsockopt = socket.socket.setsockopt

    def fake_setsockopt(self, level, optname, value):
        if optname == socket.SO_LINGER:
            raise OSError("SO_LINGER not supported here")
        return real_setsockopt(self, level, optname, value)

    monkeypatch.setattr(socket.socket, "setsockopt", fake_setsockopt)
    server = SwarmNodeServer("linger", host="127.0.0.1", port=0)
    t = threading.Thread(target=server.start, daemon=True)
    t.start()
    import time

    for _ in range(50):
        if server.server is not None and server.actual_port != 0:
            break
        time.sleep(0.02)
    assert server.actual_port != 0
    server.stop()
    t.join(timeout=3.0)
    assert not t.is_alive()


def test_start_binds_and_loop_exits_on_close():
    """start() in a thread binds the socket; stop() makes the accept loop exit."""
    import threading

    server = SwarmNodeServer("life", host="127.0.0.1", port=0)
    t = threading.Thread(target=server.start, daemon=True)
    t.start()
    # Wait for bind.
    for _ in range(50):
        if server.server is not None and server.actual_port != 0:
            break
        socket.setdefaulttimeout(None)
        import time

        time.sleep(0.02)
    assert server.actual_port != 0
    server.stop()
    t.join(timeout=3.0)
    assert not t.is_alive()
