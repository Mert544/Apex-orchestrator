from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

from app.agents.bus import AgentBus
from app.agents.collaboration import ApexCollaborationProtocol
from app.agents.skills.self_audit_agent import SelfAuditAgent


# ---------------------------------------------------------------------------
# ApexCollaborationProtocol
# ---------------------------------------------------------------------------


class TestCollaborationSendAndBroadcast:
    def test_send_event_success_delivers_payload(self):
        # A real local TCP server stands in for a peer node.
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        server.listen(1)

        received: list[dict] = []

        def _accept():
            conn, _ = server.accept()
            data = conn.recv(4096)
            received.append(json.loads(data.decode("utf-8")))
            conn.close()

        t = threading.Thread(target=_accept)
        t.start()

        proto = ApexCollaborationProtocol("node-1")
        # Point the protocol's event port at our ephemeral server port.
        proto.EVENT_PORT = port
        proto._send_event("127.0.0.1", {"topic": "t", "payload": {"v": 9}})

        t.join(timeout=2.0)
        server.close()
        assert received == [{"topic": "t", "payload": {"v": 9}}]
        # Successful send must not discard the peer.
        assert "127.0.0.1" not in proto.peers  # never added in the first place

    def test_broadcast_to_peers_iterates_known_peers(self):
        proto = ApexCollaborationProtocol("node-1")
        sent: list[tuple[str, dict]] = []
        proto._send_event = lambda pid, ev: sent.append((pid, ev))  # type: ignore[method-assign]
        proto.peers.update({"peer-a", "peer-b"})
        proto.broadcast_to_peers({"topic": "x"})
        assert sorted(p for p, _ in sent) == ["peer-a", "peer-b"]
        assert all(ev == {"topic": "x"} for _, ev in sent)

    def test_broadcast_to_peers_no_peers_is_noop(self):
        proto = ApexCollaborationProtocol("node-1")
        called = []
        proto._send_event = lambda pid, ev: called.append(pid)  # type: ignore[method-assign]
        proto.broadcast_to_peers({"topic": "x"})
        assert called == []


class TestCollaborationWireBus:
    def test_wire_bus_forwards_published_messages_to_peers(self):
        bus = AgentBus()
        proto = ApexCollaborationProtocol("node-1", bus=bus)
        forwarded: list[dict] = []
        proto.broadcast_to_peers = lambda ev: forwarded.append(ev)  # type: ignore[method-assign]
        proto._wire_bus()

        bus.broadcast("sender-x", "topic.y", {"k": "v"})

        assert len(forwarded) == 1
        ev = forwarded[0]
        assert ev["sender"] == "sender-x"
        assert ev["topic"] == "topic.y"
        assert ev["payload"] == {"k": "v"}
        assert ev["recipient"] is None

    def test_wire_bus_still_delivers_to_local_subscribers(self):
        bus = AgentBus()
        proto = ApexCollaborationProtocol("node-1", bus=bus)
        proto.broadcast_to_peers = lambda ev: None  # type: ignore[method-assign]
        proto._wire_bus()

        received = []
        bus.subscribe("local", "topic.z", lambda msg: received.append(msg))
        bus.broadcast("s", "topic.z", {"a": 1})
        assert len(received) == 1
        assert received[0].payload == {"a": 1}

    def test_start_with_bus_wires_forwarding(self):
        bus = AgentBus()
        proto = ApexCollaborationProtocol("node-2", bus=bus)
        forwarded: list[dict] = []
        proto.broadcast_to_peers = lambda ev: forwarded.append(ev)  # type: ignore[method-assign]
        try:
            proto.start()
            bus.broadcast("s", "t", {"p": 1})
        finally:
            proto.stop()
        assert len(forwarded) == 1
        assert forwarded[0]["topic"] == "t"


