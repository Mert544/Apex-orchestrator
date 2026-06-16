"""Shared JSON-response writer for the stdlib plugin HTTP servers.

Both the plugin marketplace server and the registry server reply to requests by
serializing a dict to indented JSON, setting the same status / content-type /
CORS / content-length headers, and writing the body. That handful of statements
was duplicated verbatim in each handler's ``_send_json``; hoisting it here keeps
one source of truth. The bytes written and headers sent are identical to the
originals. Deterministic, stdlib-only.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from typing import Any


def send_json_response(
    handler: BaseHTTPRequestHandler, status: int, data: dict[str, Any]
) -> None:
    """Write ``data`` as an indented JSON response on ``handler``."""
    body = json.dumps(data, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
