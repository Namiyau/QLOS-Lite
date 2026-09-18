from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable


StreamEventCallback = Callable[[dict[str, Any]], None]


class HermesClient:
    def __init__(self, api_url: str, api_key: str, timeout: int = 180, stream: bool = True):
        self.api_url = api_url
        self.api_key = api_key
        self.timeout = timeout
        self.stream = stream

    def chat(
        self,
        messages: list[dict[str, str]],
        session_key: str | None = None,
        session_id: str | None = None,
        on_stream_event: StreamEventCallback | None = None,
    ) -> str:
        headers = {
            "Content-Type": "application/json; charset=utf-8",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if session_id:
            headers["X-Hermes-Session-Id"] = session_id
        if session_key:
            headers["X-Hermes-Session-Key"] = session_key

        payload: dict[str, Any] = {
            "model": "hermes-agent",
            "messages": messages,
            "stream": self.stream,
        }
        if self.stream:
            return self._chat_streaming(payload, headers, on_stream_event=on_stream_event)

        return self._chat_non_streaming(payload, headers)

    def _chat_non_streaming(self, payload: dict[str, Any], headers: dict[str, str]) -> str:
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data: dict[str, Any] = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
        return _extract_openai_message_content(data)

    def _chat_streaming(
        self,
        payload: dict[str, Any],
        headers: dict[str, str],
        on_stream_event: StreamEventCallback | None = None,
    ) -> str:
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        chunks: list[str] = []
        event_name: str | None = None
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event_name = None
                    continue
                if event_name == "hermes.tool.progress":
                    if on_stream_event:
                        on_stream_event({"type": "tool_progress", "payload": event})
                    event_name = None
                    continue
                text = _extract_stream_content(event)
                if text:
                    chunks.append(text)
                    if on_stream_event:
                        on_stream_event({"type": "content", "text": text})
                event_name = None
        reply = "".join(chunks).strip()
        if not reply:
            raise ValueError("Hermes streaming response did not include assistant content")
        return reply


def _extract_stream_content(event: dict[str, Any]) -> str:
    pieces: list[str] = []
    for choice in event.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or {}
        if isinstance(delta, dict):
            pieces.append(_content_to_text(delta.get("content")))
            continue
        message = choice.get("message") or {}
        if isinstance(message, dict):
            pieces.append(_content_to_text(message.get("content")))
    return "".join(piece for piece in pieces if piece)


def _extract_openai_message_content(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise KeyError("choices")
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        return str(message)
    return _content_to_text(message.get("content"))


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if isinstance(value, str):
                    parts.append(value)
        return "".join(parts)
    return str(content)


def build_session_id(event, sender) -> str:
    if event.chat_type == "private":
        return f"qlos-qq-dm-{sender.user_id}"
    return f"qlos-qq-group-{event.group_id}-user-{sender.user_id}"


def build_session_key(event, sender) -> str:
    if event.chat_type == "private":
        return f"qlos:qq:dm:{sender.user_id}"
    return f"qlos:qq:group:{event.group_id}:user:{sender.user_id}"
