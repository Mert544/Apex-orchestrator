from __future__ import annotations

import io
import json

import pytest

import app.registry_server as registry_server
from app.mcp import http_server
from app.mcp.http_server import MCPHTTPHandler
from app.registry_server import RegistryHandler


# ---------------------------------------------------------------------------
# MCPHTTPHandler: drive do_POST / do_GET / do_OPTIONS without a real socket.
# ---------------------------------------------------------------------------


class _MCPHandler(MCPHTTPHandler):
    """Drive MCPHTTPHandler methods without a real socket."""

    def __init__(self, body: bytes = b"", path: str = "/", headers: dict | None = None):
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.path = path
        self.headers = headers if headers is not None else {"Content-Length": str(len(body))}
        self._status = None
        self._headers: dict = {}
        self.requestline = ""
        self.client_address = ("127.0.0.1", 0)
        self.command = ""

    def send_response(self, status, message=None):
        self._status = status

    def send_header(self, k, v):
        self._headers[k] = v

    def end_headers(self):
        pass


def _post(message: dict):
    body = json.dumps(message).encode("utf-8")
    h = _MCPHandler(body=body)
    h.do_POST()
    return h


def _body_dict(h: _MCPHandler) -> dict:
    raw = h.wfile.getvalue().decode("utf-8")
    return json.loads(raw)


def test_post_parse_error_returns_400():
    h = _MCPHandler(body=b"{not json}")
    h.do_POST()
    assert h._status == 400
    data = _body_dict(h)
    assert data["error"]["code"] == -32700
    assert data["id"] is None


def test_post_initialize_uses_default_protocol_version():
    h = _post({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert h._status == 200
    data = _body_dict(h)
    assert data["result"]["protocolVersion"] == "2025-06-18"
    assert data["result"]["serverInfo"]["name"] == "apex-orchestrator-mcp-http"


def test_post_tools_list_includes_schema_and_docstring():
    def my_tool(x="y"):
        """Does a thing."""
        return x

    my_tool.input_schema = {"type": "object", "properties": {"x": {}}}
    MCPHTTPHandler.tools = {"my_tool": my_tool}
    try:
        h = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        data = _body_dict(h)
        tool = data["result"]["tools"][0]
        assert tool["name"] == "my_tool"
        assert tool["title"] == "My Tool"
        assert tool["description"] == "Does a thing."
        assert tool["inputSchema"] == {"type": "object", "properties": {"x": {}}}
    finally:
        MCPHTTPHandler.tools = {}


def test_post_tools_list_default_schema_when_missing():
    def bare():
        return None

    MCPHTTPHandler.tools = {"bare": bare}
    try:
        h = _post({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        data = _body_dict(h)
        tool = data["result"]["tools"][0]
        assert tool["inputSchema"] == {"type": "object", "properties": {}}
        assert tool["description"] == ""
    finally:
        MCPHTTPHandler.tools = {}


def test_post_tools_call_dict_result_is_json_encoded():
    MCPHTTPHandler.tools = {"obj": lambda: {"a": 1}}
    try:
        h = _post({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "obj", "arguments": {}},
        })
        data = _body_dict(h)
        text = data["result"]["content"][0]["text"]
        assert json.loads(text) == {"a": 1}
    finally:
        MCPHTTPHandler.tools = {}


def test_post_tools_call_str_result_passthrough():
    MCPHTTPHandler.tools = {"echo": lambda msg="hi": msg}
    try:
        h = _post({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "plain"}},
        })
        data = _body_dict(h)
        assert data["result"]["content"][0]["text"] == "plain"
    finally:
        MCPHTTPHandler.tools = {}


def test_post_tools_call_not_found():
    MCPHTTPHandler.tools = {}
    h = _post({
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {"name": "ghost", "arguments": {}},
    })
    data = _body_dict(h)
    assert data["error"]["code"] == -32602
    assert "ghost" in data["error"]["message"]


def test_post_tools_call_exception_returns_internal_error():
    def boom():
        raise ValueError("kaboom")

    MCPHTTPHandler.tools = {"boom": boom}
    try:
        h = _post({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "boom", "arguments": {}},
        })
        data = _body_dict(h)
        assert data["error"]["code"] == -32603
        assert data["error"]["message"] == "kaboom"
    finally:
        MCPHTTPHandler.tools = {}


