from __future__ import annotations

from dataclasses import dataclass

from ..llm.parser import DecisionAction, ModelDecision


@dataclass(frozen=True)
class PolicyDecision:
    should_send: bool
    action: DecisionAction
    reason: str


class PolicyEngine:
    """Small policy boundary; automatic sending stays disabled for phase 1."""

    def __init__(self, *, auto_reply_enabled: bool = False) -> None:
        self.auto_reply_enabled = auto_reply_enabled

    def evaluate(self, decision: ModelDecision) -> PolicyDecision:
        if decision.action is not DecisionAction.AUTO_REPLY:
            return PolicyDecision(False, decision.action, "model did not request an auto reply")
        if not self.auto_reply_enabled:
            return PolicyDecision(False, decision.action, "automatic sending is disabled")
        if not decision.reply:
            return PolicyDecision(False, decision.action, "auto reply has no reply text")
        return PolicyDecision(True, decision.action, "policy allows auto reply")
