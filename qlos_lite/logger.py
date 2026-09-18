from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SENSITIVE_MARKERS = [
    "Authorization: Bearer",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "HERMES_API_KEY",
    "QLOS_HERMES_API_KEY",
    "cookie=",
]


SENSITIVE_FIELD_NAMES = {
    "api_key",
    "access_token",
    "authorization",
    "cookie",
    "hermes_api_key",
    "onebot_access_token",
    "onebot_inbound_token",
    "qlos_hermes_api_key",
}


def _is_sensitive_field_name(key: Any) -> bool:
    normalized = str(key).lower().strip()
    return normalized in SENSITIVE_FIELD_NAMES or normalized.endswith("_api_key") or normalized.endswith("_token")


def scrub_sensitive(value: Any) -> Any:
    if isinstance(value, str):
        scrubbed = value
        for marker in SENSITIVE_MARKERS:
            scrubbed = scrubbed.replace(marker, "[已隐藏敏感字段]")
        return scrubbed
    if isinstance(value, dict):
        return {key: scrub_sensitive(item) for key, item in value.items() if not _is_sensitive_field_name(key)}
    if isinstance(value, list):
        return [scrub_sensitive(item) for item in value]
    return value


class AuditLogger:
    def __init__(self, log_dir: str | Path, enabled: bool = True):
        self.log_dir = Path(log_dir)
        self.enabled = enabled

    def _write(self, name: str, record: dict[str, Any]) -> None:
        if not self.enabled:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        payload = scrub_sensitive({"ts": datetime.now(timezone.utc).isoformat(), **record})
        with (self.log_dir / f"{name}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _base(self, event, sender=None, risk=None) -> dict[str, Any]:
        record = {
            "message_id": event.message_id,
            "chat_type": event.chat_type,
            "group_id": event.group_id,
            "user_id": event.user_id,
            "nickname": event.nickname,
            "text": event.text,
        }
        if sender:
            record["sender_role"] = sender.role
        if risk:
            record["risk"] = risk["risk"]
            record["reason"] = risk["reason"]
        return record

    def log_inbound(self, event, sender, risk) -> None:
        self._write("inbound", self._base(event, sender, risk))

    def log_outbound(self, event, sender, reply: str) -> None:
        self._write("outbound", {**self._base(event, sender), "reply": reply})

    def log_blocked(self, event, sender, risk, reply: str) -> None:
        self._write("blocked", {**self._base(event, sender, risk), "reply": reply})

    def log_error(self, event, exc: Exception) -> None:
        self._write("errors", {**self._base(event), "error_type": type(exc).__name__, "error": str(exc)})
