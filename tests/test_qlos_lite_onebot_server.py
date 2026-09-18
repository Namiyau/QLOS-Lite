from email.message import Message
from io import BytesIO
import hashlib
import hmac
import json
import threading
import time
import urllib.request
from http.server import HTTPServer

from qlos_lite.config import QLOSLiteConfig
from qlos_lite.onebot_server import (
    _authorized,
    _claim_and_process_queue,
    _read_request_body,
    make_onebot_handler,
    parse_onebot_event,
    process_onebot_payload,
)
from qlos_lite.queue import MessageQueue


def _headers(**items):
    headers = Message()
    for key, value in items.items():
        headers[key.replace("_", "-")] = value
    return headers


def test_authorized_accepts_napcat_token_header_variants():
    token = "secret"

    assert _authorized(_headers(Authorization="Token secret"), token)
    assert _authorized(_headers(Authorization="token secret"), token)
    assert _authorized(_headers(X_Access_Token="secret"), token)


def test_authorized_rejects_wrong_token():
    assert not _authorized(_headers(Authorization="Token wrong"), "secret")


def test_authorized_accepts_napcat_sha1_signature():
    body = b'{"post_type":"message"}'
    signature = "sha1=" + hmac.new(b"secret", body, hashlib.sha1).hexdigest()

    assert _authorized(_headers(X_Signature=signature), "secret", body=body)


def test_read_request_body_supports_chunked_transfer_encoding():
    headers = _headers(Transfer_Encoding="chunked")
    body = b'{"post_type":"message"}'
    rfile = BytesIO(f"{len(body):X}\r\n".encode("ascii") + body + b"\r\n0\r\n\r\n")

    assert _read_request_body(headers, rfile) == body


def test_parse_onebot_event_unwraps_napcat_array_msg():
    event = parse_onebot_event(
        {
            "stringMsg": {"post_type": "message", "message_type": "private", "raw_message": "ignored"},
            "arrayMsg": {
                "self_id": 1000000002,
                "post_type": "message",
                "message_type": "private",
                "user_id": 1000000001,
                "message_id": 801,
                "raw_message": "你好呀？",
                "message": [{"type": "text", "data": {"text": "你好呀？"}}],
                "sender": {"nickname": "Stayin' Alive"},
            },
        },
        "1000000002",
    )

    assert event is not None
    assert event.chat_type == "private"
    assert event.user_id == "1000000001"
    assert event.message_id == "801"
    assert event.text == "你好呀？"


def test_parse_onebot_event_unwraps_napcat_group_at_array_msg():
    event = parse_onebot_event(
        {
            "arrayMsg": {
                "self_id": 1000000002,
                "post_type": "message",
                "message_type": "group",
                "group_id": 2000000001,
                "user_id": 1000000001,
                "message_id": 86,
                "raw_message": "[CQ:at,qq=1000000002] 你好",
                "message": [
                    {"type": "at", "data": {"qq": "1000000002"}},
                    {"type": "text", "data": {"text": " 你好"}},
                ],
                "sender": {"nickname": "Stayin' Alive"},
            },
        },
        "1000000002",
    )

    assert event is not None
    assert event.chat_type == "group"
    assert event.group_id == "2000000001"
    assert event.is_at_bot is True
    assert event.text == "你好"


def test_parse_onebot_event_detects_textual_bot_mention():
    event = parse_onebot_event(
        {
            "arrayMsg": {
                "self_id": 1000000002,
                "post_type": "message",
                "message_type": "group",
                "group_id": 2000000001,
                "user_id": 1000000001,
                "message_id": 87,
                "raw_message": "@Memory° 你好呀？",
                "message": [{"type": "text", "data": {"text": "@Memory° 你好呀？"}}],
                "sender": {"nickname": "Stayin' Alive"},
            },
        },
        "1000000002",
        bot_names=["Memory°", "Memory掳"],
    )

    assert event is not None
    assert event.is_at_bot is True
    assert event.text == "你好呀？"


def test_parse_onebot_event_uses_readable_voice_placeholder_without_url():
    event = parse_onebot_event(
        {
            "post_type": "message",
            "message_type": "private",
            "user_id": 1000000001,
            "message_id": 809,
            "message": [{"type": "record", "data": {}}],
            "sender": {"nickname": "Stayin' Alive"},
        },
        "1000000002",
    )

    assert event is not None
    assert event.text == "[语音消息]"


def test_parse_onebot_event_keeps_image_attachment_url_with_type():
    event = parse_onebot_event(
        {
            "post_type": "message",
            "message_type": "private",
            "user_id": 1000000001,
            "message_id": 810,
            "message": [{"type": "image", "data": {"url": "https://example.com/pic.png"}}],
            "sender": {"nickname": "Stayin' Alive"},
        },
        "1000000002",
    )

    assert event is not None
    assert event.text == "[image]"
    assert event.attachments == ["image:https://example.com/pic.png"]


def test_parse_onebot_event_keeps_file_attachment_url_with_type():
    event = parse_onebot_event(
        {
            "post_type": "message",
            "message_type": "private",
            "user_id": 1000000001,
            "message_id": 811,
            "message": [{"type": "file", "data": {"url": "https://example.com/report.pdf"}}],
            "sender": {"nickname": "Stayin' Alive"},
        },
        "1000000002",
    )

    assert event is not None
    assert event.text == "[file]"
    assert event.attachments == ["file:https://example.com/report.pdf"]


