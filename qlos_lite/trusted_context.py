"""Authenticated, hash-only QQ context for the Hermi memory bridge."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any


CONTEXT_VERSION = 1
DEFAULT_TTL_SECONDS = 15 * 60


def build_trusted_context(
    event: Any,
    sender: Any,
    session_id: str,
    session_key: str,
    signing_key: str,
    *,
    now: int | float | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any] | None:
    """Return a signed context without raw QQ or session identifiers."""
    if not str(signing_key or "").strip() or not str(getattr(event, "user_id", "") or "").strip():
        return None
    issued_at = int(time.time() if now is None else now)
    key = str(signing_key).encode("utf-8")
    payload: dict[str, Any] = {
        "version": CONTEXT_VERSION,
        "platform": "qq",
        "chat_type": str(getattr(event, "chat_type", "") or ""),
        "subject_id_hash": _bound_hash(key, f"qq:user:{getattr(event, 'user_id', '')}"),
        "group_id_hash": _bound_hash(key, f"qq:group:{getattr(event, 'group_id', '')}")
        if str(getattr(event, "group_id", "") or "").strip()
        else "",
        "is_owner": bool(getattr(sender, "is_owner", False)),
        "sender_role": str(getattr(sender, "role", "") or ""),
        "session_id_hash": _bound_hash(key, f"session:id:{session_id}"),
        "session_key_hash": _bound_hash(key, f"session:key:{session_key}"),
        "issued_at": issued_at,
        "expires_at": issued_at + max(1, int(ttl_seconds)),
    }
    payload["nonce"] = _bound_hash(key, f"nonce:{getattr(event, 'message_id', '')}:{issued_at}")
    payload["signature"] = _sign(payload, key)
    return payload


def verify_trusted_context(
    context: Any,
    signing_key: str,
    session_id: str,
    session_key: str,
    *,
    now: int | float | None = None,
) -> dict[str, Any] | None:
    """Verify an untrusted transport payload and return a safe copy or None."""
    if not isinstance(context, dict) or not str(signing_key or "").strip():
        return None
    key = str(signing_key).encode("utf-8")
    signature = str(context.get("signature") or "")
    payload = {name: value for name, value in context.items() if name != "signature"}
    if not signature or not hmac.compare_digest(signature, _sign(payload, key)):
        return None
    current = int(time.time() if now is None else now)
    if payload.get("version") != CONTEXT_VERSION or payload.get("platform") != "qq":
        return None
    if not isinstance(payload.get("issued_at"), int) or not isinstance(payload.get("expires_at"), int):
        return None
    if payload["expires_at"] <= current or payload["issued_at"] > current + 60:
        return None
    if not hmac.compare_digest(str(payload.get("session_id_hash") or ""), _bound_hash(key, f"session:id:{session_id}")):
        return None
    if not hmac.compare_digest(str(payload.get("session_key_hash") or ""), _bound_hash(key, f"session:key:{session_key}")):
        return None
    if not str(payload.get("subject_id_hash") or "").strip():
        return None
    if payload.get("chat_type") not in {"private", "group"}:
        return None
    if payload["chat_type"] == "group" and not str(payload.get("group_id_hash") or "").strip():
        return None
    if bool(payload.get("is_owner")) != (str(payload.get("sender_role") or "") == "owner"):
        return None
    return dict(payload)


def _bound_hash(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _sign(payload: dict[str, Any], key: bytes) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, encoded, hashlib.sha256).hexdigest()
