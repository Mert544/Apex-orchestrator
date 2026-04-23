#!/usr/bin/env python3
"""Apex Plugin Registry Server (stdlib-only).

Usage:
    python -m app.registry_server --port 8765 --plugin-dir ./plugins
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse


class RegistryHandler(BaseHTTPRequestHandler):
    plugin_dir: Path = Path("plugins")

    def log_message(self, format, *args):
        # Suppress default logging
        pass

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/plugins":
            plugins = []
            if self.plugin_dir.exists():
                for f in sorted(self.plugin_dir.glob("*.py")):
                    plugins.append({
                        "name": f.stem,
                        "url": f"/plugins/{f.stem}",
                    })
            self._send_json(200, {"plugins": plugins})
            return

        if path.startswith("/plugins/"):
            name = path.split("/")[-1]
            plugin_file = self.plugin_dir / f"{name}.py"
            if plugin_file.exists():
                self._send_json(200, {
                    "name": name,
                    "version": "0.0.1",
                    "description": "",
                    "download_url": f"/download/{name}.py",
                })
                return
            self._send_json(404, {"error": "Plugin not found"})
            return

        if path.startswith("/download/"):
            filename = path.split("/")[-1]
            plugin_file = self.plugin_dir / filename
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--plugin-dir", default="plugins")
    args = parser.parse_args()

    plugin_dir = Path(args.plugin_dir).resolve()
    plugin_dir.mkdir(parents=True, exist_ok=True)
    RegistryHandler.plugin_dir = plugin_dir

    server = HTTPServer((args.host, args.port), RegistryHandler)
    print(f"Apex Registry Server running on http://{args.host}:{args.port}")
    print(f"Serving plugins from: {plugin_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
