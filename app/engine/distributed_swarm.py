from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable


class CircuitBreaker:
    """Simple circuit breaker for remote node calls."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = self.CLOSED
        self.failures = 0
        self.last_failure_time: float = 0.0

    def call(self, fn: Callable[[], Any]) -> Any:
        if self.state == self.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = self.HALF_OPEN
            else:
                raise CircuitBreakerOpen("Circuit breaker is OPEN")
        try:
            result = fn()
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise exc

    def _on_success(self) -> None:
        self.failures = 0
        self.state = self.CLOSED

    def _on_failure(self) -> None:
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.state = self.OPEN


class CircuitBreakerOpen(Exception):
    pass


@dataclass
class SwarmNode:
    """A remote node in the distributed swarm."""

    node_id: str
    host: str
    port: int
    status: str = "unknown"  # online, busy, offline
    last_heartbeat: float = 0.0

    def url(self, path: str = "") -> str:
        return f"http://{self.host}:{self.port}{path}"


@dataclass
class DistributedSwarmResult:
    """Result from running distributed tasks."""

    aggregated_output: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    nodes_completed: int = 0
    nodes_failed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregated_output": self.aggregated_output,
            "errors": self.errors,
            "nodes_completed": self.nodes_completed,
            "nodes_failed": self.nodes_failed,
        }


class DistributedSwarmCoordinator:
    """Coordinate Apex agents across multiple machines via HTTP.

    Each remote machine runs a lightweight SwarmNodeServer that exposes
    a JSON HTTP endpoint at POST /execute. The coordinator distributes
    work items to available nodes and aggregates results.
    """

    def __init__(self, nodes: list[SwarmNode] | None = None) -> None:
        self.nodes: list[SwarmNode] = nodes or []
        self._timeout_seconds = 60
        self._circuits: dict[str, CircuitBreaker] = {}

    def register_node(self, node: SwarmNode) -> None:
        self.nodes.append(node)

    def _is_online(self, node: SwarmNode) -> bool:
        try:
            req = urllib.request.Request(node.url("/health"), method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _execute_on_node(
        self,
        node: SwarmNode,
        task_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        cb = self._circuits.setdefault(node.node_id, CircuitBreaker())
        try:
            def _call() -> dict[str, Any]:
                body = json.dumps({"task": task_name, "payload": payload}).encode("utf-8")
                req = urllib.request.Request(
                    node.url("/execute"),
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self._timeout_seconds) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            return cb.call(_call)
        except CircuitBreakerOpen:
            return {"error": f"Circuit breaker OPEN for {node.node_id}"}
        except Exception as e:
            return {"error": str(e)}

    def run(
        self,
        task_name: str,
        items: list[dict[str, Any]],
        aggregator: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None,
    ) -> DistributedSwarmResult:
        """Distribute *items* across registered nodes and aggregate results.

        If more items than nodes, items are round-robined. If no nodes are
        online, everything runs locally via *local_runner* fallback.
        """
        result = DistributedSwarmResult()
        online_nodes = [n for n in self.nodes if self._is_online(n)]
        if not online_nodes:
            result.errors.append("No online nodes available")
            return result

        responses: list[dict[str, Any]] = []
        # Round-robin dispatch
        for idx, item in enumerate(items):
            node = online_nodes[idx % len(online_nodes)]
            node.status = "busy"
            resp = self._execute_on_node(node, task_name, item)
            node.status = "online"
            if resp and "error" not in resp:
                responses.append(resp)
                result.nodes_completed += 1
            else:
                result.nodes_failed += 1
                if resp:
                    result.errors.append(f"{node.node_id}: {resp['error']}")

        if aggregator:
            result.aggregated_output = aggregator(responses)
        else:
            result.aggregated_output = {"responses": responses}
        return result


class SwarmNodeServer:
    """Minimal HTTP server that exposes a single /execute endpoint.

    Run this on remote machines so the DistributedSwarmCoordinator can
    dispatch work to them.
    """

    def __init__(
        self,
        node_id: str,
        host: str = "0.0.0.0",
        port: int = 18765,
        task_registry: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
    ) -> None:
        self.node_id = node_id
        self.host = host
        self.port = port
        self.task_registry = task_registry or {}
        self.server: socket.socket | None = None
        self._running = False

    def register_task(self, name: str, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.task_registry[name] = fn

    def _handle_request(self, conn: socket.socket) -> None:
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            if not data:
                return
            header_end = data.find(b"\r\n\r\n")
            headers = data[:header_end].decode("utf-8", errors="ignore")
            body = data[header_end + 4 :]

            # Very simple HTTP parsing
            first_line = headers.split("\r\n")[0]
            method, path, _ = first_line.split(" ")

            if path == "/health" and method == "GET":
                resp_body = json.dumps({"status": "ok", "node_id": self.node_id})
                conn.sendall(self._http_response(200, resp_body).encode("utf-8"))
                return

            if path == "/execute" and method == "POST":
                # Read remaining body if Content-Length present
                content_length = 0
                for line in headers.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        content_length = int(line.split(":")[1].strip())
                        break
                while len(body) < content_length:
                    body += conn.recv(4096)

                try:
                    req = json.loads(body.decode("utf-8"))
                    task_name = req.get("task", "")
                    payload = req.get("payload", {})
                    fn = self.task_registry.get(task_name)
                    if fn:
                        result = fn(payload)
                        resp_body = json.dumps({"node_id": self.node_id, "result": result})
                    else:
                        resp_body = json.dumps({"error": f"Unknown task: {task_name}"})
                except Exception as e:
                    resp_body = json.dumps({"error": str(e)})
                conn.sendall(self._http_response(200, resp_body).encode("utf-8"))
                return

            conn.sendall(self._http_response(404, json.dumps({"error": "Not found"})).encode("utf-8"))
        finally:
            conn.close()

    @staticmethod
    def _http_response(status: int, body: str) -> str:
        status_text = {200: "OK", 404: "Not Found", 500: "Internal Server Error"}.get(status, "Unknown")
        return (
            f"HTTP/1.1 {status} {status_text}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body.encode('utf-8'))}\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"\r\n"
            f"{body}"
        )

    def start(self) -> None:
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.host, self.port))
        self.server.listen(5)
        self._running = True
        print(f"SwarmNodeServer {self.node_id} listening on {self.host}:{self.port}")

        while self._running:
            try:
                self.server.settimeout(1.0)
                conn, _ = self.server.accept()
                threading.Thread(target=self._handle_request, args=(conn,), daemon=True).start()
            except socket.timeout:
                continue
            except Exception:
                break

    def stop(self) -> None:
        self._running = False
        if self.server:
            self.server.close()
