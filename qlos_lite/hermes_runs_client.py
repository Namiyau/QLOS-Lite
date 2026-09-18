from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

from .hermes_client import StreamEventCallback, _content_to_text


ApprovalHandler = Callable[[str, dict[str, Any]], str | None]


class HermesRunsClient:
    def __init__(self, api_url: str, api_key: str, timeout: int = 180):
        self.api_url = _derive_v1_url(api_url)
        self.api_key = api_key
        self.timeout = timeout

    def chat_with_approval(
        self,
        messages: list[dict[str, str]],
        session_key: str,
        session_id: str,
        approval_handler: ApprovalHandler,
        on_stream_event: StreamEventCallback | None = None,
    ) -> str:
        instructions, user_input = _messages_to_run_parts(messages)
        run_id = self.start_run(
            user_input,
            instructions=instructions,
            session_id=session_id,
            session_key=session_key,
        )

        chunks: list[str] = []
        for event in self.stream_events(run_id):
            event_type = str(event.get("type") or event.get("event") or "")
            if event_type == "message.delta":
                delta = _extract_delta(event)
                if delta:
                    chunks.append(delta)
                    if on_stream_event:
                        on_stream_event({"type": "content", "text": delta})
                continue
            if event_type == "approval.request":
                if on_stream_event:
                    on_stream_event({"type": "tool_progress", "payload": event})
                choice = approval_handler(run_id, event) or "deny"
                self.approve(run_id, choice)
                continue
            if event_type == "run.completed":
                output = _extract_completed_output(event)
                return output or "".join(chunks).strip()
            if event_type == "run.failed":
                raise RuntimeError(str(event.get("error") or "Hermes run failed"))
            if event_type.startswith("tool.") and on_stream_event:
                on_stream_event({"type": "tool_progress", "payload": event})

        reply = "".join(chunks).strip()
        if not reply:
            raise RuntimeError("Hermes run event stream ended without output")
        return reply

    def start_run(
        self,
        user_input: str,
        instructions: str,
        session_id: str,
        session_key: str,
    ) -> str:
        payload: dict[str, Any] = {
            "input": user_input,
            "session_id": session_id,
        }
        if instructions:
            payload["instructions"] = instructions
        data = self._request_json(
            f"{self.api_url}/runs",
            payload,
            session_key=session_key,
            expected_status={200, 201, 202},
        )
        run_id = str(data.get("run_id") or data.get("id") or "")
        if not run_id:
            raise RuntimeError("Hermes runs API did not return run_id")
        return run_id

    def stream_events(self, run_id: str):
        request = urllib.request.Request(
            f"{self.api_url}/runs/{run_id}/events",
            headers=self._headers(accept="text/event-stream"),
            method="GET",
        )
        data_lines: list[str] = []
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            for raw_chunk in response:
                for raw_line in raw_chunk.splitlines(keepends=True):
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line:
                        event = _decode_sse_data(data_lines)
                        data_lines = []
                        if event is not None:
                            yield event
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[5:].strip())
            event = _decode_sse_data(data_lines)
            if event is not None:
                yield event

    def approve(self, run_id: str, choice: str) -> dict[str, Any]:
        return self._request_json(
            f"{self.api_url}/runs/{run_id}/approval",
            {"choice": choice},
            expected_status={200, 202},
        )

    def _request_json(
        self,
        url: str,
        payload: dict[str, Any],
        session_key: str | None = None,
        expected_status: set[int] | None = None,
    ) -> dict[str, Any]:
        expected_status = expected_status or {200}
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(session_key=session_key),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                status = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Hermes runs API HTTP {exc.code}: {body[:500]}") from exc
        if status not in expected_status:
            raise RuntimeError(f"Hermes runs API HTTP {status}: {body[:500]}")
        return json.loads(body or "{}")

    def _headers(self, session_key: str | None = None, accept: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if accept:
            headers["Accept"] = accept
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if session_key:
            headers["X-Hermes-Session-Key"] = session_key
        return headers


def _derive_v1_url(api_url: str) -> str:
    url = str(api_url).strip().rstrip("/")
    if url.endswith("/v1/chat/completions"):
        return url[: -len("/chat/completions")]
    if url.endswith("/chat/completions"):
        return url[: -len("/chat/completions")]
    if url.endswith("/v1"):
        return url
    return url


def _messages_to_run_parts(messages: list[dict[str, Any]]) -> tuple[str, Any]:
    instructions: list[str] = []
    inputs: list[dict[str, Any]] = []
    text_inputs: list[str] = []
    has_multimodal = False
    for message in messages:
        role = str(message.get("role") or "")
        content = message.get("content") or ""
        if role == "system":
            instructions.append(str(content))
        elif role == "user":
            inputs.append({"role": "user", "content": content})
            if isinstance(content, str):
                text_inputs.append(content)
            else:
                has_multimodal = True
    run_input: Any
    if has_multimodal:
        run_input = inputs
    else:
        run_input = "\n\n".join(part for part in text_inputs if part).strip()
    return "\n\n".join(part for part in instructions if part).strip(), run_input


def _decode_sse_data(data_lines: list[str]) -> dict[str, Any] | None:
    if not data_lines:
        return None
    data = "\n".join(data_lines).strip()
    if not data or data == "[DONE]":
        return None
    return json.loads(data)


def _extract_delta(event: dict[str, Any]) -> str:
    for key in ("delta", "text", "content"):
        value = event.get(key)
        if value is not None:
            return _content_to_text(value)
    return ""


def _extract_completed_output(event: dict[str, Any]) -> str:
    for key in ("output", "message", "content"):
        value = event.get(key)
        if value is not None:
            return _content_to_text(value).strip()
    return ""
