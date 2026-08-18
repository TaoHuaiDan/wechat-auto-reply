from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import error as urlerror
from urllib import parse, request

from .models import BridgeEvent, BridgeProtocolError


class BridgeError(RuntimeError):
    """Base error for bridge transport and protocol failures."""


class BridgeTransportError(BridgeError):
    """The local bridge could not be reached or did not answer in time."""


class BridgeRequestError(BridgeError):
    """The bridge returned a non-success HTTP/application response."""


@dataclass(frozen=True)
class BridgeActionResult:
    event_id: str
    status: str
    raw: dict[str, Any]


class WeChatBridge(Protocol):
    """Boundary used by the application service.

    ``send_message`` is intentionally unused in phase 1. Keeping it here makes
    the future policy-to-UI boundary explicit without enabling auto-send.
    """

    def health(self) -> dict[str, Any]:
        ...

    def get_events(self, *, timeout_seconds: float, limit: int) -> tuple[BridgeEvent, ...]:
        ...

    def acknowledge_event(self, event_id: str) -> BridgeActionResult:
        ...

    def complete_event(self, event_id: str) -> BridgeActionResult:
        ...

    def send_message(self, chat_name: str, message: str) -> dict[str, Any]:
        ...


class HttpWeChatBridge:
    """HTTP adapter for the current hermes-wxauto bridge-server API."""

    def __init__(self, base_url: str, *, request_timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.request_timeout_seconds = float(request_timeout_seconds)

    def health(self) -> dict[str, Any]:
        payload = self._request_json("GET", "/health")
        if payload.get("status") != "ok":
            raise BridgeRequestError(f"bridge health is not ok: {payload}")
        return payload

    def get_events(self, *, timeout_seconds: float, limit: int) -> tuple[BridgeEvent, ...]:
        query = parse.urlencode({"timeout": timeout_seconds, "limit": limit})
        payload = self._request_json(
            "GET",
            f"/events?{query}",
            timeout_seconds=float(timeout_seconds) + self.request_timeout_seconds,
        )
        if payload.get("status") != "ok":
            raise BridgeRequestError(f"bridge event poll failed: {payload}")
        raw_events = payload.get("events") or []
        if not isinstance(raw_events, list):
            raise BridgeProtocolError("bridge events response must contain a list")
        try:
            return tuple(BridgeEvent.from_payload(item) for item in raw_events)
        except BridgeProtocolError:
            raise
        except (TypeError, ValueError) as exc:
            raise BridgeProtocolError("bridge event payload is invalid") from exc

    def acknowledge_event(self, event_id: str) -> BridgeActionResult:
        return self._event_action(event_id, "ack")

    def complete_event(self, event_id: str) -> BridgeActionResult:
        return self._event_action(event_id, "complete")

    def send_message(self, chat_name: str, message: str) -> dict[str, Any]:
        # This method is a reserved adapter capability. AutoReplyService does
        # not call it until a later phase has an enabled policy.
        return self._request_json(
            "POST",
            "/send",
            data={"who": chat_name, "message": message},
            timeout_seconds=max(self.request_timeout_seconds, 60.0),
        )

    def _event_action(self, event_id: str, action: str) -> BridgeActionResult:
        if not event_id.strip():
            raise BridgeProtocolError("event_id must not be empty")
        payload = self._request_json(
            "POST",
            f"/events/{parse.quote(event_id, safe='')}/{action}",
        )
        if payload.get("status") != "ok":
            raise BridgeRequestError(f"bridge event {action} failed: {payload}")
        return BridgeActionResult(
            event_id=str(payload.get("batch_id") or event_id),
            status=str(payload.get("batch_status") or "unknown"),
            raw=payload,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(
                req,
                timeout=self.request_timeout_seconds if timeout_seconds is None else timeout_seconds,
            ) as response:
                raw = response.read()
        except urlerror.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except OSError:
                detail = ""
            raise BridgeRequestError(
                f"bridge HTTP {exc.code} for {method} {path}: {detail[:500]}"
            ) from exc
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            raise BridgeTransportError(f"bridge request failed for {method} {path}: {exc}") from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BridgeProtocolError(f"bridge returned invalid JSON for {method} {path}") from exc
        if not isinstance(payload, dict):
            raise BridgeProtocolError(f"bridge response must be a JSON object for {method} {path}")
        return payload
