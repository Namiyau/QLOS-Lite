from qlos_lite.trusted_context import build_trusted_context, verify_trusted_context


class Event:
    message_id = "qq-1"
    chat_type = "group"
    user_id = "1000000001"
    group_id = "9988"


class Sender:
    user_id = "1000000001"
    role = "owner"
    is_owner = True


def test_trusted_context_binds_hashed_qq_identity_to_session_without_raw_ids():
    context = build_trusted_context(Event(), Sender(), "qlos-session", "qlos-key", "channel-token", now=100)

    verified = verify_trusted_context(context, "channel-token", "qlos-session", "qlos-key", now=101)

    assert verified["platform"] == "qq"
    assert verified["chat_type"] == "group"
    assert verified["is_owner"] is True
    assert verified["subject_id_hash"]
    assert verified["group_id_hash"]
    assert "1000000001" not in str(context)
    assert "9988" not in str(context)


def test_trusted_context_rejects_tampering_expiry_and_different_session():
    context = build_trusted_context(Event(), Sender(), "qlos-session", "qlos-key", "channel-token", now=100, ttl_seconds=5)
    tampered = {**context, "is_owner": False}

    assert verify_trusted_context(tampered, "channel-token", "qlos-session", "qlos-key", now=101) is None
    assert verify_trusted_context(context, "channel-token", "other-session", "qlos-key", now=101) is None
    assert verify_trusted_context(context, "channel-token", "qlos-session", "qlos-key", now=106) is None

