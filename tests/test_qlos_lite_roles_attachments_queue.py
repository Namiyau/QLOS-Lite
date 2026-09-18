from __future__ import annotations

import json

from qlos_lite.attachments import prepare_attachments
from qlos_lite.config import QLOSLiteConfig
from qlos_lite.identity import classify_sender
from qlos_lite.models import QQMessageEvent
from qlos_lite.queue import MessageQueue
from qlos_lite.roles import RolePolicy, load_role_policy


def _event(user_id="222", chat_type="private", group_id=None, attachments=None):
    return QQMessageEvent(
        message_id="m1",
        chat_type=chat_type,
        user_id=user_id,
        nickname="Alice",
        raw_message="hello",
        text="hello",
        group_id=group_id,
        attachments=attachments,
    )


def test_role_policy_overrides_non_owner_permission(tmp_path):
    roles_path = tmp_path / "roles.json"
    roles_path.write_text(
        json.dumps(
            {
                "users": {"222": {"role": "trusted_friend"}},
                "roles": {
                    "trusted_friend": {
                        "permission": "trusted sandbox user; no host shell",
                        "allow_group_without_at": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    policy = load_role_policy(roles_path)
    sender = classify_sender(_event(user_id="222"), "123", policy)

    assert sender.role == "trusted_friend"
    assert sender.is_owner is False
    assert sender.permission == "trusted sandbox user; no host shell"
    assert policy.should_allow_group_without_at("222", "999") is True


def test_owner_role_cannot_be_stolen_by_role_policy(tmp_path):
    roles_path = tmp_path / "roles.json"
    roles_path.write_text(json.dumps({"users": {"222": {"role": "owner"}}}), encoding="utf-8")

    sender = classify_sender(_event(user_id="222"), "123", load_role_policy(roles_path))

    assert sender.role == "friend"
    assert sender.is_owner is False


def test_prepare_attachments_writes_media_index_and_returns_stable_refs(tmp_path):
    event = _event(
        attachments=[
            "image:https://example.com/a.png",
            "file:C:/tmp/report.pdf",
            "",
        ]
    )

    refs = prepare_attachments(event, media_dir=tmp_path / "media")

    assert len(refs) == 2
    assert refs[0].startswith("image:")
    assert refs[1].startswith("file:")
    rows = [json.loads(line) for line in (tmp_path / "media" / "index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["message_id"] == "m1"
    assert rows[0]["kind"] == "image"
    assert rows[0]["original"] == "https://example.com/a.png"
    assert rows[0]["ref"].startswith("image:qlos-media:")


def test_message_queue_enqueues_once_marks_done_and_retries_stale_processing(tmp_path):
    queue = MessageQueue(tmp_path / "queue")
    payload = {"post_type": "message", "message_id": "m1"}

    assert queue.enqueue("m1", payload) is True
    assert queue.enqueue("m1", payload) is False
    item = queue.claim_next(stale_after_seconds=0)
    assert item is not None
    assert item.message_id == "m1"
    queue.mark_done("m1")
    assert queue.claim_next(stale_after_seconds=0) is None

    queue.enqueue("m2", {"message_id": "m2"})
    first = queue.claim_next(stale_after_seconds=0)
    retry = queue.claim_next(stale_after_seconds=0)
    assert first is not None
    assert retry is not None
    assert retry.message_id == "m2"


def test_config_loads_roles_media_and_queue_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("QLOS_ROLES_FILE", str(tmp_path / "roles.json"))
    monkeypatch.setenv("QLOS_MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setenv("QLOS_QUEUE_DIR", str(tmp_path / "queue"))
    monkeypatch.setenv("QLOS_ENABLE_QUEUE", "true")

    config = QLOSLiteConfig(owner_qq_id="1")
    from qlos_lite.config import load_qlos_lite_config

    loaded = load_qlos_lite_config()

    assert loaded.roles_file == tmp_path / "roles.json"
    assert loaded.media_dir == tmp_path / "media"
    assert loaded.queue_dir == tmp_path / "queue"
    assert loaded.enable_queue is True
