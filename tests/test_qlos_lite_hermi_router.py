from pathlib import Path

from qlos_lite.config import QLOSLiteConfig
from qlos_lite.models import QQMessageEvent
from qlos_lite.router import handle_qq_message


class FakeOneBotClient:
    def __init__(self):
        self.private = []

    def send_private_msg(self, user_id, message):
        self.private.append((user_id, message))
        return {"ok": True}


class FakeHermesClient:
    def __init__(self):
        self.calls = []

    def chat(self, messages, session_key=None, session_id=None, on_stream_event=None):
        self.calls.append((messages, session_key, session_id))
        return "direct hermes"


class FakeHermiClient:
    def __init__(self):
        self.calls = []

    def send_qq_event(self, event, sender, risk, session_id, session_key, trusted_context=None):
        self.calls.append((event, sender, risk, session_id, session_key, trusted_context))
        return {"ok": True, "reply": "from hermi"}


class DuplicateHermiClient(FakeHermiClient):
    def send_qq_event(self, event, sender, risk, session_id, session_key, trusted_context=None):
        self.calls.append((event, sender, risk, session_id, session_key, trusted_context))
        return {"ok": True, "duplicate": True, "reply": ""}


def test_router_uses_hermi_gateway_when_configured(tmp_path: Path):
    event = QQMessageEvent(
        message_id="qq-1",
        chat_type="private",
        user_id="1000000001",
        nickname="Owner",
        raw_message="hello",
        text="hello",
    )
    config = QLOSLiteConfig(
        owner_qq_id="1000000001",
        hermi_gateway_url="http://127.0.0.1:8899",
        hermi_gateway_token="channel-token",
        log_dir=tmp_path / "logs",
        identity_dir=tmp_path / "identity",
        roles_file=tmp_path / "roles.json",
        media_dir=tmp_path / "media",
    )
    onebot = FakeOneBotClient()
    hermes = FakeHermesClient()
    hermi = FakeHermiClient()

    result = handle_qq_message(event, config, onebot, hermes, hermi_client=hermi)

    assert result["transport"] == "hermi"
    assert hermes.calls == []
    assert hermi.calls[0][3] == "qlos-qq-dm-1000000001"
    assert hermi.calls[0][5]["subject_id_hash"]
    assert onebot.private == [("1000000001", "from hermi")]


def test_router_does_not_send_a_visible_reply_for_a_duplicate_hermi_event(tmp_path: Path):
    event = QQMessageEvent(
        message_id="qq-duplicate",
        chat_type="private",
        user_id="1000000001",
        nickname="Owner",
        raw_message="hello",
        text="hello",
    )
    config = QLOSLiteConfig(
        owner_qq_id="1000000001",
        hermi_gateway_url="http://127.0.0.1:8899",
        hermi_gateway_token="channel-token",
        log_dir=tmp_path / "logs",
        identity_dir=tmp_path / "identity",
        roles_file=tmp_path / "roles.json",
        media_dir=tmp_path / "media",
    )
    onebot = FakeOneBotClient()
    hermi = DuplicateHermiClient()

    result = handle_qq_message(event, config, onebot, FakeHermesClient(), hermi_client=hermi)

    assert result["duplicate"] is True
    assert onebot.private == []

