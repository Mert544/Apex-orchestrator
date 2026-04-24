from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.bus import AgentBus
from app.plugins.registry import PluginRegistry, PluginEventBridge


def test_plugin_event_bridge_wire(tmp_path: Path):
    # Create a fake plugin that subscribes to an agent event
    plugin_file = tmp_path / "test_plugin.py"
    plugin_file.write_text("""
__plugin_name__ = "test-listener"

def register(proxy):
    def handler(msg):
        pass
    proxy.on_agent_event("security.alert", handler)
""")

    registry = PluginRegistry(plugin_dirs=[str(tmp_path)])
    registry.load(plugin_file)
    bus = AgentBus()
    bridge = PluginEventBridge(registry, bus)
    bridge.wire()

    assert bus.stats()["subscriber_count"] >= 1


def test_plugin_proxy_on_agent_event():
    from app.plugins.registry import _PluginProxy
    proxy = _PluginProxy()
    proxy.on_agent_event("test.topic", lambda msg: None)
    assert len(proxy._agent_subscriptions) == 1
    assert proxy._agent_subscriptions[0][0] == "test.topic"