class TestCollaborationListenerLoops:
    def test_discovery_listener_adds_remote_peer(self, monkeypatch):
        proto = ApexCollaborationProtocol("node-1")

        class FakeSock:
            def __init__(self):
                self._sent = False

            def setsockopt(self, *a):
                pass

            def bind(self, *a):
                pass

            def settimeout(self, *a):
                pass

            def recvfrom(self, n):
                # First call: deliver a beacon from another node, then stop loop.
                if not self._sent:
                    self._sent = True
                    return (json.dumps({"node_id": "node-2"}).encode(), ("10.0.0.5", 1))
                proto._running = False
                raise socket.timeout()

        monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())
        monkeypatch.setattr(socket, "inet_aton", lambda s: b"\x00\x00\x00\x00")
        proto._running = True
        proto._start_discovery_listener()
        for t in proto._threads:
            t.join(timeout=2.0)
        assert "node-2" in proto.peers

    def test_discovery_listener_ignores_own_beacon(self, monkeypatch):
        proto = ApexCollaborationProtocol("node-1")

        class FakeSock:
            def __init__(self):
                self._sent = False

            def setsockopt(self, *a):
                pass

            def bind(self, *a):
                pass

            def settimeout(self, *a):
                pass

            def recvfrom(self, n):
                if not self._sent:
                    self._sent = True
                    return (json.dumps({"node_id": "node-1"}).encode(), ("10.0.0.5", 1))
                proto._running = False
                raise Exception("boom")  # exercises the break branch

        monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())
        monkeypatch.setattr(socket, "inet_aton", lambda s: b"\x00\x00\x00\x00")
        proto._running = True
        proto._start_discovery_listener()
        for t in proto._threads:
            t.join(timeout=2.0)
        assert proto.peers == set()

    def test_discovery_beacon_sends_then_stops(self, monkeypatch):
        proto = ApexCollaborationProtocol("node-1")
        sent: list[tuple] = []

        class FakeSock:
            def setsockopt(self, *a):
                pass

            def sendto(self, data, addr):
                sent.append((data, addr))
                proto._running = False

        monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())
        # time.sleep is never reached because _running flips to False first,
        # but patch it anyway to keep the test fast and deterministic.
        monkeypatch.setattr("app.agents.collaboration.time.sleep", lambda *a: None)
        proto._running = True
        proto._start_discovery_beacon()
        for t in proto._threads:
            t.join(timeout=2.0)
        assert len(sent) == 1
        payload = json.loads(sent[0][0].decode())
        assert payload["node_id"] == "node-1"

    def test_discovery_beacon_swallows_send_errors(self, monkeypatch):
        proto = ApexCollaborationProtocol("node-1")
        calls = {"n": 0}

        class FakeSock:
            def setsockopt(self, *a):
                pass

            def sendto(self, data, addr):
                calls["n"] += 1
                proto._running = False
                raise OSError("network down")

        monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())
        monkeypatch.setattr("app.agents.collaboration.time.sleep", lambda *a: None)
        proto._running = True
        proto._start_discovery_beacon()
        for t in proto._threads:
            t.join(timeout=2.0)
        assert calls["n"] == 1  # error was swallowed, no crash

    def test_event_listener_handles_remote_event(self, monkeypatch):
        bus = AgentBus()
        received = []
        bus.subscribe("listener", "remote.topic", lambda msg: received.append(msg))
        proto = ApexCollaborationProtocol("node-1", bus=bus)

        class FakeConn:
            def recv(self, n):
                return json.dumps({"topic": "remote.topic", "payload": {"q": 7}}).encode()

            def close(self):
                pass

        class FakeSock:
            def __init__(self):
                self._sent = False

            def setsockopt(self, *a):
                pass

            def bind(self, *a):
                pass

            def listen(self, *a):
                pass

            def settimeout(self, *a):
                pass

            def accept(self):
                if not self._sent:
                    self._sent = True
                    return (FakeConn(), ("10.0.0.7", 5))
                proto._running = False
                raise socket.timeout()

        monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())
        proto._running = True
        proto._start_event_listener()
        for t in proto._threads:
            t.join(timeout=2.0)
        assert len(received) == 1
        assert received[0].payload == {"q": 7}

    def test_event_listener_breaks_on_unexpected_error(self, monkeypatch):
        proto = ApexCollaborationProtocol("node-1")

        class FakeSock:
            def setsockopt(self, *a):
                pass

            def bind(self, *a):
                pass

            def listen(self, *a):
                pass

            def settimeout(self, *a):
                pass

            def accept(self):
                raise OSError("socket closed")

        monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())
        proto._running = True
        proto._start_event_listener()
        for t in proto._threads:
            t.join(timeout=2.0)
        # Loop broke without raising; nothing to assert beyond clean exit.
        assert proto._event_sock is not None

    def test_handle_remote_event_without_bus_is_noop(self):
        proto = ApexCollaborationProtocol("node-1")
        # No bus configured -> must not raise.
        proto._handle_remote_event({"topic": "t", "payload": {}})

    def test_handle_remote_event_without_topic_is_noop(self):
        bus = AgentBus()
        received = []
        bus.subscribe("x", "anything", lambda m: received.append(m))
        proto = ApexCollaborationProtocol("node-1", bus=bus)
        proto._handle_remote_event({"payload": {"a": 1}})
        assert received == []


