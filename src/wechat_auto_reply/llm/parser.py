from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class DecisionAction(str, Enum):
    IGNORE = "IGNORE"
    AUTO_REPLY = "AUTO_REPLY"
    NEED_HUMAN = "NEED_HUMAN"


@dataclass(frozen=True)
class ModelDecision:
    action: DecisionAction
    reply: str | None
    confidence: float | None
    reason: str | None
    raw_output: str


def parse_model_decision(output: str) -> ModelDecision:
    raw = output.strip()
    if not raw:
        raise ValueError("model output is empty")
    candidate = _extract_json(raw)
    if not isinstance(candidate, dict):
        raise ValueError("model output must be a JSON object")
    try:
        action = DecisionAction(str(candidate["action"]).strip().upper())
    except (KeyError, ValueError) as exc:
        raise ValueError("model output contains an unsupported action") from exc

    reply_value = candidate.get("reply")
    reply = None if reply_value is None else str(reply_value).strip()
    if action is DecisionAction.AUTO_REPLY and not reply:
        raise ValueError("AUTO_REPLY requires a non-empty reply")

    confidence = candidate.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise ValueError("confidence must be a number between 0 and 1") from exc
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be a number between 0 and 1")

    reason_value = candidate.get("reason")
    reason = None if reason_value is None else str(reason_value).strip() or None
    return ModelDecision(
        action=action,
        reply=reply,
        confidence=confidence,
        reason=reason,
        raw_output=output,
    )


def _extract_json(raw: str) -> Any:
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
    return json.loads(fenced.group(1) if fenced else raw)
