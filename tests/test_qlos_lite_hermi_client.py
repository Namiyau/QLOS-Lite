from qlos_lite.hermi_client import HermiGatewayClient
from qlos_lite.trusted_context import build_trusted_context


class FakeEvent:
    message_id = "qq-1"
    chat_type = "private"
    user_id = "1000000001"
    nickname = "Owner"
    text = "hello"
    group_id = None
    attachments = ["image:https://example.com/a.png"]


class FakeSender:
    role = "owner"
    user_id = "1000000001"
    is_owner = True


def test_hermi_client_posts_qq_event(monkeypatch):
    captured = {}

    def fake_request_json(url, payload, token, timeout):
        captured["url"] = url
        captured["payload"] = payload
        captured["token"] = token
        captured["timeout"] = timeout
        return {"ok": True, "reply": "hi"}

    monkeypatch.setattr("qlos_lite.hermi_client._request_json", fake_request_json)

    trusted_context = build_trusted_context(FakeEvent(), FakeSender(), "qlos-qq-dm-1000000001", "qlos:qq:dm:1000000001", "channel-token", now=100)
    result = HermiGatewayClient("http://127.0.0.1:8899", "channel-token", timeout=9).send_qq_event(
        FakeEvent(),
        FakeSender(),
        {"risk": "L0", "blocked": False},
        "qlos-qq-dm-1000000001",
        "qlos:qq:dm:1000000001",
        trusted_context=trusted_context,
    )

    assert result["reply"] == "hi"
    assert captured["url"] == "http://127.0.0.1:8899/channels/qq/events"
    assert captured["token"] == "channel-token"
    assert captured["timeout"] == 9
    assert captured["payload"]["text"] == "hello"
    assert captured["payload"]["sender_role"] == "owner"
    assert "<<<QLOS_SPLIT>>>" in captured["payload"]["qlos_prompt"]
    assert "MUST" in captured["payload"]["qlos_prompt"]
    assert captured["payload"]["trusted_context"] == trusted_context

