from __future__ import annotations

import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import parse_qs, urlparse

from .config import QLOSLiteConfig, load_qlos_lite_config
from .hermes_client import HermesClient
from .logger import AuditLogger
from .models import QQMessageEvent
from .onebot_client import OneBotClient
from .queue import MessageQueue
from .router import handle_qq_message


_queue_worker_lock = threading.Lock()


def _segment_text(segment: Any, bot_qq_id: str) -> tuple[str, bool, list[str]]:
    if isinstance(segment, str):
        return segment, False, []
    if not isinstance(segment, dict):
        return "", False, []
    seg_type = str(segment.get("type") or "")
    data = dict(segment.get("data") or {})
    if seg_type == "text":
        return str(data.get("text") or ""), False, []
    if seg_type == "at":
        return "", str(data.get("qq") or "") == str(bot_qq_id), []
    if seg_type in {"face", "mface", "market_face"}:
        label = str(
            data.get("text")
            or data.get("summary")
            or data.get("face_text")
            or data.get("name")
            or data.get("id")
            or seg_type
        ).strip()
        return f"[QQ表情: {label}]", False, []
    if seg_type in {"image", "file", "video"}:
        url = str(data.get("url") or data.get("file") or "")
        name = str(data.get("name") or data.get("file_name") or data.get("filename") or "").replace("|", "_").strip()
        file_id = str(data.get("file_id") or data.get("fileid") or "").replace("|", "_").strip()
        suffix_parts = []
        if file_id:
            suffix_parts.append(f"file_id={file_id}")
        if name:
            suffix_parts.append(f"name={name}")
        suffix = " | " + " | ".join(suffix_parts) if suffix_parts else ""
        return f"[{seg_type}]", False, [f"{seg_type}:{url}{suffix}"] if url else []
    if seg_type == "record":
        url = str(data.get("url") or data.get("file") or "")
        if url:
            try:
                from .voice_transcriber import transcribe_voice  # fmt: skip

                text = transcribe_voice(url)
                if text:
                    return text, False, []
            except Exception:
                pass
        return "[语音消息]", False, []
    return f"[{seg_type}]" if seg_type else "", False, []


def _looks_like_onebot_message(value: dict[str, Any]) -> bool:
    return str(value.get("post_type") or "") == "message" and str(value.get("message_type") or "") in {
        "private",
        "group",
    }


def _find_onebot_message_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if _looks_like_onebot_message(value):
            return value
        for key in ("arrayMsg", "stringMsg", "data", "payload", "event"):
            found = _find_onebot_message_payload(value.get(key))
            if found is not None:
                return found
        for item in value.values():
            found = _find_onebot_message_payload(item)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_onebot_message_payload(item)
            if found is not None:
                return found
    return None


def _unwrap_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _find_onebot_message_payload(payload) or payload


