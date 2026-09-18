import json

from qlos_lite.hermes_runs_client import HermesRunsClient


class FakeResponse:
    def __init__(self, body=None, lines=None, status=200):
        self.body = body or {}
        self.lines = lines or []
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")

    def __iter__(self):
        return iter(self.lines)


def test_runs_client_starts_run_and_reads_completed_output(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/v1/runs"):
            payload = json.loads(request.data.decode("utf-8"))
            assert payload["session_id"] == "qlos-qq-dm-1000000001"
            assert payload["input"] == "hello"
            assert payload["instructions"] == "sys"
            return FakeResponse({"run_id": "run-1"}, status=202)
        if request.full_url.endswith("/v1/runs/run-1/events"):
            return FakeResponse(
                lines=[
                    b'data: {"type":"message.delta","delta":"hi"}\n\n',
                    b'data: {"type":"run.completed","output":"hi done"}\n\n',
                ]
            )
        raise AssertionError(request.full_url)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    reply = HermesRunsClient("http://127.0.0.1:8642/v1/chat/completions", "secret").chat_with_approval(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello"}],
        session_key="qlos:qq:dm:1000000001",
        session_id="qlos-qq-dm-1000000001",
        approval_handler=lambda _run_id, _event: "once",
    )

    assert reply == "hi done"
    assert requests[0].full_url == "http://127.0.0.1:8642/v1/runs"


def test_runs_client_preserves_multimodal_user_input(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/v1/runs"):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse({"run_id": "run-1"}, status=202)
        if request.full_url.endswith("/v1/runs/run-1/events"):
            return FakeResponse(lines=[b'data: {"type":"run.completed","output":"ok"}\n\n'])
        raise AssertionError(request.full_url)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    content = [
        {"type": "text", "text": "look"},
        {"type": "image_url", "image_url": {"url": "https://example.com/pic.png"}},
    ]
    reply = HermesRunsClient("http://127.0.0.1:8642/v1/chat/completions", "secret").chat_with_approval(
        [{"role": "user", "content": content}],
        session_key="qlos:qq:dm:1000000001",
        session_id="qlos-qq-dm-1000000001",
        approval_handler=lambda _run_id, _event: "once",
    )

    assert reply == "ok"
    assert captured["payload"]["input"] == [{"role": "user", "content": content}]


def test_runs_client_posts_approval_and_continues_stream(monkeypatch):
    approved = []
    events = []

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/v1/runs"):
            return FakeResponse({"run_id": "run-1"}, status=202)
        if request.full_url.endswith("/v1/runs/run-1/events"):
            return FakeResponse(
                lines=[
                    'data: {"type":"message.delta","delta":"先答。"}\n\n'.encode("utf-8"),
                    b'data: {"type":"approval.request","command":"echo hi"}\n\n',
                    'data: {"type":"message.delta","delta":"继续。"}\n\n'.encode("utf-8"),
                    'data: {"type":"run.completed","output":"先答。继续。"}\n\n'.encode("utf-8"),
                ]
            )
        if request.full_url.endswith("/v1/runs/run-1/approval"):
            approved.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse({"ok": True})
        raise AssertionError(request.full_url)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    reply = HermesRunsClient("http://127.0.0.1:8642/v1/chat/completions", "secret").chat_with_approval(
        [{"role": "user", "content": "run tool"}],
        session_key="qlos:qq:dm:1000000001",
        session_id="qlos-qq-dm-1000000001",
        approval_handler=lambda run_id, event: "once",
        on_stream_event=events.append,
    )

    assert reply == "先答。继续。"
    assert approved == [{"choice": "once"}]
    assert events == [
        {"type": "content", "text": "先答。"},
        {"type": "tool_progress", "payload": {"type": "approval.request", "command": "echo hi"}},
        {"type": "content", "text": "继续。"},
    ]

