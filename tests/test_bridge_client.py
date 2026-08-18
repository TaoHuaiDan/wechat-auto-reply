from __future__ import annotations

import json

from wechat_auto_reply.wechat.bridge import HttpWeChatBridge
from wechat_auto_reply.wechat import bridge as bridge_module


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.payload


def test_http_adapter_uses_current_event_lifecycle(monkeypatch):
    responses = [
        {"status": "ok", "listener_alive": True},
        {
            "status": "ok",
            "count": 1,
            "events": [
                {
                    "event_id": "batch/1",
                    "batch_id": "batch/1",
                    "platform": "wechat_desktop",
                    "chat_id": "wechat:Alice",
                    "chat_name": "Alice",
                    "status": "frozen",
                    "messages": [
                        {
                            "message_key": "m1",
                            "chat_name": "Alice",
                            "content": "hello",
                            "message_type": "text",
                        }
                    ],
                }
            ],
        },
        {"status": "ok", "batch_id": "batch/1", "batch_status": "submitted"},
        {"status": "ok", "batch_id": "batch/1", "batch_status": "completed"},
    ]
    calls = []

    def fake_urlopen(req, timeout):
        calls.append((req.method, req.full_url, req.data, timeout))
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr(bridge_module.request, "urlopen", fake_urlopen)
    bridge = HttpWeChatBridge("http://127.0.0.1:8765", request_timeout_seconds=10)

    assert bridge.health()["status"] == "ok"
    events = bridge.get_events(timeout_seconds=30, limit=1)
    assert events[0].event_id == "batch/1"
    assert bridge.acknowledge_event("batch/1").status == "submitted"
    assert bridge.complete_event("batch/1").status == "completed"

    assert calls[0][0] == "GET"
    assert calls[1][0] == "GET"
    assert "timeout=30" in calls[1][1]
    assert "/events/batch%2F1/ack" in calls[2][1]
    assert "/events/batch%2F1/complete" in calls[3][1]
    assert calls[1][3] == 40