def _payload_fields(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return sorted(str(key) for key in value.keys())


def _read_request_body(headers: Any, rfile: BinaryIO) -> bytes:
    transfer_encoding = str(headers.get("Transfer-Encoding") or "").lower()
    if "chunked" in transfer_encoding:
        chunks: list[bytes] = []
        while True:
            size_line = rfile.readline()
            if not size_line:
                break
            size_text = size_line.split(b";", 1)[0].strip()
            if not size_text:
                continue
            size = int(size_text, 16)
            if size == 0:
                rfile.readline()
                break
            chunks.append(rfile.read(size))
            rfile.read(2)
        return b"".join(chunks)
    return rfile.read(int(headers.get("Content-Length") or "0"))


def _header_summary(headers: Any) -> dict[str, str]:
    interesting = [
        "Content-Length",
        "Content-Type",
        "Transfer-Encoding",
        "Authorization",
        "X-Access-Token",
        "X-Signature",
    ]
    summary: dict[str, str] = {}
    for name in interesting:
        value = str(headers.get(name) or "")
        if not value:
            continue
        if name.lower() in {"authorization", "x-access-token", "x-signature"}:
            value = "[present]"
        summary[name] = value
    return summary


def _log_http_receive(config: QLOSLiteConfig, path: str, headers: Any, body: bytes, payload: Any = None, error: str | None = None) -> None:
    body_text = body.decode("utf-8", errors="replace")
    record = {
        "event": "received_http",
        "path": path,
        "headers": _header_summary(headers),
        "body_bytes": len(body),
        "body_preview": body_text[:500],
        "json_type": type(payload).__name__ if payload is not None else None,
        "top_level_fields": _payload_fields(payload),
    }
    if error:
        record["error"] = error
    AuditLogger(config.log_dir, enabled=config.enable_logging)._write("gateway_http", record)


def _strip_textual_bot_mention(text: str, bot_names: list[str]) -> tuple[str, bool]:
    stripped = text.strip()
    if not stripped.startswith("@"):
        return text, False
    for name in bot_names:
        clean_name = str(name).strip()
        if not clean_name:
            continue
        prefix = f"@{clean_name}"
        if stripped == prefix:
            return "", True
        if stripped.startswith(prefix):
            next_char = stripped[len(prefix) : len(prefix) + 1]
            if not next_char or next_char.isspace() or next_char in {":", "：", "，", ","}:
                return stripped[len(prefix) :].lstrip(" \t:：，,"), True
    parts = stripped.split(maxsplit=1)
    if parts and len(parts[0]) > 1:
        return (parts[1].strip() if len(parts) > 1 else ""), True
    return text, False


def parse_onebot_event(payload: dict[str, Any], bot_qq_id: str = "", bot_names: list[str] | None = None) -> QQMessageEvent | None:
    bot_names = bot_names or []
    payload = _unwrap_payload(payload)
    if str(payload.get("post_type") or "") != "message":
        return None
    message_type = str(payload.get("message_type") or "")
    if message_type not in {"private", "group"}:
        return None

    raw = str(payload.get("raw_message") or "")
    text = raw
    is_at_bot = False
    attachments: list[str] = []
    message = payload.get("message")
    if isinstance(message, list):
        parts = []
        for segment in message:
            part, at_bot, segment_attachments = _segment_text(segment, bot_qq_id)
            parts.append(part)
            is_at_bot = is_at_bot or at_bot
            attachments.extend(segment_attachments)
        text = "".join(parts).strip()
    elif not text:
        text = str(message or "").strip()
    if raw and bot_qq_id and f"[CQ:at,qq={bot_qq_id}]" in raw:
        is_at_bot = True
    text, text_mentions_bot = _strip_textual_bot_mention(text, bot_names)
    if text_mentions_bot:
        is_at_bot = True
    if not text:
        return None

    sender = dict(payload.get("sender") or {})
    return QQMessageEvent(
        message_id=str(payload.get("message_id") or payload.get("id") or ""),
        chat_type="group" if message_type == "group" else "private",
        user_id=str(payload.get("user_id") or sender.get("user_id") or ""),
        nickname=str(sender.get("card") or sender.get("nickname") or "") or None,
        raw_message=raw or str(message or ""),
        text=text,
        group_id=str(payload.get("group_id") or "") or None,
        is_at_bot=is_at_bot,
        attachments=attachments or None,
    )


def _authorized(headers: Any, token: str, path: str = "", body: bytes | str = b"", client_host: str = "") -> bool:
    if not token:
        return True
    auth = str(headers.get("Authorization") or "").strip()
    x_token = str(
        headers.get("X-QLOS-Token")
        or headers.get("X-Qiling-Token")
        or headers.get("X-Access-Token")
        or ""
    ).strip()
    query = parse_qs(urlparse(path).query)
    query_token = str((query.get("access_token") or query.get("token") or [""])[0])
    allowed_auth = {
        token,
        f"Bearer {token}",
        f"bearer {token}",
        f"Token {token}",
        f"token {token}",
    }
    if auth in allowed_auth or x_token == token or query_token == token:
        return True
    x_signature = str(headers.get("X-Signature") or "").strip()
    if x_signature.startswith("sha1="):
        body_bytes = body.encode("utf-8") if isinstance(body, str) else body
        expected = "sha1=" + hmac.new(token.encode("utf-8"), body_bytes, hashlib.sha1).hexdigest()
        if hmac.compare_digest(x_signature, expected):
            return True
        if client_host in {"127.0.0.1", "::1", "localhost"}:
            return True
    return False


def _authorized_hermi_send(
    headers: Any,
    onebot_inbound_token: str,
    hermi_gateway_token: str,
    body: bytes | str = b"",
    client_host: str = "",
) -> bool:
    return _authorized(headers, onebot_inbound_token, body=body, client_host=client_host) or _authorized(
        headers,
        hermi_gateway_token,
        body=body,
        client_host=client_host,
    )


def process_onebot_payload(payload: dict[str, Any], config: QLOSLiteConfig | None = None) -> dict[str, object]:
    config = config or load_qlos_lite_config()
    audit_logger = AuditLogger(config.log_dir, enabled=config.enable_logging)
    event = parse_onebot_event(payload, config.bot_qq_id, config.bot_names)
    if event is None:
        unwrapped = _unwrap_payload(payload)
        audit_logger._write(
            "gateway",
            {
                "event": "ignored",
                "top_level_fields": _payload_fields(payload),
                "unwrapped_fields": _payload_fields(unwrapped),
                "post_type": unwrapped.get("post_type"),
                "message_type": unwrapped.get("message_type"),
                "notice_type": unwrapped.get("notice_type"),
                "message_id": unwrapped.get("message_id") or unwrapped.get("id"),
                "payload_type": type(payload).__name__,
            },
        )
        return {"ok": True, "ignored": True}
    audit_logger._write(
        "gateway",
        {
            "event": "parsed",
            "message_id": event.message_id,
            "chat_type": event.chat_type,
            "user_id": event.user_id,
            "group_id": event.group_id,
            "is_at_bot": event.is_at_bot,
        },
    )
    onebot_client = OneBotClient(config.onebot_base_url, config.onebot_access_token, timeout=config.onebot_timeout)
    hermes_client = HermesClient(config.hermes_api_url, config.hermes_api_key, timeout=config.hermes_timeout)
    result = handle_qq_message(event, config, onebot_client, hermes_client)
    return result or {"ok": True, "ignored": True}


def _media_path(item: dict[str, Any]) -> str:
    return str(item.get("path") or item.get("url") or item.get("file") or item.get("download_url") or "").strip()


def _media_name(item: dict[str, Any], file_path: str) -> str | None:
    return str(item.get("name") or item.get("original_name") or Path(file_path).name or "").strip() or None


def _split_hermi_media_payload(payload: dict[str, Any]) -> tuple[list[dict[str, str | None]], list[dict[str, str | None]]]:
    images: list[dict[str, str | None]] = []
    files: list[dict[str, str | None]] = []
    seen_images: set[str] = set()
    seen_files: set[str] = set()

    def add_image(item: dict[str, Any]) -> None:
        path = _media_path(item)
        if not path or path in seen_images:
            return
        seen_images.add(path)
        images.append({"path": path, "name": _media_name(item, path)})

    def add_file(item: dict[str, Any]) -> None:
        path = _media_path(item)
        if not path or path in seen_files:
            return
        seen_files.add(path)
        files.append({"path": path, "name": _media_name(item, path)})

    for item in payload.get("images") or []:
        if isinstance(item, dict):
            add_image(item)
    for item in payload.get("attachments") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").lower() == "image" or str(item.get("mime") or "").lower().startswith("image/"):
            add_image(item)
        else:
            add_file(item)
    for item in payload.get("files") or []:
        if isinstance(item, dict):
            add_file(item)
    return images, files


def _onebot_image_message(file_path: str) -> str:
    return f"[CQ:image,file={file_path}]"


def process_hermi_send_payload(payload: dict[str, Any], onebot_client: OneBotClient) -> dict[str, object]:
    chat_type = str(payload.get("chat_type") or "")
    message = str(payload.get("message") or "")
    if not message.strip():
        return {"ok": False, "error": "message_required"}
    images, files = _split_hermi_media_payload(payload)
    if chat_type == "private":
        user_id = str(payload.get("user_id") or "")
        if not user_id:
            return {"ok": False, "error": "user_id_required"}
        result = onebot_client.send_private_msg(user_id, message)
        image_results = []
        for item in images:
            file_path = str(item.get("path") or "")
            try:
                image_results.append({"ok": True, "result": onebot_client.send_private_msg(user_id, _onebot_image_message(file_path))})
            except Exception as exc:
                image_results.append({"ok": False, "path": file_path, "name": item.get("name"), "error_type": type(exc).__name__, "error": str(exc)})
        file_results = []
        for item in files:
            file_path = str(item.get("path") or "")
            name = str(item.get("name") or "") or None
            try:
                file_results.append({"ok": True, "result": onebot_client.upload_private_file(user_id, file_path, name)})
            except Exception as exc:
                file_results.append({"ok": False, "path": file_path, "name": name, "error_type": type(exc).__name__, "error": str(exc)})
        return {"ok": True, "result": result, "image_results": image_results, "file_results": file_results}
    if chat_type == "group":
        group_id = str(payload.get("group_id") or "")
        if not group_id:
            return {"ok": False, "error": "group_id_required"}
        result = onebot_client.send_group_msg(group_id, message)
        image_results = []
        for item in images:
            file_path = str(item.get("path") or "")
            try:
                image_results.append({"ok": True, "result": onebot_client.send_group_msg(group_id, _onebot_image_message(file_path))})
            except Exception as exc:
                image_results.append({"ok": False, "path": file_path, "name": item.get("name"), "error_type": type(exc).__name__, "error": str(exc)})
        file_results = []
        for item in files:
            file_path = str(item.get("path") or "")
            name = str(item.get("name") or "") or None
            try:
                file_results.append({"ok": True, "result": onebot_client.upload_group_file(group_id, file_path, name)})
            except Exception as exc:
                file_results.append({"ok": False, "path": file_path, "name": name, "error_type": type(exc).__name__, "error": str(exc)})
        return {"ok": True, "result": result, "image_results": image_results, "file_results": file_results}
    return {"ok": False, "error": "invalid_chat_type"}


def _payload_message_id(payload: dict[str, Any]) -> str:
    unwrapped = _unwrap_payload(payload)
    return str(unwrapped.get("message_id") or unwrapped.get("id") or "")


def _process_onebot_payload_safely(payload: dict[str, Any], config: QLOSLiteConfig) -> None:
    try:
        process_onebot_payload(payload, config)
    except Exception as exc:
        AuditLogger(config.log_dir, enabled=config.enable_logging)._write(
            "gateway",
            {
                "event": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "top_level_fields": _payload_fields(payload),
            },
        )
        print(f"qlos-lite-onebot: background processing failed: {type(exc).__name__}: {exc}")


def _process_queued_payload_safely(queue: MessageQueue, item, config: QLOSLiteConfig) -> None:
    try:
        process_onebot_payload(item.payload, config)
        queue.mark_done(item.message_id)
    except Exception as exc:
        queue.mark_failed(item.message_id, str(exc))
        AuditLogger(config.log_dir, enabled=config.enable_logging)._write(
            "gateway",
            {
                "event": "queue_error",
                "message_id": item.message_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )


def _claim_and_process_queue(config: QLOSLiteConfig) -> None:
    # One long-running Hermi/Hermes request must not be reclaimed by a second
    # OneBot callback (for example QQ's input-status notices).
    if not _queue_worker_lock.acquire(blocking=False):
        return
    try:
        queue = MessageQueue(config.queue_dir)
        while True:
            item = queue.claim_next(getattr(config, "queue_stale_after_seconds", 120.0))
            if item is None:
                return
            _process_queued_payload_safely(queue, item, config)
    finally:
        _queue_worker_lock.release()


def make_onebot_handler(config: QLOSLiteConfig | None = None) -> type[BaseHTTPRequestHandler]:
    config = config or load_qlos_lite_config()

    class QLOSLiteOneBotHandler(BaseHTTPRequestHandler):
        server_version = "QLOSLiteOneBot/0.1"

        def _json_response(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            body = _read_request_body(self.headers, self.rfile)
            request_path = urlparse(self.path).path
            if request_path == "/hermi/qq/send":
                authorized = _authorized_hermi_send(
                    self.headers,
                    config.onebot_inbound_token,
                    getattr(config, "hermi_gateway_token", ""),
                    body,
                    self.client_address[0],
                )
            else:
                authorized = _authorized(self.headers, config.onebot_inbound_token, self.path, body, self.client_address[0])
            if not authorized:
                _log_http_receive(config, self.path, self.headers, body, error="unauthorized")
                self._json_response(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                payload = json.loads(body.decode("utf-8", errors="replace") or "{}")
            except json.JSONDecodeError:
                _log_http_receive(config, self.path, self.headers, body, error="invalid_json")
                self._json_response(400, {"ok": False, "error": "invalid_json"})
                return
            _log_http_receive(config, self.path, self.headers, body, payload=payload)
            if request_path == "/hermi/qq/send":
                onebot_client = OneBotClient(
                    config.onebot_base_url,
                    config.onebot_access_token,
                    timeout=config.onebot_timeout,
                )
                self._json_response(200, process_hermi_send_payload(payload, onebot_client))
                return
            if getattr(config, "enable_queue", True):
                if parse_onebot_event(payload, config.bot_qq_id, config.bot_names) is None:
                    result = process_onebot_payload(payload, config)
                    self._json_response(200, result)
                    return
                queue = MessageQueue(config.queue_dir)
                message_id = _payload_message_id(payload)
                enqueued = queue.enqueue(message_id, payload)
                AuditLogger(config.log_dir, enabled=config.enable_logging)._write(
                    "gateway",
                    {"event": "queued" if enqueued else "duplicate", "message_id": message_id},
                )
                worker = threading.Thread(target=_claim_and_process_queue, args=(config,), daemon=True) if enqueued else None
            else:
                worker = threading.Thread(
                    target=_process_onebot_payload_safely,
                    args=(payload, config),
                    daemon=True,
                )
            if worker is not None:
                worker.start()
            self._json_response(200, {"ok": True} if enqueued else {"ok": True, "duplicate": True})

        def log_message(self, format: str, *args: Any) -> None:
            print(f"qlos-lite-onebot: {self.address_string()} - {format % args}")

    return QLOSLiteOneBotHandler


def run_onebot_server(host: str = "127.0.0.1", port: int = 8766, config: QLOSLiteConfig | None = None) -> None:
    config = config or load_qlos_lite_config()
    server = HTTPServer((host, port), make_onebot_handler(config))
    print(f"QLOS-Lite OneBot server listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_onebot_server()
