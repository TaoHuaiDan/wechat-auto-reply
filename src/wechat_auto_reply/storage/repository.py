from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..wechat.models import BridgeEvent, BridgeMessage
from .database import Database


class StorageError(RuntimeError):
    """Base class for storage and event identity errors."""


class ConversationIdentityError(StorageError):
    """Raised when one bridge identity is presented as two conversations."""


class EventValidationError(StorageError):
    """Raised when an event contains messages from another conversation."""


@dataclass(frozen=True)
class ConversationRecord:
    id: int
    bridge_chat_id: str
    chat_name: str
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    batch_id: str
    conversation_id: int
    bridge_status: str
    local_status: str
    message_count: int
    received_at: float
    acknowledged_at: float | None
    stored_at: float | None
    completed_at: float | None
    last_error: str | None


@dataclass(frozen=True)
class MessageRecord:
    id: int
    conversation_id: int
    external_message_key: str
    event_id: str | None
    direction: str
    sender: str | None
    message_type: str
    content: str
    time_text: str | None
    is_self: bool | None
    observed_at: float
    raw: dict[str, Any]


@dataclass(frozen=True)
class IngestResult:
    event_id: str
    conversation_id: int
    inserted_messages: int
    duplicate_messages: int
    local_status: str


class Repository:
    """Application data access layer.

    The bridge database remains owned by hermes-wxauto. This repository stores
    only the application-side audit trail and uses bridge message keys/event IDs
    as idempotency keys.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def get_event(self, event_id: str) -> EventRecord | None:
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT event_id, batch_id, conversation_id, bridge_status,
                       local_status, message_count, received_at,
                       acknowledged_at, stored_at, completed_at, last_error
                FROM bridge_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
        return _event_record(row) if row is not None else None

    def get_conversation(self, bridge_chat_id: str) -> ConversationRecord | None:
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT id, bridge_chat_id, chat_name, created_at, updated_at
                FROM conversations
                WHERE bridge_chat_id = ?
                """,
                (bridge_chat_id,),
            ).fetchone()
        return _conversation_record(row) if row is not None else None

    def get_conversation_by_id(self, conversation_id: int) -> ConversationRecord | None:
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT id, bridge_chat_id, chat_name, created_at, updated_at
                FROM conversations
                WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()
        return _conversation_record(row) if row is not None else None

    def ensure_event_received(self, event: BridgeEvent, *, now: float | None = None) -> EventRecord:
        """Persist the event identity before calling bridge ack.

        This closes the restart window between ack and message ingestion. It is
        deliberately separate from ``ingest_event`` so a crash can be retried
        without acknowledging an unknown event.
        """

        timestamp = _now(now)
        _validate_event(event)
        payload_json = _json(event.raw)
        with self.database.connection() as conn:
            conversation_id = _ensure_conversation(conn, event, timestamp)
            row = conn.execute(
                "SELECT * FROM bridge_events WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO bridge_events(
                        event_id, batch_id, conversation_id, bridge_status,
                        local_status, message_count, received_at, payload_json
                    ) VALUES (?, ?, ?, ?, 'received', ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.batch_id,
                        conversation_id,
                        event.status,
                        len(event.messages),
                        timestamp,
                        payload_json,
                    ),
                )
            else:
                _assert_event_identity(row, event, conversation_id)
                if row["local_status"] == "failed":
                    conn.execute(
                        """
                        UPDATE bridge_events
                        SET local_status = 'received', bridge_status = ?,
                            message_count = ?, last_error = NULL,
                            payload_json = ?
                        WHERE event_id = ?
                        """,
                        (event.status, len(event.messages), payload_json, event.event_id),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE bridge_events
                        SET bridge_status = ?, message_count = ?, payload_json = ?
                        WHERE event_id = ?
                        """,
                        (event.status, len(event.messages), payload_json, event.event_id),
                    )
            stored = conn.execute(
                "SELECT * FROM bridge_events WHERE event_id = ?", (event.event_id,)
            ).fetchone()
        assert stored is not None
        return _event_record(stored)

    def mark_event_acknowledged(self, event_id: str, *, now: float | None = None) -> None:
        timestamp = _now(now)
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT local_status FROM bridge_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                raise StorageError(f"event not found: {event_id}")
            if row["local_status"] == "completed":
                return
            conn.execute(
                """
                UPDATE bridge_events
                SET local_status = 'acknowledged',
                    acknowledged_at = COALESCE(acknowledged_at, ?),
                    last_error = NULL
                WHERE event_id = ?
                """,
                (timestamp, event_id),
            )

    def ingest_event(self, event: BridgeEvent, *, now: float | None = None) -> IngestResult:
        """Atomically insert the event's messages, tolerating redelivery."""

        timestamp = _now(now)
        _validate_event(event)
        payload_json = _json(event.raw)
        observed_at = event.created_at if event.created_at is not None else timestamp
        inserted = 0
        duplicates = 0

        with self.database.connection() as conn:
            conversation_id = _ensure_conversation(conn, event, timestamp)
            event_row = conn.execute(
                "SELECT * FROM bridge_events WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if event_row is None:
                conn.execute(
                    """
                    INSERT INTO bridge_events(
                        event_id, batch_id, conversation_id, bridge_status,
                        local_status, message_count, received_at, payload_json
                    ) VALUES (?, ?, ?, ?, 'received', ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.batch_id,
                        conversation_id,
                        event.status,
                        len(event.messages),
                        timestamp,
                        payload_json,
                    ),
                )
                event_row = conn.execute(
                    "SELECT * FROM bridge_events WHERE event_id = ?", (event.event_id,)
                ).fetchone()
            assert event_row is not None
            _assert_event_identity(event_row, event, conversation_id)

            for message in event.messages:
                existing = conn.execute(
                    """
                    SELECT conversation_id, content, message_type, event_id
                    FROM messages
                    WHERE external_message_key = ?
                    """,
                    (message.external_message_key,),
                ).fetchone()
                if existing is not None:
                    if int(existing["conversation_id"]) != conversation_id:
                        raise ConversationIdentityError(
                            "message key is already owned by another conversation: "
                            f"{message.external_message_key}"
                        )
                    if (
                        str(existing["content"]) != message.content
                        or str(existing["message_type"]) != message.message_type
                    ):
                        raise StorageError(
                            "message key was reused with different content: "
                            f"{message.external_message_key}"
                        )
                    duplicates += 1
                    continue

                conn.execute(
                    """
                    INSERT INTO messages(
                        conversation_id, external_message_key, event_id, direction,
                        sender, message_type, content, time_text, is_self,
                        observed_at, raw_json
                    ) VALUES (?, ?, ?, 'incoming', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        conversation_id,
                        message.external_message_key,
                        event.event_id,
                        message.sender,
                        message.message_type,
                        message.content,
                        message.time_text,
                        _bool_int(message.is_self),
                        observed_at,
                        _json(message.raw),
                    ),
                )
                inserted += 1

            conn.execute(
                """
                UPDATE bridge_events
                SET bridge_status = ?, local_status = 'stored',
                    message_count = ?, stored_at = COALESCE(stored_at, ?),
                    last_error = NULL, payload_json = ?
                WHERE event_id = ?
                """,
                (event.status, len(event.messages), timestamp, payload_json, event.event_id),
            )

        return IngestResult(
            event_id=event.event_id,
            conversation_id=conversation_id,
            inserted_messages=inserted,
            duplicate_messages=duplicates,
            local_status="stored",
        )

    def mark_event_completed(self, event_id: str, *, now: float | None = None) -> None:
        timestamp = _now(now)
        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE bridge_events
                SET local_status = 'completed', completed_at = COALESCE(completed_at, ?),
                    last_error = NULL
                WHERE event_id = ?
                """,
                (timestamp, event_id),
            )
            if cursor.rowcount != 1:
                raise StorageError(f"event not found: {event_id}")

    def mark_event_failed(self, event_id: str, error: str) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                UPDATE bridge_events
                SET local_status = 'failed', last_error = ?
                WHERE event_id = ? AND local_status <> 'completed'
                """,
                (error[:2000], event_id),
            )

    def list_messages(self, conversation_id: int, *, limit: int = 20) -> tuple[MessageRecord, ...]:
        if limit <= 0:
            return ()
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, conversation_id, external_message_key, event_id,
                       direction, sender, message_type, content, time_text,
                       is_self, observed_at, raw_json
                FROM messages
                WHERE conversation_id = ?
                ORDER BY observed_at DESC, id DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()
        return tuple(_message_record(row) for row in reversed(rows))

    def record_decision(
        self,
        *,
        event_id: str,
        conversation_id: int,
        context: Mapping[str, Any],
        raw_model_output: str | None,
        action: str | None,
        proposed_reply: str | None,
        confidence: float | None,
        reason: str | None,
        should_send: bool | None,
        sent: bool | None,
        now: float | None = None,
    ) -> int:
        """Persist the future model/policy audit record without invoking a model."""

        timestamp = _now(now)
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO decisions(
                    event_id, conversation_id, context_json, raw_model_output,
                    action, proposed_reply, confidence, reason, should_send,
                    sent, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    conversation_id = excluded.conversation_id,
                    context_json = excluded.context_json,
                    raw_model_output = excluded.raw_model_output,
                    action = excluded.action,
                    proposed_reply = excluded.proposed_reply,
                    confidence = excluded.confidence,
                    reason = excluded.reason,
                    should_send = excluded.should_send,
                    sent = excluded.sent,
                    updated_at = excluded.updated_at
                """,
                (
                    event_id,
                    conversation_id,
                    _json(context),
                    raw_model_output,
                    action,
                    proposed_reply,
                    confidence,
                    reason,
                    _bool_int(should_send),
                    _bool_int(sent),
                    timestamp,
                    timestamp,
                ),
            )
            row = conn.execute("SELECT id FROM decisions WHERE event_id = ?", (event_id,)).fetchone()
        assert row is not None
        return int(row["id"])


def _validate_event(event: BridgeEvent) -> None:
    if not event.event_id.strip() or not event.batch_id.strip():
        raise EventValidationError("bridge event is missing event_id/batch_id")
    if not event.chat_name.strip() or not event.chat_id.strip():
        raise EventValidationError("bridge event is missing chat identity")
    for message in event.messages:
        if message.chat_name and message.chat_name != event.chat_name:
            raise EventValidationError(
                "message chat_name does not match event chat_name: "
                f"{message.chat_name!r} != {event.chat_name!r}"
            )
        if not message.content.strip():
            raise EventValidationError("bridge event contains an empty message")


def _ensure_conversation(
    conn: sqlite3.Connection,
    event: BridgeEvent,
    timestamp: float,
) -> int:
    row = conn.execute(
        "SELECT id, chat_name FROM conversations WHERE bridge_chat_id = ?",
        (event.chat_id,),
    ).fetchone()
    if row is not None:
        if str(row["chat_name"]) != event.chat_name:
            raise ConversationIdentityError(
                "bridge chat identity changed display name: "
                f"{row['chat_name']!r} != {event.chat_name!r}"
            )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (timestamp, row["id"]),
        )
        return int(row["id"])

    cursor = conn.execute(
        """
        INSERT INTO conversations(bridge_chat_id, chat_name, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (event.chat_id, event.chat_name, timestamp, timestamp),
    )
    return int(cursor.lastrowid)


def _assert_event_identity(
    row: sqlite3.Row,
    event: BridgeEvent,
    conversation_id: int,
) -> None:
    if int(row["conversation_id"]) != conversation_id:
        raise ConversationIdentityError(f"event is owned by another conversation: {event.event_id}")
    if str(row["batch_id"]) != event.batch_id:
        raise StorageError(f"event_id was reused with another batch_id: {event.event_id}")


def _conversation_record(row: sqlite3.Row) -> ConversationRecord:
    return ConversationRecord(
        id=int(row["id"]),
        bridge_chat_id=str(row["bridge_chat_id"]),
        chat_name=str(row["chat_name"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )


def _event_record(row: sqlite3.Row) -> EventRecord:
    return EventRecord(
        event_id=str(row["event_id"]),
        batch_id=str(row["batch_id"]),
        conversation_id=int(row["conversation_id"]),
        bridge_status=str(row["bridge_status"]),
        local_status=str(row["local_status"]),
        message_count=int(row["message_count"]),
        received_at=float(row["received_at"]),
        acknowledged_at=_optional_float(row["acknowledged_at"]),
        stored_at=_optional_float(row["stored_at"]),
        completed_at=_optional_float(row["completed_at"]),
        last_error=str(row["last_error"]) if row["last_error"] is not None else None,
    )


def _message_record(row: sqlite3.Row) -> MessageRecord:
    raw = json.loads(str(row["raw_json"]))
    return MessageRecord(
        id=int(row["id"]),
        conversation_id=int(row["conversation_id"]),
        external_message_key=str(row["external_message_key"]),
        event_id=str(row["event_id"]) if row["event_id"] is not None else None,
        direction=str(row["direction"]),
        sender=str(row["sender"]) if row["sender"] is not None else None,
        message_type=str(row["message_type"]),
        content=str(row["content"]),
        time_text=str(row["time_text"]) if row["time_text"] is not None else None,
        is_self=_optional_bool(row["is_self"]),
        observed_at=float(row["observed_at"]),
        raw=raw if isinstance(raw, dict) else {},
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _bool_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    return bool(int(value))


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _now(value: float | None) -> float:
    return time.time() if value is None else float(value)
