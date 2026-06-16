from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from app.plugins._http_json import send_json_response


class PluginMarketplaceHandler(BaseHTTPRequestHandler):
    """HTTP handler for the Plugin Marketplace Server.

    Endpoints:
      GET  /plugins              — list all plugins
      GET  /plugins/<name>       — get plugin metadata
      POST /plugins              — publish a new plugin
      GET  /download/<name>.py   — download plugin source
    """

    def log_message(self, format: str, *args: Any) -> None:
        pass

    @property
    def _plugin_dir(self) -> Path:
        return getattr(self.server, "plugin_dir", Path("plugins"))

    @property
    def _index_file(self) -> Path:
        return getattr(self.server, "index_file", Path("plugins") / "index.json")

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        send_json_response(self, status, data)

    def _load_index(self) -> dict[str, Any]:
        if self._index_file.exists():
            try:
                return json.loads(self._index_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"plugins": {}}

    def _save_index(self, data: dict[str, Any]) -> None:
        self._index_file.parent.mkdir(parents=True, exist_ok=True)
        self._index_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def do_GET(self) -> None:
        path = self.path

        if path == "/plugins":
            index = self._load_index()
            plugins = [
                {"name": name, **meta}
                for name, meta in index.get("plugins", {}).items()
            ]
            self._send_json(200, {"plugins": plugins})
            return

        if path.startswith("/plugins/"):
            name = path.split("/")[-1]
            index = self._load_index()
            meta = index.get("plugins", {}).get(name)
            if meta:
                self._send_json(200, {"name": name, **meta})
                return
            self._send_json(404, {"error": "Plugin not found"})
            return

        if path.startswith("/download/"):
            filename = path.split("/")[-1]
            plugin_file = self._plugin_dir / filename
            if plugin_file.exists():
                content = plugin_file.read_text(encoding="utf-8")
                body = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send_json(404, {"error": "File not found"})
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path == "/plugins":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON"})
                return

            name = data.get("name")
            if not name:
                self._send_json(400, {"error": "Plugin name required"})
                return

            index = self._load_index()
            index.setdefault("plugins", {})[name] = {
                "version": data.get("version", "0.0.1"),
                "description": data.get("description", ""),
                "author": data.get("author", ""),
                "tags": data.get("tags", []),
                "download_url": f"/download/{name}.py",
            }
            self._save_index(index)

            if "content" in data:
                plugin_file = self._plugin_dir / f"{name}.py"
                plugin_file.parent.mkdir(parents=True, exist_ok=True)
                plugin_file.write_text(data["content"], encoding="utf-8")

            self._send_json(201, {"status": "published", "name": name})
            return

        self._send_json(404, {"error": "Not found"})


class PluginMarketplaceServer:
    """Plugin Marketplace HTTP server.

    Usage:
        server = PluginMarketplaceServer(port=8765)
        server.start()
        # ...
        server.stop()
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8765, plugin_dir: str | Path = "plugins") -> None:
        self.host = host
        self.port = port
        self.plugin_dir = Path(plugin_dir).resolve()
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.plugin_dir / "index.json"
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._server = HTTPServer((self.host, self.port), PluginMarketplaceHandler)
        self._server.plugin_dir = self.plugin_dir
        self._server.index_file = self.index_file
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"Plugin Marketplace Server running on http://{self.host}:{self.port}")

    def stop(self) -> None:
        if not (self._server):
            return
        self._server.shutdown()
        self._server = None

    def __enter__(self) -> PluginMarketplaceServer:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
