from __future__ import annotations

import queue
import urllib.request

import pytest

from app.event_stream import EventStream, ApexEventStreamServer, StreamEvent


class TestEventStream:
    def test_publish_and_subscribe(self):
        stream = EventStream()
        sq = stream.subscribe()
        stream.publish(StreamEvent(timestamp=1.0, topic="test", payload={"x": 1}))
        event = sq.get(timeout=1.0)
        assert event.topic == "test"
        assert event.payload["x"] == 1

    def test_unsubscribe(self):
        stream = EventStream()
        sq = stream.subscribe()
        stream.unsubscribe(sq)
        stream.publish(StreamEvent(timestamp=1.0, topic="test", payload={}))
        with pytest.raises(queue.Empty):
            sq.get(timeout=0.1)


class TestApexEventStreamServer:
    def test_start_stop(self):
        server = ApexEventStreamServer(host="127.0.0.1", port=18769)
        server.start()
        req = urllib.request.Request("http://127.0.0.1:18769/", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            assert resp.status == 200
            assert b"Apex Live" in resp.read()
        server.stop()

    def test_emit(self):
        server = ApexEventStreamServer(host="127.0.0.1", port=18770)
        server.start()
        server.emit("security.alert", {"risk": "eval"})
        assert server.stream._queue.qsize() == 1
        server.stop()


def test_publish_handles_full_main_queue():
    import time
    from app.event_stream import EventStream, StreamEvent
    es = EventStream(max_size=2)
    # Fill beyond capacity; publish must not raise on a full main queue.
    for i in range(5):
        es.publish(StreamEvent(timestamp=time.time(), topic="t", payload={"i": i}))
    # Still usable.
    sq = es.subscribe()
    es.publish(StreamEvent(timestamp=time.time(), topic="t", payload={}))
    assert sq.qsize() >= 1


def test_publish_handles_full_subscriber_queue():
    import time
    from app.event_stream import EventStream, StreamEvent
    es = EventStream(max_size=1000)
    sq = es.subscribe()
    # Subscriber queue caps at 100; publishing more must not raise.
    for i in range(150):
        es.publish(StreamEvent(timestamp=time.time(), topic="t", payload={"i": i}))
    assert sq.qsize() <= 100


def test_unsubscribe_unknown_is_safe():
    import queue
    from app.event_stream import EventStream
    es = EventStream()
    es.unsubscribe(queue.Queue())  # not subscribed -> no error
