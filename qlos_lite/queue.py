from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class QueueItem:
    message_id: str
    payload: dict[str, Any]
    path: Path


_recent_ids: dict[str, float] = {}
_RECENT_TTL = 5.0


def _seen_id(message_id: str) -> bool:
    """In-memory dedup to close the TOCTOU window in enqueue()."""
    now = time.time()
    seen = _recent_ids.get(message_id)
    if seen is not None and now - seen < _RECENT_TTL:
        return True
    _recent_ids[message_id] = now
    if len(_recent_ids) > 10_000:
        stale = [k for k, v in _recent_ids.items() if now - v >= _RECENT_TTL]
        for k in stale:
            _recent_ids.pop(k, None)
    return False


class MessageQueue:
    def __init__(self, queue_dir: str | Path):
        self.queue_dir = Path(queue_dir)
        self.pending_dir = self.queue_dir / "pending"
        self.processing_dir = self.queue_dir / "processing"
        self.done_dir = self.queue_dir / "done"
        self.failed_dir = self.queue_dir / "failed"

    def _ensure(self) -> None:
        for path in (self.pending_dir, self.processing_dir, self.done_dir, self.failed_dir):
            path.mkdir(parents=True, exist_ok=True)

    def _path(self, directory: Path, message_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(message_id)) or "unknown"
        return directory / f"{safe}.json"

    def enqueue(self, message_id: str, payload: dict[str, Any]) -> bool:
        self._ensure()
        message_id = str(message_id or payload.get("message_id") or payload.get("id") or "")
        if not message_id:
            message_id = str(int(time.time() * 1000))
        if _seen_id(message_id):
            return False
        for directory in (self.pending_dir, self.processing_dir, self.done_dir):
            if self._path(directory, message_id).exists():
                return False
        path = self._path(self.pending_dir, message_id)
        path.write_text(
            json.dumps({"message_id": message_id, "ts": time.time(), "payload": payload}, ensure_ascii=False),
            encoding="utf-8",
        )
        return True

    def claim_next(self, stale_after_seconds: float = 120) -> QueueItem | None:
        self._ensure()
        now = time.time()
        for path in sorted(self.processing_dir.glob("*.json"), key=lambda item: item.stat().st_mtime):
            if now - path.stat().st_mtime >= stale_after_seconds:
                return self._load_item(path)
        pending = sorted(self.pending_dir.glob("*.json"), key=lambda item: item.stat().st_mtime)
        if not pending:
            return None
        path = pending[0]
        target = self.processing_dir / path.name
        path.replace(target)
        return self._load_item(target)

    def _load_item(self, path: Path) -> QueueItem | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            path.replace(self.failed_dir / path.name)
            return None
        return QueueItem(str(data.get("message_id") or path.stem), dict(data.get("payload") or {}), path)

    def mark_done(self, message_id: str) -> None:
        self._ensure()
        for directory in (self.processing_dir, self.pending_dir):
            path = self._path(directory, message_id)
            if path.exists():
                path.replace(self._path(self.done_dir, message_id))
                return

    def mark_failed(self, message_id: str, error: str) -> None:
        self._ensure()
        path = self._path(self.processing_dir, message_id)
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        data["error"] = error
        failed = self._path(self.failed_dir, message_id)
        failed.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        path.unlink(missing_ok=True)
