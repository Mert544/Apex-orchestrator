from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable


class MCPHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for MCP JSON-RPC over POST + SSE notifications.

    Minimal, stdlib-only implementation.
    """

    tools: dict[str, Callable[..., Any]] = {}

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default logging to keep output clean
        pass

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_sse(self, event: str, data: dict[str, Any]) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        self.wfile.write(payload.encode("utf-8"))
        self.wfile.flush()

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        try:
            message = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})
            return

        msg_id = message.get("id")
        method = message.get("method", "")

        if method == "initialize":
            self._send_json(200, {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": message.get("params", {}).get("protocolVersion", "2025-06-18"),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "apex-orchestrator-mcp-http", "version": "0.1.0"},
                },
            })
            return

        if method == "tools/list":
            tools = []
            for name, fn in self.tools.items():
                schema = getattr(fn, "input_schema", {"type": "object", "properties": {}})
                tools.append({
                    "name": name,
                    "title": name.replace("_", " ").title(),
                    "description": (fn.__doc__ or "").strip(),
                    "inputSchema": schema,
                })
            self._send_json(200, {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}})
            return

        if method == "tools/call":
            params = message.get("params", {})
            name = params.get("name")
            arguments = params.get("arguments", {})
            if name not in self.tools:
                self._send_json(200, {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32602, "message": f"Tool '{name}' not found"},
                })
                return
            try:
                result = self.tools[name](**arguments)
                text_result = result if isinstance(result, str) else json.dumps(result, indent=2, default=str)
                self._send_json(200, {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": [{"type": "text", "text": text_result}]},
                })
            except Exception as exc:
                self._send_json(200, {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32603, "message": str(exc)},
                })
            return

        self._send_json(200, {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "Method not found"}})

    def do_GET(self) -> None:
        if self.path == "/sse":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            # Keep connection alive with periodic ping
            import time
            try:
                while True:
                    self._send_sse("ping", {"time": time.time()})
                    time.sleep(30)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self._send_json(404, {"error": "Not found"})


class MCPHTTPServer:
    """Run the MCP HTTP+SSE server on a given host/port."""

    def __init__(self, tools: dict[str, Callable[..., Any]], host: str = "127.0.0.1", port: int = 8787) -> None:
        self.host = host
        self.port = port
        MCPHTTPHandler.tools = tools
        self.server = HTTPServer((host, port), MCPHTTPHandler)

    def run(self) -> None:
        print(f"Apex MCP HTTP server listening on http://{self.host}:{self.port}")
        print(f"  POST /   → JSON-RPC endpoint")
        print(f"  GET  /sse → SSE stream")
        self.server.serve_forever()

    def start_in_thread(self) -> threading.Thread:
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        return thread

    def shutdown(self) -> None:
        self.server.shutdown()
