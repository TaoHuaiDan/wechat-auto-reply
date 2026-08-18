from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..storage.repository import ConversationRecord, MessageRecord


@dataclass(frozen=True)
class ContextMessage:
    content: str
    direction: str
    sender: str | None = None
    message_type: str = "unknown"
    time_text: str | None = None

    @classmethod
    def from_record(cls, message: MessageRecord) -> "ContextMessage":
        return cls(
            content=message.content,
            direction=message.direction,
            sender=message.sender,
            message_type=message.message_type,
            time_text=message.time_text,
        )


@dataclass(frozen=True)
class ConversationContext:
    conversation: ConversationRecord
    recent_messages: tuple[ContextMessage, ...]
    incoming_messages: tuple[ContextMessage, ...]
    # These fields are intentionally empty extension points. Retrieval,
    # persona, and long-term memory are not implemented in phase 1.
    contact_profile: Mapping[str, Any] | None = None
    persona: Mapping[str, Any] | None = None
    long_term_summary: str | None = None
    retrieved_history: tuple[ContextMessage, ...] = ()
    long_term_memory: tuple[str, ...] = ()


class ContextBuilder:
    """Assemble model-ready context without knowing how messages are stored."""

    def build(
        self,
        *,
        conversation: ConversationRecord,
        recent_messages: Sequence[MessageRecord | ContextMessage],
        incoming_messages: Sequence[MessageRecord | ContextMessage],
        contact_profile: Mapping[str, Any] | None = None,
        persona: Mapping[str, Any] | None = None,
        long_term_summary: str | None = None,
        retrieved_history: Sequence[MessageRecord | ContextMessage] = (),
        long_term_memory: Sequence[str] = (),
    ) -> ConversationContext:
        return ConversationContext(
            conversation=conversation,
            recent_messages=tuple(_as_context_message(message) for message in recent_messages),
            incoming_messages=tuple(_as_context_message(message) for message in incoming_messages),
            contact_profile=contact_profile,
            persona=persona,
            long_term_summary=long_term_summary,
            retrieved_history=tuple(_as_context_message(message) for message in retrieved_history),
            long_term_memory=tuple(str(item) for item in long_term_memory),
        )


def _as_context_message(message: MessageRecord | ContextMessage) -> ContextMessage:
    if isinstance(message, ContextMessage):
        return message
    return ContextMessage.from_record(message)
