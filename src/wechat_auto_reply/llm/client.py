from __future__ import annotations

import json
from typing import Any, Protocol, Sequence
from urllib import error as urlerror
from urllib import request

from ..config import LLMConfig


class LLMClient(Protocol):
    """Provider boundary for a future OpenAI-compatible local model."""

    def complete(self, messages: Sequence[dict[str, str]]) -> str:
        ...


class OpenAICompatibleLLMClient:
    """Minimal provider adapter, kept unused while phase 1 is ingest-only."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def complete(self, messages: Sequence[dict[str, str]]) -> str:
        if not self.config.enabled:
            raise RuntimeError("LLM is disabled in the current configuration")
        payload = {
            "model": self.config.model,
            "messages": list(messages),
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.config.base_url}/chat/completions",
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                raw = response.read()
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc
        try:
            result: Any = json.loads(raw.decode("utf-8"))
            return str(result["choices"][0]["message"]["content"])
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("LLM returned an invalid OpenAI-compatible response") from exc
