import json

from qlos_lite.hermes_client import HermesClient, build_session_id, build_session_key
from qlos_lite.models import QQMessageEvent, SenderContext


class FakeResponse:
    def __init__(self, body=None, lines=None):
        self.body = body or {"choices": [{"message": {"content": "ok"}}]}
        self.lines = lines or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")

    def __iter__(self):
        return iter(self.lines)


def test_hermes_client_sends_session_id_and_session_key_headers(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    reply = HermesClient("http://127.0.0.1:8642/v1/chat/completions", "secret", timeout=12, stream=False).chat(
        [{"role": "user", "content": "hello"}],
        session_key="qlos:qq:dm:1000000001",
        session_id="qlos-qq-dm-1000000001",
    )

    assert reply == "ok"
    assert captured["headers"]["X-hermes-session-key"] == "qlos:qq:dm:1000000001"
    assert captured["headers"]["X-hermes-session-id"] == "qlos-qq-dm-1000000001"
    assert captured["timeout"] == 12


def test_hermes_client_collects_streamed_assistant_content(monkeypatch):
    lines = [
        b'data: {"choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"first"},"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"delta":{"content":" second"},"finish_reason":null}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(lines=lines)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    reply = HermesClient("http://127.0.0.1:8642/v1/chat/completions", "secret").chat(
        [{"role": "user", "content": "hello"}]
    )

    assert captured["payload"]["stream"] is True
    assert reply == "first second"


def test_hermes_client_emits_tool_progress_stream_events(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"content":"先答一段。"},"finish_reason":null}]}\n\n'.encode("utf-8"),
        b"event: hermes.tool.progress\n",
        b'data: {"name":"terminal","phase":"start"}\n\n',
        'data: {"choices":[{"delta":{"content":"最终回答。"},"finish_reason":null}]}\n\n'.encode("utf-8"),
        b"data: [DONE]\n\n",
    ]
    events = []

    def fake_urlopen(request, timeout):
        return FakeResponse(lines=lines)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    reply = HermesClient("http://127.0.0.1:8642/v1/chat/completions", "secret").chat(
        [{"role": "user", "content": "hello"}],
        on_stream_event=events.append,
    )

    assert reply == "先答一段。最终回答。"
    assert events == [
        {"type": "content", "text": "先答一段。"},
        {"type": "tool_progress", "payload": {"name": "terminal", "phase": "start"}},
        {"type": "content", "text": "最终回答。"},
    ]


def test_hermes_client_can_use_non_streaming_mode(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        captured["stream"] = payload["stream"]
        return FakeResponse(body={"choices": [{"message": {"content": "fallback ok"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    reply = HermesClient("http://127.0.0.1:8642/v1/chat/completions", "secret", stream=False).chat(
        [{"role": "user", "content": "hello"}]
    )

    assert captured["stream"] is False
    assert reply == "fallback ok"


def test_build_session_id_matches_qq_conversation_scope():
    sender = SenderContext(
        user_id="1000000001",
        nickname=None,
        role="owner",
        is_owner=True,
        permission="owner",
    )
    private_event = QQMessageEvent(
        message_id="m1",
        chat_type="private",
        user_id="1000000001",
        nickname=None,
        raw_message="hello",
        text="hello",
    )
    group_event = QQMessageEvent(
        message_id="m2",
        chat_type="group",
        group_id="2000000001",
        user_id="1000000001",
        nickname=None,
        raw_message="hello",
        text="hello",
    )

    assert build_session_id(private_event, sender) == "qlos-qq-dm-1000000001"
    assert build_session_key(private_event, sender) == "qlos:qq:dm:1000000001"
    assert build_session_id(group_event, sender) == "qlos-qq-group-2000000001-user-1000000001"
    assert build_session_key(group_event, sender) == "qlos:qq:group:2000000001:user:1000000001"

