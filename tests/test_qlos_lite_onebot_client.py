import json

import pytest

from qlos_lite.onebot_client import OneBotClient, OneBotSendError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_onebot_client_returns_success_response(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse({"status": "ok", "retcode": 0, "data": {"message_id": 1}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = OneBotClient("http://127.0.0.1:3000", "secret").send_private_msg("1000000001", "hello")

    assert result["retcode"] == 0


def test_onebot_client_raises_on_failed_retcode(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse({"status": "failed", "retcode": 1400, "wording": "bad user_id"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(OneBotSendError):
        OneBotClient("http://127.0.0.1:3000", "secret").send_private_msg("bad", "hello")


def test_onebot_client_uploads_private_file(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["auth"] = request.headers["Authorization"]
        return FakeResponse({"status": "ok", "retcode": 0})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    OneBotClient("http://127.0.0.1:3000", "secret").upload_private_file(
        "1000000001",
        "C:/tmp/report.docx",
        "report.docx",
    )

    assert captured["url"] == "http://127.0.0.1:3000/upload_private_file"
    assert captured["payload"] == {
        "user_id": 1000000001,
        "file": "C:/tmp/report.docx",
        "name": "report.docx",
    }
    assert captured["auth"] == "Bearer secret"

