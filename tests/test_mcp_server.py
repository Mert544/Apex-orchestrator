from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

import pytest

from app.mcp.server import MCPServer
from app.mcp.tools import build_apex_tools


def _make_message(body: dict) -> bytes:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(payload)}\r\n\r\n".encode("utf-8")
    return header + payload


def _run_server_with_input(raw_input: bytes, tools: dict | None = None) -> bytes:
    tools = tools or {"echo": lambda msg="hello": msg}
    server = MCPServer(tools)

    old_stdin = sys.stdin
    old_stdout = sys.stdout
    try:
        sys.stdin = BytesIO(raw_input)  # type: ignore[assignment]
        sys.stdout = BytesIO()  # type: ignore[assignment]
        # Monkey-patch buffer attributes
        sys.stdin.buffer = sys.stdin  # type: ignore[attr-defined]
        sys.stdout.buffer = sys.stdout  # type: ignore[attr-defined]
        server.run()
        sys.stdout.seek(0)
        return sys.stdout.read()  # type: ignore[return-value]
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout


def _parse_messages(raw: bytes) -> list[dict]:
    messages = []
    offset = 0
    while offset < len(raw):
        header_end = raw.find(b"\r\n\r\n", offset)
        if header_end == -1:
            break
        header = raw[offset:header_end].decode("utf-8")
        length = 0
        for line in header.split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        body_start = header_end + 4
        body = raw[body_start:body_start + length]
        messages.append(json.loads(body.decode("utf-8")))
        offset = body_start + length
    return messages


def test_initialize_handshake():
    init_request = _make_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        },
    })
    init_notification = _make_message({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    })
    tools_request = _make_message({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
    })

    raw_input = init_request + init_notification + tools_request
    output = _run_server_with_input(raw_input)
    messages = _parse_messages(output)

    assert len(messages) == 2
    assert messages[0]["id"] == 1
    assert messages[0]["result"]["serverInfo"]["name"] == "apex-orchestrator-mcp"
    assert messages[0]["result"]["capabilities"]["tools"]["listChanged"] is False
    assert messages[1]["id"] == 2
    assert "tools" in messages[1]["result"]


def test_tools_call():
    def _sample_tool(name: str = "world") -> str:
        return f"Hello, {name}!"

    _sample_tool.input_schema = {"type": "object", "properties": {}}  # type: ignore[attr-defined]

    init_request = _make_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        },
    })
    init_notification = _make_message({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    })
    call_request = _make_message({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "_sample_tool", "arguments": {"name": "Apex"}},
    })

    raw_input = init_request + init_notification + call_request
    output = _run_server_with_input(raw_input, tools={"_sample_tool": _sample_tool})
    messages = _parse_messages(output)

    assert len(messages) == 2
    call_response = messages[1]
    assert call_response["id"] == 3
    content = call_response["result"]["content"][0]
    assert content["type"] == "text"
    assert "Hello, Apex!" in content["text"]


def test_tool_not_found():
    init_request = _make_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test"}},
    })
    init_notification = _make_message({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    })
    call_request = _make_message({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "missing_tool", "arguments": {}},
    })

    raw_input = init_request + init_notification + call_request
    output = _run_server_with_input(raw_input)
    messages = _parse_messages(output)

    assert messages[1]["error"]["code"] == -32602
    assert "missing_tool" in messages[1]["error"]["message"]


def test_method_not_found():
    init_request = _make_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test"}},
    })
    init_notification = _make_message({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    })
    unknown_request = _make_message({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "unknown/method",
    })

    raw_input = init_request + init_notification + unknown_request
    output = _run_server_with_input(raw_input)
    messages = _parse_messages(output)

    assert messages[1]["error"]["code"] == -32601


def test_apex_tools_discovery():
    tools = build_apex_tools()
    assert "apex_project_profile" in tools
    assert "apex_generate_patch" in tools
    assert "apex_apply_patch" in tools
    assert "apex_run_tests" in tools
    for name, fn in tools.items():
        assert hasattr(fn, "input_schema")
        assert isinstance(fn.input_schema, dict)


def test_apex_tool_profile(tmp_path: Path):
    # Create a tiny project
    main_py = tmp_path / "app" / "main.py"
    main_py.parent.mkdir(parents=True, exist_ok=True)
    main_py.write_text("def main(): pass\n", encoding="utf-8")
    tools = build_apex_tools()
    result = tools["apex_project_profile"](project_root=str(tmp_path))
    data = json.loads(result)
    assert data["total_files"] >= 1


def test_apex_tool_generate_and_apply_patch(tmp_path: Path):
    math_py = tmp_path / "app" / "math.py"
    math_py.parent.mkdir(parents=True, exist_ok=True)
    math_py.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    tools = build_apex_tools()

    patch_result = tools["apex_generate_patch"](
        project_root=str(tmp_path),
        target_files=["app/math.py"],
        title="Add docstrings",
        change_strategy=["add docstrings"],
    )
    patch_data = json.loads(patch_result)
    assert patch_data["transform_type"] == "add_docstring"
    pr = patch_data["patch_requests"][0]

    apply_result = tools["apex_apply_patch"](
        project_root=str(tmp_path),
        patch_requests=[pr],
    )
    apply_data = json.loads(apply_result)
    assert apply_data["ok"] is True
    assert "app/math.py" in apply_data["changed_files"]
    assert '"""Add docstrings."""' in (tmp_path / "app" / "math.py").read_text(encoding="utf-8")
