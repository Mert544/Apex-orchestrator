from __future__ import annotations

import json
import sys
from typing import Any, Callable


class MCPServer:
    """Minimal stdio MCP server using JSON-RPC 2.0 with Content-Length framing.

    No external dependencies required. Works with stdlib only.
    """

    def __init__(self, tools: dict[str, Callable[..., Any]]):
        self.tools = tools
        self.initialized = False

    def run(self) -> None:
        """Read messages from stdin and write responses to stdout until EOF."""
        while True:
            message = self._read_message()
            if message is None:
                break
            response = self._handle_message(message)
            if response is not None:
                self._write_message(response)

    def _read_message(self) -> dict[str, Any] | None:
        """Parse a single JSON-RPC message from stdin with Content-Length framing."""
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = sys.stdin.buffer.read(1)
            if not chunk:
                return None
            header += chunk

        # Parse Content-Length
        content_length = 0
        for line in header.decode("utf-8", errors="replace").split("\r\n"):
            if line.lower().startswith("content-length:"):
                try:
                    content_length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass

        if content_length <= 0:
            return None

        body = sys.stdin.buffer.read(content_length)
        if len(body) < content_length:
            return None

        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def _write_message(self, message: dict[str, Any]) -> None:
        """Serialize a JSON-RPC message to stdout with Content-Length framing."""
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        sys.stdout.buffer.write(header + body)
        sys.stdout.buffer.flush()

    def _handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        msg_id = message.get("id")

        if method == "initialize":
            return self._handle_initialize(message, msg_id)

        if method == "notifications/initialized":
            self.initialized = True
            return None

        if not self.initialized:
            return self._error(msg_id, -32002, "Server not initialized")

        if method == "tools/list":
            return self._handle_tools_list(msg_id)

        if method == "tools/call":
            return self._handle_tools_call(message, msg_id)

        return self._error(msg_id, -32601, "Method not found")

    def _handle_initialize(self, message: dict[str, Any], msg_id: Any) -> dict[str, Any]:
        params = message.get("params", {})
        client_version = params.get("protocolVersion", "unknown")
        result = {
            "protocolVersion": client_version,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": "apex-orchestrator-mcp",
                "version": "0.1.0",
            },
        }
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _handle_tools_list(self, msg_id: Any) -> dict[str, Any]:
        tools = []
        for name, fn in self.tools.items():
            schema = getattr(fn, "input_schema", {"type": "object", "properties": {}})
            tools.append({
                "name": name,
                "title": name.replace("_", " ").title(),
                "description": (fn.__doc__ or "").strip(),
                "inputSchema": schema,
            })
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}}

    def _handle_tools_call(self, message: dict[str, Any], msg_id: Any) -> dict[str, Any]:
        params = message.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments", {})

        if name not in self.tools:
            return self._error(msg_id, -32602, f"Tool '{name}' not found")

        try:
            result = self.tools[name](**arguments)
            text_result = result if isinstance(result, str) else json.dumps(result, indent=2, default=str)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": text_result}],
                },
            }
        except Exception as exc:
            return self._error(msg_id, -32603, str(exc))

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }


if __name__ == "__main__":
    from app.mcp.tools import build_apex_tools

    tools = build_apex_tools()
    server = MCPServer(tools)
    server.run()
