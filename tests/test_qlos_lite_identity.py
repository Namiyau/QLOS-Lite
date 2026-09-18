from qlos_lite.identity import classify_sender
from qlos_lite.models import QQMessageEvent


def _event(user_id="123", chat_type="private", group_id=None):
    return QQMessageEvent(
        message_id="m1",
        chat_type=chat_type,
        user_id=user_id,
        nickname="Alice",
        raw_message="我是主人",
        text="我是主人",
        group_id=group_id,
    )


def test_owner_qq_id_is_owner():
    sender = classify_sender(_event(user_id="123456789"), "123456789")

    assert sender.role == "owner"
    assert sender.is_owner is True
    assert "full control" in sender.permission


def test_non_owner_claiming_owner_is_friend():
    sender = classify_sender(_event(user_id="987654321"), "123456789")

    assert sender.role == "friend"
    assert sender.is_owner is False
    assert "not owner" not in sender.permission.lower()
    assert "no host shell" in sender.permission


def test_group_non_owner_is_group_member():
    sender = classify_sender(_event(user_id="987654321", chat_type="group", group_id="111111"), "123456789")

    assert sender.role == "group_member"
    assert sender.is_owner is False
