from __future__ import annotations

import time
import shutil
import uuid
from pathlib import Path

import pytest

from wechat_auto_reply.wechat.models import BridgeEvent


@pytest.fixture
def tmp_path():
    """Use a workspace-local temp directory in the restricted test runner."""
    path = Path(__file__).resolve().parents[1] / ".test-run" / "cases" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def event_factory():
    def make(
        *,
        event_id: str = "wechat-batch-1",
        chat_name: str = "Alice",
        chat_id: str | None = None,
        content: str = "你好",
        message_key: str = "message-1",
    ) -> BridgeEvent:
        return BridgeEvent.from_payload(
            {
                "event_id": event_id,
                "batch_id": event_id,
                "platform": "wechat_desktop",
                "chat_id": chat_id or f"wechat:{chat_name}",
                "chat_name": chat_name,
                "status": "frozen",
                "created_at": time.time(),
                "messages": [
                    {
                        "message_key": message_key,
                        "chat_name": chat_name,
                        "sender": chat_name,
                        "is_self": False,
                        "message_type": "text",
                        "content": content,
                        "time_text": "12:00",
                    }
                ],
            }
        )

    return make
