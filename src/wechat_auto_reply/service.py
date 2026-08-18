from __future__ import annotations

import logging
import threading
from typing import Any

from .storage.repository import Repository, StorageError
from .wechat import BridgeEvent, WeChatBridge


class AutoReplyService:
    """Serial phase-one bridge consumer.

    The service intentionally stops after durable ingestion and bridge
    completion. There is no LLM call and no send call in this phase.
    """

    def __init__(
        self,
        *,
        bridge: WeChatBridge,
        repository: Repository,
        poll_timeout_seconds: float = 30.0,
        poll_limit: int = 1,
        retry_delay_seconds: float = 5.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.bridge = bridge
        self.repository = repository
        self.poll_timeout_seconds = float(poll_timeout_seconds)
        self.poll_limit = int(poll_limit)
        self.retry_delay_seconds = float(retry_delay_seconds)
        self.logger = logger or logging.getLogger(__name__)

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        stop = stop_event or threading.Event()
        bridge_ready = False
        self.logger.info(
            "auto-reply service started; phase=ingest-only poll_timeout=%.1fs poll_limit=%d",
            self.poll_timeout_seconds,
            self.poll_limit,
        )

        while not stop.is_set():
            try:
                if not bridge_ready:
                    health = self.bridge.health()
                    bridge_ready = True
                    self.logger.info("hermes-wxauto bridge healthy: %s", _health_summary(health))

                events = self.bridge.get_events(
                    timeout_seconds=self.poll_timeout_seconds,
                    limit=self.poll_limit,
                )
                if events:
                    self.logger.debug("bridge returned %d event(s)", len(events))
                for event in events:
                    try:
                        self.process_event(event)
                    except Exception:
                        # One bad event must not terminate the resident process.
                        self.logger.exception("event processing failed: event_id=%s", event.event_id)
            except Exception:
                bridge_ready = False
                self.logger.exception("bridge loop failed; retrying after %.1fs", self.retry_delay_seconds)
                stop.wait(self.retry_delay_seconds)

    def process_event(self, event: BridgeEvent) -> None:
        """Process one event with ack → local commit → complete ordering."""

        existing = self.repository.get_event(event.event_id)
        if existing is not None and existing.local_status == "completed":
            # Never ack a locally completed event: hermes-wxauto's current
            # mark_batch_submitted implementation can otherwise move a completed
            # bridge row back to submitted.
            self.logger.info("skip already completed event: event_id=%s", event.event_id)
            return

        if existing is not None and existing.local_status == "stored":
            self.logger.info(
                "retrying bridge completion for durably stored event: event_id=%s chat=%s",
                event.event_id,
                event.chat_name,
            )
            self._complete_bridge_event(event)
            return

        self.repository.ensure_event_received(event)
        self.bridge.acknowledge_event(event.event_id)
        self.repository.mark_event_acknowledged(event.event_id)
        self.logger.info(
            "event acknowledged: event_id=%s chat=%s messages=%d",
            event.event_id,
            event.chat_name,
            len(event.messages),
        )

        try:
            result = self.repository.ingest_event(event)
        except Exception as exc:
            try:
                self.repository.mark_event_failed(event.event_id, str(exc))
            except StorageError:
                self.logger.exception("unable to mark failed event: event_id=%s", event.event_id)
            raise

        self.logger.info(
            "event saved: event_id=%s chat=%s conversation_id=%d inserted=%d duplicates=%d",
            event.event_id,
            event.chat_name,
            result.conversation_id,
            result.inserted_messages,
            result.duplicate_messages,
        )
        self._complete_bridge_event(event)

    def _complete_bridge_event(self, event: BridgeEvent) -> None:
        self.bridge.complete_event(event.event_id)
        self.repository.mark_event_completed(event.event_id)
        self.logger.info(
            "event completed: event_id=%s chat=%s; no message was sent (phase 1)",
            event.event_id,
            event.chat_name,
        )


def _health_summary(payload: dict[str, Any]) -> str:
    fields = ("status", "listener_alive", "queue_size", "store_path")
    return ", ".join(f"{key}={payload[key]}" for key in fields if key in payload)
