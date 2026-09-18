import threading
import time

from qlos_lite.approval_bridge import ApprovalBridge


def test_approval_bridge_parses_owner_choices(tmp_path):
    bridge = ApprovalBridge(tmp_path)

    assert bridge.parse_approval_choice("同意") == "once"
    assert bridge.parse_approval_choice("本会话同意") == "session"
    assert bridge.parse_approval_choice("永久同意") == "always"
    assert bridge.parse_approval_choice("拒绝") == "deny"
    assert bridge.parse_approval_choice("随便聊聊") is None


def test_approval_bridge_waits_for_later_decision(tmp_path):
    bridge = ApprovalBridge(tmp_path, wait_timeout=2, poll_interval=0.05)
    event = type("Event", (), {"chat_type": "private", "group_id": None, "message_id": "m1"})
    sender = type("Sender", (), {"user_id": "1000000001", "role": "owner"})

    bridge.record_pending(
        "qlos-qq-dm-1000000001",
        "run-1",
        event,
        sender,
        {"type": "approval.request", "command": "echo hi"},
        "qlos:qq:dm:1000000001",
    )

    thread = threading.Thread(
        target=lambda: (time.sleep(0.1), bridge.set_decision("qlos-qq-dm-1000000001", "once")),
        daemon=True,
    )
    thread.start()

    assert bridge.wait_for_decision("qlos-qq-dm-1000000001") == "once"


