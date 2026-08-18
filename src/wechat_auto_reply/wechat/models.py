from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


class BridgeProtocolError(ValueError):
    """Raised when a hermes-wxauto response cannot be safely interpreted."""


@dataclass(frozen=True)
class BridgeMessage:
    external_message_key: str
    chat_name: str
    content: str
    message_type: str
    sender: str | None
    is_self: bool | None
    time_text: str | None
    raw: dict[str, Any]

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        chat_name: str,
        occurrence_index: int,
    ) -> "BridgeMessage":
        content_value = payload.get("content")
        if content_value is None:
            content_value = payload.get("raw_name")
        content = str(content_value or "").strip()
        if not content:
            raise BridgeProtocolError("bridge message has empty content")

        message_type = str(payload.get("message_type") or "unknown").strip() or "unknown"
        message_chat_name = str(payload.get("chat_name") or chat_name).strip()
        provided_key = str(payload.get("message_key") or "").strip()
        time_text = _optional_str(payload.get("time_text"))
        sender = _optional_str(payload.get("sender"))
        is_self = _optional_bool(payload.get("is_self"))
        key = provided_key or _fallback_message_key(
            chat_name=message_chat_name,
            message_type=message_type,
            content=content,
            time_text=time_text,
            occurrence_index=occurrence_index,
        )

        return cls(
            external_message_key=key,
            chat_name=message_chat_name,
            content=content,
            message_type=message_type,
            sender=sender,
            is_self=is_self,
            time_text=time_text,
            raw=dict(payload),
        )


@dataclass(frozen=True)
class BridgeEvent:
    event_id: str
    batch_id: str
    platform: str
    chat_id: str
    chat_name: str
    status: str
    created_at: float | None
    frozen_at: float | None
    submitted_at: float | None
    completed_at: float | None
    messages: tuple[BridgeMessage, ...]
    raw: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "BridgeEvent":
        raw = dict(payload)
        event_id = str(payload.get("batch_id") or payload.get("event_id") or "").strip()
        batch_id = str(payload.get("batch_id") or event_id).strip()
        chat_name = str(payload.get("chat_name") or "").strip()
        if not event_id or not batch_id:
            raise BridgeProtocolError("bridge event is missing batch_id/event_id")
        if not chat_name:
            raise BridgeProtocolError(f"bridge event {event_id} is missing chat_name")

        chat_id = str(payload.get("chat_id") or f"wechat:{chat_name}").strip()
        if not chat_id:
            raise BridgeProtocolError(f"bridge event {event_id} is missing chat_id")

        raw_messages = payload.get("messages")
        if raw_messages is None:
            raw_messages = []
        if not isinstance(raw_messages, (list, tuple)):
            raise BridgeProtocolError(f"bridge event {event_id} messages must be a list")

        messages: list[BridgeMessage] = []
        for index, raw_message in enumerate(raw_messages):
            if not isinstance(raw_message, Mapping):
                raise BridgeProtocolError(f"bridge event {event_id} contains a non-object message")
            messages.append(
                BridgeMessage.from_payload(
                    raw_message,
                    chat_name=chat_name,
                    occurrence_index=index,
                )
            )

        return cls(
            event_id=event_id,
            batch_id=batch_id,
            platform=str(payload.get("platform") or "wechat_desktop"),
            chat_id=chat_id,
            chat_name=chat_name,
            status=str(payload.get("status") or "unknown"),
            created_at=_optional_float(payload.get("created_at")),
            frozen_at=_optional_float(payload.get("frozen_at")),
            submitted_at=_optional_float(payload.get("submitted_at")),
            completed_at=_optional_float(payload.get("completed_at")),
            messages=tuple(messages),
            raw=raw,
        )


def _fallback_message_key(
    *,
    chat_name: str,
    message_type: str,
    content: str,
    time_text: str | None,
    occurrence_index: int,
) -> str:
    payload = {
        "chat_name": chat_name,
        "message_type": message_type,
        "content": content,
        "time_text": time_text,
        "occurrence_index": occurrence_index,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "derived-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
