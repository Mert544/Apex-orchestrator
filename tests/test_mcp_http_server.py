from __future__ import annotations

import json
import socket
import time
import urllib.request

import pytest

from app.mcp.http_server import MCPHTTPServer


def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    """Poll-connect until the server socket accepts — bounded retry, no fixed sleep."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def _http_post(url: str, body: dict) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read()


@pytest.fixture(scope="module")
def http_server():
    tools = {"echo": lambda msg="hello": msg}
    setattr(tools["echo"], "input_schema", {"type": "object", "properties": {}})
    server = MCPHTTPServer(tools, host="127.0.0.1", port=18787)
    server.start_in_thread()
    # P4 (docs/rnd/context-fragile-tests.md #3): poll-connect readiness instead of
    # a fixed 0.3s startup sleep. HTTPServer binds+listens in __init__, so the
    # first connect normally succeeds immediately; the retry budget is a
    # hang-guard, never a margin.
    assert _wait_for_port("127.0.0.1", 18787), "MCP HTTP server never became reachable"
    yield server
    server.shutdown()


def test_initialize(http_server):
    result = _http_post("http://127.0.0.1:18787", {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        },
    })
    assert result["id"] == 1
    assert result["result"]["serverInfo"]["name"] == "apex-orchestrator-mcp-http"


def test_tools_list(http_server):
    result = _http_post("http://127.0.0.1:18787", {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
    })
    assert result["id"] == 2
    assert len(result["result"]["tools"]) == 1
    assert result["result"]["tools"][0]["name"] == "echo"


def test_tools_call(http_server):
    result = _http_post("http://127.0.0.1:18787", {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": {"msg": "Apex HTTP"}},
    })
    assert result["id"] == 3
    content = result["result"]["content"][0]
    assert content["type"] == "text"
    assert "Apex HTTP" in content["text"]


def test_tool_not_found(http_server):
    result = _http_post("http://127.0.0.1:18787", {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "missing", "arguments": {}},
    })
    assert "error" in result
    assert result["error"]["code"] == -32602


def test_method_not_found(http_server):
    result = _http_post("http://127.0.0.1:18787", {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "unknown/method",
    })
    assert result["error"]["code"] == -32601


def test_cors_preflight(http_server):
    req = urllib.request.Request(
        "http://127.0.0.1:18787",
        method="OPTIONS",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"