def test_post_unknown_method_returns_method_not_found():
    h = _post({"jsonrpc": "2.0", "id": 8, "method": "nope"})
    data = _body_dict(h)
    assert data["error"]["code"] == -32601


def test_do_options_sets_cors_headers():
    h = _MCPHandler()
    h.do_OPTIONS()
    assert h._status == 200
    assert h._headers["Access-Control-Allow-Origin"] == "*"
    assert "POST" in h._headers["Access-Control-Allow-Methods"]


def test_send_sse_writes_event_payload():
    h = _MCPHandler()
    h._send_sse("ping", {"n": 1})
    out = h.wfile.getvalue().decode("utf-8")
    assert out.startswith("event: ping\n")
    assert 'data: {"n": 1}' in out
    assert out.endswith("\n\n")


def test_do_get_unknown_path_returns_404():
    h = _MCPHandler(path="/other")
    h.do_GET()
    assert h._status == 404
    data = _body_dict(h)
    assert data["error"] == "Not found"


def test_do_get_sse_streams_then_stops_on_broken_pipe(monkeypatch):
    # Make the keep-alive loop terminate deterministically: time.sleep raises
    # a BrokenPipeError, which the handler swallows.
    import time as _time

    def fake_sleep(_seconds):
        raise BrokenPipeError()

    monkeypatch.setattr(_time, "sleep", fake_sleep)
    monkeypatch.setattr(_time, "time", lambda: 1234.0)

    h = _MCPHandler(path="/sse")
    h.do_GET()  # should return without raising
    assert h._status == 200
    assert h._headers["Content-Type"] == "text/event-stream"
    out = h.wfile.getvalue().decode("utf-8")
    assert "event: ping" in out


# ---------------------------------------------------------------------------
# MCPHTTPServer: cover run() / shutdown() without binding a real port.
# ---------------------------------------------------------------------------


class _FakeServer:
    def __init__(self, *_args, **_kwargs):
        self.serve_called = False
        self.shutdown_called = False

    def serve_forever(self):
        self.serve_called = True
        raise KeyboardInterrupt()

    def shutdown(self):
        self.shutdown_called = True


def test_mcp_server_run_invokes_serve_forever(monkeypatch, capsys):
    monkeypatch.setattr(http_server, "HTTPServer", _FakeServer)
    server = http_server.MCPHTTPServer({}, host="127.0.0.1", port=0)
    with pytest.raises(KeyboardInterrupt):
        server.run()
    assert server.server.serve_called is True
    out = capsys.readouterr().out
    assert "listening on" in out


def test_mcp_server_shutdown_delegates(monkeypatch):
    monkeypatch.setattr(http_server, "HTTPServer", _FakeServer)
    server = http_server.MCPHTTPServer({}, host="127.0.0.1", port=0)
    server.shutdown()
    assert server.server.shutdown_called is True


# ---------------------------------------------------------------------------
# RegistryHandler.log_message + main() entrypoint.
# ---------------------------------------------------------------------------


def test_registry_log_message_is_silent(capsys):
    # log_message is a no-op; calling it produces no output.
    RegistryHandler.log_message(object(), "%s", "x")
    assert capsys.readouterr().out == ""


def test_registry_main_runs_until_keyboard_interrupt(monkeypatch, tmp_path, capsys):
    plugin_dir = tmp_path / "myplugins"

    monkeypatch.setattr(registry_server.sys, "argv", [
        "registry_server",
        "--port", "0",
        "--host", "127.0.0.1",
        "--plugin-dir", str(plugin_dir),
    ])

    class _RegFakeServer:
        def __init__(self, *_a, **_k):
            self.shutdown_called = False

        def serve_forever(self):
            raise KeyboardInterrupt()

        def shutdown(self):
            self.shutdown_called = True

    monkeypatch.setattr(registry_server, "HTTPServer", _RegFakeServer)

    rc = registry_server.main()
    assert rc == 0
    # plugin dir is created and bound to the handler
    assert plugin_dir.exists()
    assert RegistryHandler.plugin_dir == plugin_dir.resolve()
    out = capsys.readouterr().out
    assert "Shutting down" in out
