from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .models import QQMessageEvent


def normalize_attachments(attachments: list[str] | None) -> list[str]:
    return [item for item in (attachments or []) if item]


def _parse_attachment(item: str) -> tuple[str, str, dict[str, str]] | None:
    kind, sep, value = str(item).partition(":")
    if not sep or not kind or not value:
        return None
    parts = [part.strip() for part in value.split(" | ") if part.strip()]
    original = parts[0] if parts else value.strip()
    meta: dict[str, str] = {}
    for part in parts[1:]:
        key, meta_sep, meta_value = part.partition("=")
        if meta_sep and key.strip():
            meta[key.strip()] = meta_value.strip()
    return kind.strip(), original, meta


def _stable_ref(kind: str, original: str) -> str:
    digest = hashlib.sha256(f"{kind}:{original}".encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{kind}:qlos-media:{digest}"


def _safe_user_folder(user_id: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_-]+", "_", str(user_id or "").strip())
    return value or "unknown"


def _safe_filename(name: str, fallback: str) -> str:
    value = urllib.parse.unquote(str(name or "")).replace("\\", "/").split("/")[-1].strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" .")
    return value or fallback


def _filename_for(kind: str, original: str, meta: dict[str, str]) -> str:
    explicit = meta.get("name") or meta.get("filename") or meta.get("file_name")
    if explicit:
        return _safe_filename(explicit, _fallback_filename(kind, original))
    parsed = urllib.parse.urlparse(original)
    if parsed.scheme in {"http", "https", "file"}:
        return _safe_filename(Path(parsed.path).name, _fallback_filename(kind, original))
    return _safe_filename(Path(original).name, _fallback_filename(kind, original))


def _fallback_filename(kind: str, original: str) -> str:
    digest = hashlib.sha256(str(original).encode("utf-8", errors="replace")).hexdigest()[:12]
    suffix = ".png" if kind == "image" else ".bin"
    return f"{kind}-{digest}{suffix}"


def _unique_path(folder: Path, filename: str) -> Path:
    candidate = folder / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2
    while True:
        candidate = folder / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _copy_or_download(original: str, target: Path) -> None:
    parsed = urllib.parse.urlparse(original)
    if parsed.scheme in {"http", "https"}:
        with urllib.request.urlopen(original, timeout=30) as response:
            with target.open("wb") as handle:
                shutil.copyfileobj(response, handle)
        return
    if parsed.scheme == "file":
        source = Path(urllib.request.url2pathname(parsed.path))
        shutil.copy2(source, target)
        return
    source = Path(original)
    if source.exists():
        shutil.copy2(source, target)
        return
    raise FileNotFoundError(original)


def _relative_ref(media_path: Path, user_folder: str, filename: str) -> str:
    return f"{media_path.name}/{user_folder}/{filename}".replace("\\", "/")


def _resolve_onebot_file(original: str, meta: dict[str, str], resolve_file: Callable[[str], dict[str, Any] | None] | None) -> tuple[str, dict[str, str]]:
    file_id = str(meta.get("file_id") or "").strip()
    if not file_id or resolve_file is None:
        return original, meta
    resolved = resolve_file(file_id) or {}
    if not isinstance(resolved, dict):
        return original, meta
    value = str(
        resolved.get("path")
        or resolved.get("url")
        or resolved.get("file")
        or resolved.get("download_url")
        or original
    ).strip()
    merged = dict(meta)
    name = str(resolved.get("name") or resolved.get("file_name") or resolved.get("filename") or "").strip()
    if name and not (merged.get("name") or merged.get("file_name") or merged.get("filename")):
        merged["name"] = name
    return value or original, merged


def prepare_attachments(
    event: QQMessageEvent,
    media_dir: str | Path,
    resolve_file: Callable[[str], dict[str, Any] | None] | None = None,
) -> list[str]:
    media_path = Path(media_dir)
    media_path.mkdir(parents=True, exist_ok=True)
    refs: list[str] = []
    rows: list[dict[str, object]] = []
    user_folder = _safe_user_folder(event.user_id)
    user_path = media_path / user_folder
    user_path.mkdir(parents=True, exist_ok=True)
    for item in normalize_attachments(event.attachments):
        parsed = _parse_attachment(item)
        if not parsed:
            continue
        kind, original, meta = parsed
        resolved_original, resolved_meta = _resolve_onebot_file(original, meta, resolve_file)
        ref = _stable_ref(kind, original)
        row: dict[str, object] = {
            "ts": time.time(),
            "message_id": event.message_id,
            "chat_type": event.chat_type,
            "group_id": event.group_id,
            "user_id": event.user_id,
            "kind": kind,
            "original": original,
            "resolved_original": resolved_original,
            "ref": ref,
        }
        try:
            filename = _filename_for(kind, resolved_original, resolved_meta)
            stored_path = _unique_path(user_path, filename)
            _copy_or_download(resolved_original, stored_path)
            relative_path = _relative_ref(media_path, user_folder, stored_path.name)
            refs.append(f"{kind}:{stored_path} | relative={relative_path} | original={original}")
            row.update(
                {
                    "stored_path": str(stored_path),
                    "relative_path": relative_path,
                    "filename": stored_path.name,
                }
            )
        except Exception as exc:
            refs.append(f"{kind}:{original}")
            row.update({"error_type": type(exc).__name__, "error": str(exc)})
        rows.append(
            row
        )
    if rows:
        with (media_path / "index.jsonl").open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return refs
