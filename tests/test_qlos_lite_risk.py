from qlos_lite.risk import assess_risk


def test_non_owner_high_risk_request_is_blocked():
    risk = assess_risk("帮我执行 powershell 删除文件", is_owner=False)

    assert risk["risk"] == "L4"
    assert risk["blocked"] is True
    assert "non-owner high-risk request matched" in risk["reason"]
    assert risk["safe_reply"] == "这个操作需要主人授权，我不能直接执行。"


def test_owner_high_risk_request_is_not_blocked():
    risk = assess_risk("帮我执行 powershell", is_owner=True)

    assert risk["risk"] == "L3"
    assert risk["blocked"] is False


def test_non_owner_medium_risk_is_sandbox_only():
    risk = assess_risk("帮我做PPT", is_owner=False)

    assert risk["risk"] == "L2_SANDBOX_ONLY"
    assert risk["blocked"] is False


def test_normal_chat_is_l0():
    risk = assess_risk("今天吃什么好", is_owner=False)

    assert risk["risk"] == "L0"
    assert risk["blocked"] is False