# ---------------------------------------------------------------------------
# SelfAuditAgent
# ---------------------------------------------------------------------------


class TestSelfAuditRisks:
    def test_detects_exec_os_system_and_pickle_loads(self, tmp_path: Path):
        agent = SelfAuditAgent()
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "risky.py").write_text(
            "import os\n"
            "import pickle\n"
            "def f(code, data):\n"
            "    exec(code)\n"
            "    os.system('ls')\n"
            "    return pickle.loads(data)\n"
        )
        result = agent.run(project_root=str(tmp_path))
        risks = {r["risk"] for r in result["findings"]}
        assert "exec()" in risks
        assert "os.system()" in risks
        assert "pickle.loads()" in risks
        sev = {r["risk"]: r["severity"] for r in result["findings"]}
        assert sev["exec()"] == "critical"
        assert sev["os.system()"] == "high"
        assert sev["pickle.loads()"] == "high"

    def test_detects_bare_except(self, tmp_path: Path):
        agent = SelfAuditAgent()
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "bare.py").write_text(
            "def f():\n    try:\n        pass\n    except:\n        pass\n"
        )
        result = agent.run(project_root=str(tmp_path))
        assert any(r["risk"] == "bare except" and r["severity"] == "medium"
                   for r in result["findings"])

    def test_syntax_error_files_are_skipped(self, tmp_path: Path):
        agent = SelfAuditAgent()
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "broken.py").write_text("def (: this is not python\n")
        result = agent.run(project_root=str(tmp_path))
        # Broken file is skipped by every analyzer, no crash, no findings.
        assert result["findings"] == []
        assert result["missing_docstrings_count"] == 0
        assert result["long_functions_count"] == 0


class TestSelfAuditCoverageGap:
    def test_import_app_style_marks_module_tested(self, tmp_path: Path):
        agent = SelfAuditAgent()
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "module_a.py").write_text("def a(): pass\n")
        (tmp_path / "app" / "module_b.py").write_text("def b(): pass\n")
        (tmp_path / "tests").mkdir()
        # Use the `import app.x` form to hit the second coverage-gap branch.
        (tmp_path / "tests" / "test_a.py").write_text("import app.module_a\n")
        result = agent.run(project_root=str(tmp_path))
        cov = result["coverage_gap"]
        assert "module_a" in cov["tested_modules"]
        assert "module_b" in cov["untested_modules"]
        assert cov["total_test_files"] == 1

    def test_find_python_files_skips_pycache_and_venv(self, tmp_path: Path):
        agent = SelfAuditAgent()
        app_dir = tmp_path / "app"
        (app_dir / "__pycache__").mkdir(parents=True)
        (app_dir / ".venv").mkdir()
        (app_dir / "__pycache__" / "cached.py").write_text("x = 1\n")
        (app_dir / ".venv" / "libmod.py").write_text("y = 2\n")
        (app_dir / "real.py").write_text("z = 3\n")
        files = agent._find_python_files(app_dir)
        names = {f.name for f in files}
        assert names == {"real.py"}
