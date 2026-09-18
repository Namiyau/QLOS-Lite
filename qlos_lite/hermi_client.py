from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .prompt_builder import qq_channel_output_prompt


class HermiGatewayClient:
    def __init__(self, base_url: str, token: str, timeout: int = 180):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def send_qq_event(
        self,
        event: Any,
        sender: Any,
        risk: dict[str, Any],
        session_id: str,
        session_key: str,
        trusted_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "message_id": event.message_id,
            "chat_type": event.chat_type,
            "user_id": event.user_id,
            "nickname": event.nickname,
            "text": event.text,
            "group_id": event.group_id,
            "attachments": event.attachments or [],
            "sender_role": sender.role,
            "risk": risk,
            "session_id": session_id,
            "session_key": session_key,
            "qlos_prompt": qq_channel_output_prompt(),
        }
        if trusted_context is not None:
            payload["trusted_context"] = trusted_context
        return _request_json(
            f"{self.base_url}/channels/qq/events",
            payload,
            self.token,
            self.timeout,
        )


def _request_json(url: str, payload: dict[str, Any], token: str, timeout: int) -> dict[str, Any]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Hermi Gateway HTTP {exc.code}: {body[:500]}") from exc
    return json.loads(body or "{}")
