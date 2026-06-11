from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


@dataclass
class StreamEvent:
    timestamp: float
    topic: str
    payload: dict[str, Any]
    node_id: str = "local"


class EventStream:
    """Thread-safe event buffer for SSE streaming."""

    def __init__(self, max_size: int = 1000) -> None:
        self._queue: queue.Queue[StreamEvent] = queue.Queue(maxsize=max_size)
        self._subscribers: list[queue.Queue[StreamEvent]] = []
        self._lock = threading.Lock()

    def publish(self, event: StreamEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            pass
        with self._lock:
            for sq in self._subscribers:
                try:
                    sq.put_nowait(event)
                except queue.Full:
                    pass

    def subscribe(self) -> queue.Queue[StreamEvent]:
        sq: queue.Queue[StreamEvent] = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(sq)
        return sq

    def unsubscribe(self, sq: queue.Queue[StreamEvent]) -> None:
        with self._lock:
            if sq in self._subscribers:
                self._subscribers.remove(sq)


class _SseHandler(BaseHTTPRequestHandler):
    stream: EventStream

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/events":
            self._serve_sse()
        elif self.path == "/":
            self._serve_html()
        else:
            self.send_error(404)

    def _serve_sse(self):
        # Subscribe BEFORE sending headers: a client treats the completed
        # response start as "connected", so an event emitted right after must
        # already have a queue to land in. Subscribing afterwards left a gap
        # in which events were silently dropped (a real race that surfaced as
        # a flaky test under full-suite load).
        sq = self.stream.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            while True:
                event = sq.get(timeout=1.0)
                data = json.dumps({
                    "ts": event.timestamp,
                    "topic": event.topic,
                    "payload": event.payload,
                    "node": event.node_id,
                })
                self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
        except queue.Empty:
            pass
        finally:
            self.stream.unsubscribe(sq)

    def _serve_html(self):
        html = b"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>Apex Live Stream</title>
<style>
body{font-family:system-ui,sans-serif;margin:2rem;background:#0f0f23;color:#0f0;}
#log{white-space:pre-wrap;font-family:monospace;font-size:0.9rem;max-height:80vh;overflow-y:auto;}
.event{margin:0.2rem 0;padding:0.3rem;border-left:3px solid #0f0;}
.topic{font-weight:bold;color:#0ff;}
</style></head>
<body>
<h2>Apex Live Event Stream</h2>
<div id="log"></div>
<script>
const es=new EventSource('/events');
const log=document.getElementById('log');
es.onmessage=e=>{
  const d=JSON.parse(e.data);
  const div=document.createElement('div');div.className='event';
  div.innerHTML='<span class="topic">'+d.topic+'</span> <span style="color:#888">'+new Date(d.ts*1000).toLocaleTimeString()+'</span> '+JSON.stringify(d.payload);
  log.appendChild(div);log.scrollTop=log.scrollHeight;
};
</script></body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html)


class ApexEventStreamServer:
    """Lightweight SSE server for real-time Apex agent events."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8767) -> None:
        self.host = host
        self.port = port
        self.stream = EventStream()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        handler = type("Handler", (_SseHandler,), {"stream": self.stream})
        self._server = HTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None

    def emit(self, topic: str, payload: dict[str, Any], node_id: str = "local") -> None:
        self.stream.publish(StreamEvent(
            timestamp=time.time(),
            topic=topic,
            payload=payload,
            node_id=node_id,
        ))
