from pathlib import Path

from qlos_lite.config import QLOSLiteConfig
from qlos_lite.models import QQMessageEvent
from qlos_lite.onebot_server import parse_onebot_event
from qlos_lite.router import handle_qq_message


class FakeOneBotClient:
    def __init__(self):
        self.private = []
        self.group = []

    def send_private_msg(self, user_id, message):
        self.private.append((user_id, message))
        return {"ok": True}

    def send_group_msg(self, group_id, message):
        self.group.append((group_id, message))
        return {"ok": True}


class FakeHermesClient:
    def chat(self, messages, session_key=None, session_id=None):
        return "direct"


class FakeHermiClient:
    def __init__(self):
        self.calls = []

    def send_qq_event(self, event, sender, risk, session_id, session_key, trusted_context=None):
        self.calls.append(event)
        return {"ok": True, "reply": "from hermi"}


def _config(tmp_path: Path) -> QLOSLiteConfig:
    return QLOSLiteConfig(
        owner_qq_id="1000000001",
        hermi_gateway_url="http://127.0.0.1:8899",
        hermi_gateway_token="channel-token",
        enable_group=True,
        allowed_group_ids=["100"],
        require_at_in_group=False,
        log_dir=tmp_path / "logs",
        identity_dir=tmp_path / "identity",
        roles_file=tmp_path / "roles.json",
        media_dir=tmp_path / "media",
    )


def _event(message_id: str, text: str, *, chat_type: str = "private", attachments=None):
    return QQMessageEvent(
        message_id=message_id,
        chat_type=chat_type,
        group_id="100" if chat_type == "group" else None,
        user_id="1000000001",
        nickname="Owner",
        raw_message=text,
        text=text,
        attachments=attachments,
    )


def test_private_image_is_staged_then_attached_to_next_text(tmp_path: Path):
    config = _config(tmp_path)
    onebot = FakeOneBotClient()
    hermi = FakeHermiClient()

    staged = handle_qq_message(
        _event("image-only", "[image]", attachments=["image:https://example.com/pic.png"]),
        config,
        onebot,
        FakeHermesClient(),
        hermi_client=hermi,
    )
    assert staged["staged_attachment"] is True
    assert hermi.calls == []

    result = handle_qq_message(
        _event("image-followup", "read this image"),
        config,
        onebot,
        FakeHermesClient(),
        hermi_client=hermi,
    )

    assert result["transport"] == "hermi"
    assert hermi.calls[0].attachments == ["image:https://example.com/pic.png"]


def test_group_image_is_not_staged(tmp_path: Path):
    hermi = FakeHermiClient()
    result = handle_qq_message(
        _event("group-image", "[image]", chat_type="group", attachments=["image:https://example.com/pic.png"]),
        _config(tmp_path),
        FakeOneBotClient(),
        FakeHermesClient(),
        hermi_client=hermi,
    )

    assert result["transport"] == "hermi"
    assert len(hermi.calls) == 1


def test_builtin_qq_face_becomes_semantic_text_tag():
    event = parse_onebot_event(
        {
            "post_type": "message",
            "message_type": "private",
            "user_id": 1000000001,
            "message_id": 813,
            "message": [{"type": "face", "data": {"id": "14", "text": "smile"}}],
            "sender": {"nickname": "Owner"},
        },
        "1000000002",
    )

    assert event is not None
    assert event.text == "[QQ表情: smile]"

