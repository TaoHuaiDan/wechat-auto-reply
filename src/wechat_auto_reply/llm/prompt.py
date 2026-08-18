from __future__ import annotations

from ..context.builder import ConversationContext


SYSTEM_PROMPT = """你是一个本地微信自动回复助手。你必须只返回 JSON 决策，不要返回 Markdown。可用 action 为 IGNORE、AUTO_REPLY、NEED_HUMAN。"""


def build_prompt(context: ConversationContext) -> list[dict[str, str]]:
    """Build the future model input in one place; phase 1 never calls it."""

    lines = [f"会话：{context.conversation.chat_name}", "最近消息："]
    for message in context.recent_messages:
        sender = message.sender or ("我" if message.direction == "outgoing" else "对方")
        lines.append(f"- {sender}: {message.content}")
    lines.append("\n当前新消息：")
    for message in context.incoming_messages:
        sender = message.sender or "对方"
        lines.append(f"- {sender}: {message.content}")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]
