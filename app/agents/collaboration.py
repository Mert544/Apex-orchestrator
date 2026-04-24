from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any

from app.agents.bus import AgentBus


class ApexCollaborationProtocol:
    """Real-time collaboration between multiple Apex Orchestrator instances.

    - UDP multicast discovery on local network
    - TCP event sync between discovered peers
    - Shared AgentBus events propagate across nodes

    Usage:
        proto = ApexCollaborationProtocol(my_node_id="apex-1", bus=agent_bus)
        proto.start_discovery()
        proto.broadcast_to_peers({"topic": "security.alert", "payload": {...}})
    """

    DISCOVERY_PORT = 29999
    EVENT_PORT = 30000
    MULTICAST_GROUP = "239.255.42.99"

    def __init__(self, node_id: str, bus: AgentBus | None = None) -> None:
        self.node_id = node_id
        self.bus = bus
        self.peers: set[str] = set()  # node_id set
        self._running = False
        self._discovery_sock: socket.socket | None = None
        self._event_sock: socket.socket | None = None
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        self._running = True
        self._start_discovery_listener()
        self._start_event_listener()
        self._start_discovery_beacon()
        if self.bus:
            self._wire_bus()

    def stop(self) -> None:
        self._running = False
        for t in self._threads:
            t.join(timeout=1.0)
        if self._discovery_sock:
            self._discovery_sock.close()
        if self._event_sock:
            self._event_sock.close()

    def _start_discovery_listener(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", self.DISCOVERY_PORT))
        mreq = socket.inet_aton(self.MULTICAST_GROUP) + socket.inet_aton("0.0.0.0")
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self._discovery_sock = sock

        def _listen():
            while self._running:
                try:
                    sock.settimeout(1.0)
                    data, addr = sock.recvfrom(1024)
                    msg = json.loads(data.decode("utf-8"))
                    if msg.get("node_id") != self.node_id:
                        self.peers.add(msg.get("node_id", addr[0]))
                except (socket.timeout, json.JSONDecodeError):
                    continue
                except Exception:
                    break

        t = threading.Thread(target=_listen, daemon=True)
        t.start()
        self._threads.append(t)

    def _start_discovery_beacon(self) -> None:
        def _beacon():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            while self._running:
                try:
                    msg = json.dumps({"node_id": self.node_id, "ts": time.time()})
                    sock.sendto(msg.encode("utf-8"), (self.MULTICAST_GROUP, self.DISCOVERY_PORT))
                except Exception:
                    pass
                time.sleep(5.0)

        t = threading.Thread(target=_beacon, daemon=True)
        t.start()
        self._threads.append(t)

    def _start_event_listener(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self.EVENT_PORT))
        sock.listen(5)
        self._event_sock = sock

        def _listen():
            while self._running:
                try:
                    sock.settimeout(1.0)
                    conn, addr = sock.accept()
                    data = conn.recv(4096)
                    if data:
                        msg = json.loads(data.decode("utf-8"))
                        self._handle_remote_event(msg)
                    conn.close()
                except socket.timeout:
                    continue
                except Exception:
                    break

        t = threading.Thread(target=_listen, daemon=True)
        t.start()
        self._threads.append(t)

    def _handle_remote_event(self, msg: dict[str, Any]) -> None:
        if self.bus and msg.get("topic"):
            from app.agents.base import AgentMessage
            self.bus.publish(
                AgentMessage(
                    sender=msg.get("sender", "remote"),
                    recipient=msg.get("recipient"),
                    topic=msg["topic"],
                    payload=msg.get("payload", {}),
                )
            )

    def _wire_bus(self) -> None:
        """Forward local bus events to remote peers."""
        def _forward(msg: Any) -> None:
            self.broadcast_to_peers({
                "sender": msg.sender,
                "recipient": msg.recipient,
                "topic": msg.topic,
                "payload": msg.payload,
            })
        # Subscribe to all topics (wildcard not supported, so we hook publish)
        original_publish = self.bus.publish
        def _hooked_publish(msg: Any) -> None:
            original_publish(msg)
            _forward(msg)
        self.bus.publish = _hooked_publish  # type: ignore[method-assign]

    def broadcast_to_peers(self, event: dict[str, Any]) -> None:
        for peer_id in list(self.peers):
            self._send_event(peer_id, event)

    def _send_event(self, peer_id: str, event: dict[str, Any]) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect((peer_id, self.EVENT_PORT))
            sock.sendall(json.dumps(event).encode("utf-8"))
            sock.close()
        except Exception:
            self.peers.discard(peer_id)

    def stats(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "peers": list(self.peers),
            "running": self._running,
        }
