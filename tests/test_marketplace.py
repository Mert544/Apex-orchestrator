from __future__ import annotations

import json
import socket
import time
import urllib.request

import pytest

from app.plugins.marketplace_server import PluginMarketplaceServer


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


@pytest.fixture
def marketplace_server(tmp_path):
    plugin_dir = tmp_path / "plugins"
    server = PluginMarketplaceServer(host="127.0.0.1", port=18788, plugin_dir=str(plugin_dir))
    server.start()
    # P4 (docs/rnd/context-fragile-tests.md #3): poll-connect readiness instead of
    # a fixed 0.3s startup sleep. start() binds+listens synchronously, so the
    # first connect normally succeeds immediately; the retry budget is a
    # hang-guard, never a margin.
    assert _wait_for_port("127.0.0.1", 18788), "marketplace server never became reachable"
    yield server
    server.stop()


def _get(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(url: str, data: dict) -> dict:
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_full_marketplace_flow(marketplace_server):
    # 1. List empty
    result = _get("http://127.0.0.1:18788/plugins")
    assert result["plugins"] == []

    # 2. Publish
    _post("http://127.0.0.1:18788/plugins", {
        "name": "audit",
        "version": "1.0.0",
        "description": "Security audit plugin",
        "author": "apex",
        "tags": ["security"],
        "content": "def register(proxy):\n    pass\n",
    })

    # 3. Get metadata
    result = _get("http://127.0.0.1:18788/plugins/audit")
    assert result["name"] == "audit"
    assert result["version"] == "1.0.0"

    # 4. Download
    req = urllib.request.Request("http://127.0.0.1:18788/download/audit.py", method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        content = resp.read().decode("utf-8")
    assert "def register" in content

    # 5. List after publish
    result = _get("http://127.0.0.1:18788/plugins")
    assert len(result["plugins"]) == 1
    assert result["plugins"][0]["name"] == "audit"