def test_parse_onebot_event_keeps_file_id_and_name_for_later_download():
    event = parse_onebot_event(
        {
            "post_type": "message",
            "message_type": "private",
            "user_id": 1000000001,
            "message_id": 812,
            "message": [
                {
                    "type": "file",
                    "data": {"file": "报告.docx", "file_id": "file-abc", "file_name": "报告.docx"},
                }
            ],
            "sender": {"nickname": "Stayin' Alive"},
        },
        "1000000002",
    )

    assert event is not None
    assert event.text == "[file]"
    assert event.attachments == ["file:报告.docx | file_id=file-abc | name=报告.docx"]


def test_parse_onebot_event_treats_any_leading_at_text_as_group_mention():
    event = parse_onebot_event(
        {
            "arrayMsg": {
                "self_id": 1000000002,
                "post_type": "message",
                "message_type": "group",
                "group_id": 2000000001,
                "user_id": 1000000001,
                "message_id": 88,
                "raw_message": "@SomeBot 你好呀？",
                "message": [{"type": "text", "data": {"text": "@SomeBot 你好呀？"}}],
                "sender": {"nickname": "Stayin' Alive"},
            },
        },
        "1000000002",
        bot_names=[],
    )

    assert event is not None
    assert event.is_at_bot is True
    assert event.text == "你好呀？"


def test_parse_onebot_event_finds_message_inside_unknown_wrapper():
    event = parse_onebot_event(
        {
            "meta": {"source": "napcat"},
            "payload": {
                "event": {
                    "post_type": "message",
                    "message_type": "private",
                    "user_id": 1000000001,
                    "message_id": 807,
                    "raw_message": "你好呀？",
                    "message": [{"type": "text", "data": {"text": "你好呀？"}}],
                    "sender": {"nickname": "Stayin' Alive"},
                }
            },
        },
        "1000000002",
    )

    assert event is not None
    assert event.message_id == "807"
    assert event.text == "你好呀？"


def test_http_handler_acks_before_processing_finishes(monkeypatch, tmp_path):
    started = threading.Event()
    release = threading.Event()

    def slow_process(payload, config=None):
        started.set()
        release.wait(timeout=2)
        return {"ok": True}

    monkeypatch.setattr("qlos_lite.onebot_server.process_onebot_payload", slow_process)
    config = QLOSLiteConfig(
        owner_qq_id="1",
        onebot_inbound_token="secret",
        log_dir=tmp_path / "logs",
        queue_dir=tmp_path / "queue",
    )
    server = HTTPServer(("127.0.0.1", 0), make_onebot_handler(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/",
            data=json.dumps(
                {
                    "post_type": "message",
                    "message_type": "private",
                    "message_id": "queued-message",
                    "user_id": "1",
                    "raw_message": "hello",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Token secret"},
            method="POST",
        )
        before = time.monotonic()
        with urllib.request.urlopen(request, timeout=1) as response:
            body = json.loads(response.read().decode("utf-8"))
        elapsed = time.monotonic() - before
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert started.wait(timeout=1)
    assert body == {"ok": True}
    assert elapsed < 0.5


def test_http_handler_does_not_start_a_queue_worker_for_input_status_notice(monkeypatch, tmp_path):
    worker_started = threading.Event()

    def worker(config):
        worker_started.set()

    monkeypatch.setattr("qlos_lite.onebot_server._claim_and_process_queue", worker)
    config = QLOSLiteConfig(
        owner_qq_id="1",
        onebot_inbound_token="secret",
        log_dir=tmp_path / "logs",
        queue_dir=tmp_path / "queue",
    )
    server = HTTPServer(("127.0.0.1", 0), make_onebot_handler(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/",
            data=json.dumps({"post_type": "notice", "notice_type": "notify", "sub_type": "input_status"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Token secret"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=1) as response:
            body = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert body == {"ok": True, "ignored": True}
    assert not worker_started.wait(timeout=0.1)


def test_queue_worker_does_not_reclaim_a_long_running_item(monkeypatch, tmp_path):
    config = QLOSLiteConfig(
        owner_qq_id="1",
        queue_dir=tmp_path / "queue",
        queue_stale_after_seconds=0,
    )
    queue = MessageQueue(config.queue_dir)
    assert queue.enqueue("long-running", {"post_type": "message", "message_id": "long-running"})
    started = threading.Event()
    release = threading.Event()
    calls = []

    def slow_process(payload, config=None):
        calls.append(payload)
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr("qlos_lite.onebot_server.process_onebot_payload", slow_process)
    first = threading.Thread(target=_claim_and_process_queue, args=(config,), daemon=True)
    second = threading.Thread(target=_claim_and_process_queue, args=(config,), daemon=True)
    first.start()
    assert started.wait(timeout=1)
    second.start()
    time.sleep(0.1)
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert len(calls) == 1


def test_process_onebot_payload_logs_ignored_payload(tmp_path):
    config = QLOSLiteConfig(owner_qq_id="1", log_dir=tmp_path / "logs", queue_dir=tmp_path / "queue")

    result = process_onebot_payload({"post_type": "notice", "notice_type": "input_status"}, config)

    assert result == {"ok": True, "ignored": True}
    gateway_log = (tmp_path / "logs" / "gateway.jsonl").read_text(encoding="utf-8")
    assert '"event":"ignored"' in gateway_log
    assert '"post_type":"notice"' in gateway_log

