from __future__ import annotations

import threading
import time

import pytest

from app.agents.bus import AgentBus
from app.agents.collaboration import ApexCollaborationProtocol


class TestApexCollaborationProtocol:
    def test_stats_initial(self):
        bus = AgentBus()
        proto = ApexCollaborationProtocol("node-1", bus=bus)
        stats = proto.stats()
        assert stats["node_id"] == "node-1"
        assert stats["running"] is False
        assert stats["peers"] == []

    def test_start_stop(self):
        bus = AgentBus()
        proto = ApexCollaborationProtocol("node-1", bus=bus)
        proto.start()
        assert proto.stats()["running"] is True
        proto.stop()
        assert proto.stats()["running"] is False

    def test_handle_remote_event(self):
        bus = AgentBus()
        received = []
        bus.subscribe("test-node", "remote.topic", lambda msg: received.append(msg))
        proto = ApexCollaborationProtocol("node-1", bus=bus)
        proto._handle_remote_event({"topic": "remote.topic", "payload": {"x": 1}})
        assert len(received) == 1
        assert received[0].payload["x"] == 1

    def test_peers_discard_on_send_failure(self):
        proto = ApexCollaborationProtocol("node-1")
        proto.peers.add("non-existent-host-xyz")
        proto._send_event("non-existent-host-xyz", {"topic": "t"})
        assert "non-existent-host-xyz" not in proto.peers
