from __future__ import annotations

import pytest

from wechat_auto_reply.storage import Database, Repository
from wechat_auto_reply.storage.repository import EventValidationError


def test_ingest_is_idempotent_and_keeps_conversations_separate(tmp_path, event_factory):
    repository = Repository(Database(tmp_path / "app.sqlite3"))
    alice_event = event_factory(event_id="batch-alice", chat_name="Alice", message_key="alice-1")
    bob_event = event_factory(event_id="batch-bob", chat_name="Bob", message_key="bob-1")

    first = repository.ingest_event(alice_event, now=100.0)
    second = repository.ingest_event(alice_event, now=101.0)
    bob = repository.ingest_event(bob_event, now=102.0)

    assert first.inserted_messages == 1
    assert first.duplicate_messages == 0
    assert second.inserted_messages == 0
    assert second.duplicate_messages == 1
    assert bob.inserted_messages == 1

    alice = repository.get_conversation("wechat:Alice")
    bob_conversation = repository.get_conversation("wechat:Bob")
    assert alice is not None and bob_conversation is not None
    assert alice.id != bob_conversation.id
    assert [message.content for message in repository.list_messages(alice.id)] == ["你好"]
    assert [message.content for message in repository.list_messages(bob_conversation.id)] == ["你好"]


def test_event_cannot_contain_another_conversation_message(tmp_path, event_factory):
    repository = Repository(Database(tmp_path / "app.sqlite3"))
    event = event_factory(event_id="batch-mixed", chat_name="Alice")
    mixed_payload = dict(event.raw)
    mixed_payload["messages"] = [
        {
            "message_key": "bob-message",
            "chat_name": "Bob",
            "message_type": "text",
            "content": "不应混入 Alice",
        }
    ]

    from wechat_auto_reply.wechat.models import BridgeEvent

    with pytest.raises(EventValidationError):
        repository.ingest_event(BridgeEvent.from_payload(mixed_payload))

    assert repository.get_conversation("wechat:Alice") is None
    assert repository.get_conversation("wechat:Bob") is None


def test_acknowledged_event_can_be_resumed_after_restart(tmp_path, event_factory):
    db_path = tmp_path / "app.sqlite3"
    event = event_factory(event_id="batch-restart")
    first_repository = Repository(Database(db_path))
    first_repository.ensure_event_received(event, now=100.0)
    first_repository.mark_event_acknowledged(event.event_id, now=101.0)

    second_repository = Repository(Database(db_path))
    state = second_repository.get_event(event.event_id)
    assert state is not None
    assert state.local_status == "acknowledged"

    result = second_repository.ingest_event(event, now=102.0)
    assert result.inserted_messages == 1
    assert second_repository.get_event(event.event_id).local_status == "stored"
