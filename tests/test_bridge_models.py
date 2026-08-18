from __future__ import annotations

import pytest

from wechat_auto_reply.wechat.models import BridgeEvent, BridgeProtocolError


def test_current_hermes_event_shape_is_parsed():
    event = BridgeEvent.from_payload(
        {
            "event_id": "wechat-batch-1",
            "batch_id": "wechat-batch-1",
            "platform": "wechat_desktop",
            "chat_id": "wechat:Alice",
            "chat_name": "Alice",
            "status": "submitted",
            "created_at": 1.0,
            "frozen_at": 2.0,
            "submitted_at": 3.0,
            "messages": [
                {
                    "message_key": "m1",
                    "chat_name": "Alice",
                    "sender": "Alice",
                    "is_self": False,
                    "message_type": "text",
                    "content": "hello",
                    "time_text": "09:00",
                    "raw": {"source": "test"},
                }
            ],
        }
    )
    assert event.event_id == "wechat-batch-1"
    assert event.chat_id == "wechat:Alice"
    assert event.status == "submitted"
    assert event.messages[0].external_message_key == "m1"
    assert event.messages[0].content == "hello"


def test_event_without_identity_is_rejected():
    with pytest.raises(BridgeProtocolError):
        BridgeEvent.from_payload({"messages": []})
