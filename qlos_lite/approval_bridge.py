from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from .logger import scrub_sensitive


_STATE_LOCK = threading.Lock()

APPROVAL_STATE_FILE = "pending_approvals.json"

DENY_WORDS = {
    "拒绝",
    "不同意",
    "不批准",
    "不允许",
    "否",
    "取消",
    "deny",
    "/deny",
    "no",
    "n",
}
SESSION_APPROVE_WORDS = {
    "本会话同意",
    "本会话批准",
    "本会话允许",
    "会话同意",
    "同意本会话",
    "approve session",
    "/approve session",
    "session",
}
ALWAYS_APPROVE_WORDS = {
    "永久同意",
    "永久批准",
    "长期同意",
    "总是同意",
    "一直同意",
    "approve always",
    "/approve always",
    "always",
}
ONCE_APPROVE_WORDS = {
    "同意",
    "批准",
    "允许",
    "确认",
    "本次同意",
    "本次批准",
    "允许一次",
    "approve",
    "/approve",
    "yes",
    "y",
    "ok",
}


class ApprovalBridge:
    def __init__(
        self,
        state_dir: str | Path,
        wait_timeout: int = 600,
        poll_interval: float = 1.0,
    ):
        self.state_dir = Path(state_dir)
        self.state_file = self.state_dir / APPROVAL_STATE_FILE
        self.wait_timeout = wait_timeout
        self.poll_interval = poll_interval

    def parse_approval_choice(self, text: str) -> str | None:
        normalized = re.sub(r"\s+", " ", str(text).strip().lower())
        if not normalized:
            return None
        if normalized in DENY_WORDS:
            return "deny"
        if normalized in SESSION_APPROVE_WORDS:
            return "session"
        if normalized in ALWAYS_APPROVE_WORDS:
            return "always"
        if normalized in ONCE_APPROVE_WORDS:
            return "once"
        if len(normalized) <= 20:
            if normalized.startswith("/approve"):
                return "once"
            if normalized.startswith(("同意", "批准", "允许")):
                return "once"
        return None

    def has_pending(self, session_id: str) -> bool:
        return self.get_pending(session_id) is not None

    def get_pending(self, session_id: str) -> dict[str, Any] | None:
        state = self._load_state()
        pending = state.get("sessions", {}).get(session_id)
        return pending if isinstance(pending, dict) else None

    def record_pending(
        self,
        session_id: str,
        run_id: str,
        qq_event: Any,
        sender: Any,
        approval_event: dict[str, Any],
        session_key: str,
    ) -> None:
        with _STATE_LOCK:
            state = self._load_state_unlocked()
            sessions = state.setdefault("sessions", {})
            sessions[session_id] = {
                "session_id": session_id,
                "session_key": session_key,
                "run_id": run_id,
                "created_at": time.time(),
                "chat_type": qq_event.chat_type,
                "group_id": qq_event.group_id,
                "user_id": sender.user_id,
                "sender_role": sender.role,
                "message_id": qq_event.message_id,
                "approval": scrub_sensitive(approval_event),
                "decision": None,
                "decided_at": None,
            }
            self._save_state_unlocked(state)

    def set_decision(self, session_id: str, choice: str) -> bool:
        with _STATE_LOCK:
            state = self._load_state_unlocked()
            pending = state.get("sessions", {}).get(session_id)
            if not isinstance(pending, dict):
                return False
            pending["decision"] = choice
            pending["decided_at"] = time.time()
            self._save_state_unlocked(state)
            return True

    def clear_pending(self, session_id: str) -> None:
        with _STATE_LOCK:
            state = self._load_state_unlocked()
            sessions = state.setdefault("sessions", {})
            sessions.pop(session_id, None)
            self._save_state_unlocked(state)

    def wait_for_decision(self, session_id: str) -> str | None:
        deadline = time.monotonic() + max(0, self.wait_timeout)
        while time.monotonic() <= deadline:
            pending = self.get_pending(session_id)
            decision = pending.get("decision") if pending else None
            if decision:
                return str(decision)
            time.sleep(max(0.05, self.poll_interval))
        return None

    def format_approval_prompt(self, approval_event: dict[str, Any]) -> str:
        summary = _approval_summary(approval_event)
        return (
            "Hermes 需要 QQ 审批：\n"
            f"{summary}\n"
            "回复：同意 / 拒绝 / 本会话同意 / 永久同意\n"
            f"{max(1, self.wait_timeout // 60)} 分钟内有效。只有 owner QQ 可批准。"
        )

    def _load_state(self) -> dict[str, Any]:
        with _STATE_LOCK:
            return self._load_state_unlocked()

    def _load_state_unlocked(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"sessions": {}}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8") or "{}")
        except (OSError, json.JSONDecodeError):
            return {"sessions": {}}
        if not isinstance(data, dict):
            return {"sessions": {}}
        if not isinstance(data.get("sessions"), dict):
            data["sessions"] = {}
        return data

    def _save_state_unlocked(self, state: dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp_file = self.state_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_file.replace(self.state_file)


def _approval_summary(approval_event: dict[str, Any]) -> str:
    payload = scrub_sensitive(dict(approval_event))
    for key in ("command", "tool", "tool_name", "name", "reason"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return f"{key}: {_clip(value.strip(), 500)}"
    if "args" in payload:
        return f"args: {_clip(json.dumps(payload['args'], ensure_ascii=False), 500)}"
    return _clip(json.dumps(payload, ensure_ascii=False), 700)


def _clip(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
