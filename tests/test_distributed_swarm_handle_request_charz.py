"""Characterization tests for SwarmNodeServer._handle_request.

These tests pin the exact bytes written to the connection for every request
branch of the refactored handler. They exercise the helper decomposition end
to end: header reading, request-line parsing, Content-Length completion (incl.
chunked recv and lowercase header), the health/execute/404 route table, and the
execute body dispatch (known task, unknown task, raising task, malformed JSON,
missing task key). The handler must always close the connection.
"""
from __future__ import annotations

import pytest

from app.engine.distributed_swarm import SwarmNodeServer


class FakeConn:
    """Feeds a fixed byte stream via recv() in chunks; records sendall()."""

    def __init__(self, stream: bytes, chunk: int = 4096) -> None:
        self.stream = stream
        self.chunk = chunk
        self.pos = 0
        self.sent = b""
        self.closed = False

    def recv(self, n: int) -> bytes:
        end = min(self.pos + min(n, self.chunk), len(self.stream))
        out = self.stream[self.pos:end]
        self.pos = end
        return out

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def close(self) -> None:
        self.closed = True


def _echo(payload: dict) -> dict:
    return {"echo": payload, "ok": True}


def _boom(payload: dict) -> dict:
    raise ValueError("kaboom")


def _server() -> SwarmNodeServer:
    return SwarmNodeServer("node-A", task_registry={"echo": _echo, "boom": _boom})


def _req(method: str, path: str, body: bytes = b"", with_cl: bool = True,
         extra_headers: str = "") -> bytes:
    lines = [f"{method} {path} HTTP/1.1", "Host: x"]
    if extra_headers:
        lines.append(extra_headers)
    if with_cl:
        lines.append(f"Content-Length: {len(body)}")
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")
    return head + body


def _run(stream: bytes, chunk: int = 4096) -> FakeConn:
    conn = FakeConn(stream, chunk)
    _server()._handle_request(conn)
    return conn


def _http(status: int, status_text: str, body: str) -> bytes:
    return (
        f"HTTP/1.1 {status} {status_text}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body.encode('utf-8'))}\r\n"
        f"Access-Control-Allow-Origin: *\r\n"
        f"\r\n"
        f"{body}"
    ).encode("utf-8")


def test_health_branch():
    conn = _run(_req("GET", "/health"))
    assert conn.sent == _http(200, "OK", '{"status": "ok", "node_id": "node-A"}')
    assert conn.closed


def test_execute_known_task():
    conn = _run(_req("POST", "/execute", b'{"task":"echo","payload":{"a":1}}'))
    assert conn.sent == _http(
        200, "OK", '{"node_id": "node-A", "result": {"echo": {"a": 1}, "ok": true}}'
    )
    assert conn.closed


def test_execute_unknown_task():
    conn = _run(_req("POST", "/execute", b'{"task":"nope","payload":{}}'))
    assert conn.sent == _http(200, "OK", '{"error": "Unknown task: nope"}')


def test_execute_missing_task_key_is_unknown():
    conn = _run(_req("POST", "/execute", b'{"payload":{}}'))
    assert conn.sent == _http(200, "OK", '{"error": "Unknown task: "}')


def test_execute_task_raises():
    conn = _run(_req("POST", "/execute", b'{"task":"boom","payload":{}}'))
    assert conn.sent == _http(200, "OK", '{"error": "kaboom"}')


def test_execute_malformed_json():
    conn = _run(_req("POST", "/execute", b'{not json'))
    assert b'HTTP/1.1 200 OK' in conn.sent
    assert b'"error"' in conn.sent


def test_execute_lowercase_content_length():
    body = b'{"task":"echo","payload":{"z":2}}'
    conn = _run(_req("POST", "/execute", body, with_cl=False,
                     extra_headers=f"content-length: {len(body)}"))
    assert conn.sent == _http(
        200, "OK", '{"node_id": "node-A", "result": {"echo": {"z": 2}, "ok": true}}'
    )


def test_execute_no_content_length_uses_present_body():
    conn = _run(_req("POST", "/execute", b'{"task":"echo","payload":{}}', with_cl=False))
    assert conn.sent == _http(
        200, "OK", '{"node_id": "node-A", "result": {"echo": {}, "ok": true}}'
    )


def test_execute_body_chunked_across_recv():
    body = b'{"task":"echo","payload":{"big":"' + b"x" * 9000 + b'"}}'
    conn = _run(_req("POST", "/execute", body), chunk=64)
    assert b'HTTP/1.1 200 OK' in conn.sent
    assert b'"result"' in conn.sent
    assert conn.closed


@pytest.mark.parametrize("method,path", [
    ("GET", "/other"),
    ("POST", "/health"),
    ("GET", "/execute"),
])
def test_not_found_branches(method, path):
    conn = _run(_req(method, path))
    assert conn.sent == _http(404, "Not Found", '{"error": "Not found"}')
    assert conn.closed


def test_empty_stream_returns_without_send_but_closes():
    conn = _run(b"")
    assert conn.sent == b""
    assert conn.closed
