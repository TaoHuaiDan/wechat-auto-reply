from __future__ import annotations

import pytest

from wechat_auto_reply.llm.parser import DecisionAction, parse_model_decision


def test_decision_parser_reserves_three_actions():
    decision = parse_model_decision(
        '{"action":"AUTO_REPLY","reply":"在的","confidence":0.93,"reason":"闲聊"}'
    )
    assert decision.action is DecisionAction.AUTO_REPLY
    assert decision.reply == "在的"
    assert decision.confidence == 0.93


def test_auto_reply_requires_reply_text():
    with pytest.raises(ValueError, match="requires"):
        parse_model_decision('{"action":"AUTO_REPLY"}')
