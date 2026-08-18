from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from wechat_auto_reply.service import AutoReplyService
from wechat_auto_reply.storage import Database, Repository
from wechat_auto_reply.wechat.models import BridgeEvent


@dataclass
class FakeBridge:
    events: list[BridgeEvent] = field(default_factory=list)
    acknowledgements: list[str] = field(default_factory=list)
    completions: list[str] = field(default_factory=list)
    sends: list[tuple[str, str]] = field(default_factory=list)
    fail_complete_once: bool = False

    def health(self):
        return {"status": "ok", "listener_alive": True, "queue_size": 0}

    def get_events(self, *, timeout_seconds: float, limit: int):
        return tuple(self.events[:limit])

    def acknowledge_event(self, event_id: str):
        self.acknowledgements.append(event_id)
        return {"status": "ok"}

    def complete_event(self, event_id: str):
        if self.fail_complete_once:
            self.fail_complete_once = False
            raise RuntimeError("simulated bridge timeout")
        self.completions.append(event_id)
        return {"status": "ok"}

    def send_message(self, chat_name: str, message: str):
        self.sends.append((chat_name, message))
        return {"status": "ok"}


def test_service_ack_saves_completes_and_never_sends(tmp_path, event_factory):
    event = event_factory(event_id="batch-1", chat_name="Alice")
    bridge = FakeBridge(events=[event])
    repository = Repository(Database(tmp_path / "app.sqlite3"))
    service = AutoReplyService(
        bridge=bridge,
        repository=repository,
        poll_timeout_seconds=30,
        poll_limit=1,
    )

    service.process_event(event)
    service.process_event(event)  # simulate bridge redelivery after a poll retry

    state = repository.get_event(event.event_id)
    conversation = repository.get_conversation("wechat:Alice")
    assert state is not None and state.local_status == "completed"
    assert conversation is not None
    assert len(repository.list_messages(conversation.id)) == 1
    assert bridge.acknowledgements == [event.event_id]
    assert bridge.completions == [event.event_id]
    assert bridge.sends == []


def test_service_retries_completion_without_duplicate_storage(tmp_path, event_factory):
    event = event_factory(event_id="batch-retry", chat_name="Alice")
    bridge = FakeBridge(fail_complete_once=True)
    repository = Repository(Database(tmp_path / "app.sqlite3"))
    service = AutoReplyService(bridge=bridge, repository=repository)

    with pytest.raises(RuntimeError, match="simulated bridge timeout"):
        service.process_event(event)
    stored = repository.get_event(event.event_id)
    assert stored is not None and stored.local_status == "stored"

    service.process_event(event)
    conversation = repository.get_conversation("wechat:Alice")
    assert conversation is not None
    assert len(repository.list_messages(conversation.id)) == 1
    assert bridge.acknowledgements == [event.event_id]
    assert bridge.completions == [event.event_id]


def test_normal_ingestion_never_invokes_send(tmp_path, event_factory):
    event = event_factory(event_id="batch-no-send", chat_name="Bob")
    bridge = FakeBridge()
    repository = Repository(Database(tmp_path / "app.sqlite3"))
    service = AutoReplyService(bridge=bridge, repository=repository)

    service.process_event(event)

    assert bridge.sends == []
