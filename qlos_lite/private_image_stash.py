from __future__ import annotations

import json
import time
from pathlib import Path


DEFAULT_TTL_SECONDS = 15 * 60
_IMAGE_ONLY_TEXT = {"[image]", "[图片]"}


def is_private_image_only(event) -> bool:
    return (
        str(getattr(event, "chat_type", "")) == "private"
        and str(getattr(event, "text", "")).strip().lower() in _IMAGE_ONLY_TEXT
        and any(str(item).startswith("image:") for item in (getattr(event, "attachments", None) or []))
    )


def stage_private_images(identity_dir: str | Path, user_id: str, attachments: list[str], now: float | None = None) -> None:
    timestamp = time.time() if now is None else float(now)
    payload = _read_payload(identity_dir)
    _drop_expired(payload, timestamp)
    payload["items"][str(user_id)] = {"attachments": list(attachments), "saved_at": timestamp}
    _write_payload(identity_dir, payload)


def consume_private_images(
    identity_dir: str | Path,
    user_id: str,
    now: float | None = None,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
) -> list[str]:
    timestamp = time.time() if now is None else float(now)
    payload = _read_payload(identity_dir)
    _drop_expired(payload, timestamp, ttl_seconds)
    item = payload["items"].pop(str(user_id), None)
    _write_payload(identity_dir, payload)
    if not isinstance(item, dict):
        return []
    return [str(value) for value in item.get("attachments") or [] if str(value).strip()]


def _path(identity_dir: str | Path) -> Path:
    return Path(identity_dir) / "private_image_stash.json"


def _read_payload(identity_dir: str | Path) -> dict[str, object]:
    path = _path(identity_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raw = {}
    items = raw.get("items") if isinstance(raw, dict) else None
    return {"version": 1, "items": dict(items) if isinstance(items, dict) else {}}


def _write_payload(identity_dir: str | Path, payload: dict[str, object]) -> None:
    path = _path(identity_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def _drop_expired(payload: dict[str, object], now: float, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
    items = payload["items"]
    if not isinstance(items, dict):
        payload["items"] = {}
        return
    for user_id, item in list(items.items()):
        saved_at = float(item.get("saved_at") or 0) if isinstance(item, dict) else 0
        if saved_at <= 0 or now - saved_at > ttl_seconds:
            items.pop(user_id, None)
