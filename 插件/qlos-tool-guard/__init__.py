from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


BLOCKED_FOR_NON_OWNER = {
    "write_file",
    "patch",
    "terminal",
    "process",
}

DEFAULT_IDENTITY_PATH = Path("state") / "qlos_lite" / "session_identity.jsonl"
DEFAULT_MAX_IDENTITY_AGE_SECONDS = 600


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", pre_tool_call)


def pre_tool_call(**kwargs: Any) -> dict[str, str] | None:
    tool_name = normalize_tool_name(kwargs.get("tool_name"))
    if tool_name not in BLOCKED_FOR_NON_OWNER:
        return None

    session_id = str(kwargs.get("session_id") or "")
    if not should_enforce_session(session_id):
        return None

    identity = load_identity_for_session(session_id)
    if not is_owner_identity(identity):
        return {
            "action": "block",
            "message": (
                "QLOS tool guard blocked this tool call: sender is not verified owner. "
                f"Tool '{tool_name}' requires owner permission."
            ),
        }
    return None


def normalize_tool_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    for separator in (":", "/", "."):
        if separator in text:
            text = text.rsplit(separator, 1)[-1]
    return text


def should_enforce_session(session_id: str) -> bool:
    if os.getenv("QLOS_TOOL_GUARD_ENFORCE_ALL", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return session_id.startswith("qlos-") or session_id.startswith("qlos:")


def identity_file_path() -> Path:
    configured = os.getenv("QLOS_TOOL_GUARD_IDENTITY_FILE", "").strip()
    if configured:
        return Path(configured)
    return DEFAULT_IDENTITY_PATH


def load_identity_for_session(session_id: str) -> dict[str, Any]:
    path = identity_file_path()
    if not session_id or not path.exists():
        return {"role": "non-owner", "is_owner": False, "source": "missing"}

    latest: dict[str, Any] | None = None
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(record.get("session_id") or "") == session_id:
                    latest = record
    except OSError:
        return {"role": "non-owner", "is_owner": False, "source": "unreadable"}

    if not latest:
        return {"role": "non-owner", "is_owner": False, "source": "not_found"}
    if identity_expired(latest):
        return {"role": "non-owner", "is_owner": False, "source": "expired"}
    return latest


def identity_expired(identity: dict[str, Any]) -> bool:
    expires_at = identity.get("expires_at")
    if isinstance(expires_at, (int, float)):
        return time.time() > float(expires_at)
    max_age = int(os.getenv("QLOS_TOOL_GUARD_MAX_IDENTITY_AGE_SECONDS", str(DEFAULT_MAX_IDENTITY_AGE_SECONDS)))
    ts = identity.get("ts")
    if isinstance(ts, (int, float)):
        return time.time() - float(ts) > max_age
    return False


def is_owner_identity(identity: dict[str, Any]) -> bool:
    return bool(identity.get("is_owner")) or str(identity.get("role") or "").strip().lower() == "owner"
