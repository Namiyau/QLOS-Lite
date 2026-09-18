from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


DEFAULT_IDENTITY_TTL_SECONDS = 3 * 24 * 60 * 60


def write_session_identity(
    event: Any,
    sender: Any,
    risk: dict[str, Any],
    session_id: str,
    session_key: str,
    identity_dir: Path,
    ttl_seconds: int = DEFAULT_IDENTITY_TTL_SECONDS,
) -> Path:
    identity_dir = Path(identity_dir)
    identity_dir.mkdir(parents=True, exist_ok=True)

    now = time.time()
    record = {
        "ts": now,
        "expires_at": now + ttl_seconds,
        "message_id": event.message_id,
        "session_id": session_id,
        "session_key": session_key,
        "chat_type": event.chat_type,
        "group_id": event.group_id,
        "user_id": sender.user_id,
        "nickname": sender.nickname,
        "role": sender.role,
        "is_owner": sender.is_owner,
        "permission": "owner" if sender.is_owner else sender.permission,
        "risk": risk.get("risk"),
    }

    path = identity_dir / "session_identity.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return path
