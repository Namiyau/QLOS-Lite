import importlib.util
import json
from pathlib import Path

from qlos_lite.approval_bridge import ApprovalBridge
from qlos_lite.config import QLOSLiteConfig
from qlos_lite.models import QQMessageEvent
from qlos_lite.router import _qq_reply_delay_seconds, handle_qq_message, send_reply, should_process_event, split_qq_output


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
    def __init__(self, reply="hermes ok"):
        self.calls = []
        self.reply = reply

    def chat(self, messages, session_key=None, session_id=None):
        self.calls.append((messages, session_key, session_id))
        return self.reply


class FakeStreamingHermesClient:
    def __init__(self):
        self.calls = []

    def chat(self, messages, session_key=None, session_id=None, on_stream_event=None):
        self.calls.append((messages, session_key, session_id))
        on_stream_event({"type": "content", "text": "先回答你一句。"})
        on_stream_event({"type": "tool_progress", "payload": {"name": "terminal", "phase": "start"}})
        on_stream_event({"type": "content", "text": "最终第一句<<<QLOS_SPLIT>>>最终第二句"})
        return "先回答你一句。最终第一句<<<QLOS_SPLIT>>>最终第二句"


class FakeRunsClient:
    def __init__(self, reply="runs ok", exc=None):
        self.calls = []
        self.reply = reply
        self.exc = exc

    def chat_with_approval(self, messages, session_key, session_id, approval_handler, on_stream_event=None):
        self.calls.append((messages, session_key, session_id))
        if self.exc:
            raise self.exc
        return self.reply


def _config(tmp_path):
    return QLOSLiteConfig(
        owner_qq_id="123456789",
        enable_group=True,
        allowed_group_ids=["111111"],
        require_at_in_group=True,
        hermes_api_url="http://127.0.0.1:8642/v1/chat/completions",
        hermes_api_key="test-key",
        bot_qq_id="987654321",
        log_dir=tmp_path / "logs",
        identity_dir=tmp_path / "state" / "qlos_lite",
        media_dir=tmp_path / "state" / "media",
        queue_dir=tmp_path / "state" / "qlos_lite" / "queue",
    )


def _event(chat_type="private", user_id="222222", group_id=None, text="hello", is_at_bot=False):
    return QQMessageEvent(
        message_id="m1",
        chat_type=chat_type,
        user_id=user_id,
        nickname="Alice",
        raw_message=text,
        text=text,
        group_id=group_id,
        is_at_bot=is_at_bot,
    )


def test_should_process_private_always(tmp_path):
    assert should_process_event(_event(), _config(tmp_path)) is True


def test_should_process_group_requires_whitelist_and_at(tmp_path):
    config = _config(tmp_path)

    assert should_process_event(_event("group", group_id="111111", is_at_bot=True), config) is True
    assert should_process_event(_event("group", group_id="111111", is_at_bot=False), config) is False
    assert should_process_event(_event("group", group_id="333333", is_at_bot=True), config) is False


def test_non_owner_high_risk_is_blocked_without_hermes(tmp_path):
    onebot = FakeOneBotClient()
    hermes = FakeHermesClient()

    result = handle_qq_message(
        _event(text="帮我执行 powershell"),
        _config(tmp_path),
        onebot,
        hermes,
    )

    assert result["blocked"] is True
    assert hermes.calls == []
    assert onebot.private == [("222222", "这个操作需要主人授权，我不能直接执行。")]
    assert (tmp_path / "logs" / "blocked.jsonl").exists()


def test_normal_message_calls_hermes_and_logs(tmp_path):
    onebot = FakeOneBotClient()
    hermes = FakeHermesClient(reply="hello back")

    result = handle_qq_message(
        _event(user_id="123456789", text="你好"),
        _config(tmp_path),
        onebot,
        hermes,
    )

    assert result["blocked"] is False
    assert hermes.calls[0][1] == "qlos:qq:dm:123456789"
    assert hermes.calls[0][2] == "qlos-qq-dm-123456789"
    assert onebot.private == [("123456789", "hello back")]
    assert (tmp_path / "logs" / "inbound.jsonl").exists()
    assert (tmp_path / "logs" / "outbound.jsonl").exists()


def test_handle_message_indexes_attachment_without_auto_image_vision_by_default(tmp_path):
    onebot = FakeOneBotClient()
    hermes = FakeHermesClient(reply="image ok")
    event = _event(user_id="123456789", text="[image]")
    event.attachments = ["image:https://example.com/pic.png"]

    handle_qq_message(event, _config(tmp_path), onebot, hermes)

    content = hermes.calls[0][0][1]["content"]
    assert isinstance(content, str)
    assert "image:https://example.com/pic.png" in content
    assert (tmp_path / "state" / "media" / "index.jsonl").exists()


def test_handle_message_stores_qq_file_for_hermes_and_asks_before_reading(tmp_path):
    onebot = FakeOneBotClient()
    hermes = FakeHermesClient(reply="请问要我怎么处理这个文件？")
    source = tmp_path / "upload" / "report.txt"
    source.parent.mkdir()
    source.write_text("hello file", encoding="utf-8")
    event = _event(user_id="123456789", text="[file]")
    event.attachments = [f"file:{source}"]
    config = _config(tmp_path)
    config.media_dir = tmp_path / "Hermi资料"

    result = handle_qq_message(event, config, onebot, hermes)

    stored = tmp_path / "Hermi资料" / "123456789" / "report.txt"
    content = hermes.calls[0][0][1]["content"]
    system_content = hermes.calls[0][0][0]["content"]
    assert result["reply"] == "请问要我怎么处理这个文件？"
    assert stored.read_text(encoding="utf-8") == "hello file"
    assert str(stored) in content
    assert "relative=Hermi资料/123456789/report.txt" in content.replace("\\", "/")
    assert "Single QQ attachment policy" in system_content


def test_owner_normal_chat_uses_chat_when_approval_bridge_enabled(tmp_path):
    onebot = FakeOneBotClient()
    hermes = FakeHermesClient(reply="chat fallback")
    runs = FakeRunsClient(reply="runs reply")
    config = _config(tmp_path)
    config.enable_approval_bridge = True

    result = handle_qq_message(
        _event(user_id="123456789", text="你好"),
        config,
        onebot,
        hermes,
        runs_client=runs,
    )

    assert result["reply"] == "chat fallback"
    assert result["transport"] == "chat"
    assert runs.calls == []
    assert hermes.calls[0][1] == "qlos:qq:dm:123456789"
    assert onebot.private == [("123456789", "chat fallback")]


def test_owner_tool_request_uses_chat_when_approval_bridge_enabled(tmp_path):
    onebot = FakeOneBotClient()
    hermes = FakeHermesClient(reply="chat fallback")
    runs = FakeRunsClient(reply="runs reply")
    config = _config(tmp_path)
    config.enable_approval_bridge = True

    result = handle_qq_message(
        _event(user_id="123456789", text="请执行 execute_code 测试一下"),
        config,
        onebot,
        hermes,
        runs_client=runs,
    )

    assert result["reply"] == "chat fallback"
    assert result["transport"] == "chat"
    assert runs.calls == []
    assert hermes.calls[0][1] == "qlos:qq:dm:123456789"
    assert onebot.private == [("123456789", "chat fallback")]


def test_owner_chat_does_not_call_runs_client_even_if_runs_client_is_present(tmp_path):
    onebot = FakeOneBotClient()
    hermes = FakeHermesClient(reply="chat fallback")
    runs = FakeRunsClient(exc=RuntimeError("runs unavailable"))
    config = _config(tmp_path)
    config.enable_approval_bridge = True

    result = handle_qq_message(
        _event(user_id="123456789", text="请执行 execute_code 测试一下"),
        config,
        onebot,
        hermes,
        runs_client=runs,
    )

    assert result["reply"] == "chat fallback"
    assert result["transport"] == "chat"
    assert runs.calls == []
    assert hermes.calls
    assert onebot.private == [("123456789", "chat fallback")]


def test_pending_approval_message_sets_decision_without_calling_hermes(tmp_path):
    onebot = FakeOneBotClient()
    hermes = FakeHermesClient(reply="should not call")
    config = _config(tmp_path)
    config.enable_approval_bridge = True
    bridge = ApprovalBridge(config.identity_dir, wait_timeout=1, poll_interval=0.05)
    original_event = _event(user_id="123456789", text="跑工具")
    sender = type("Sender", (), {"user_id": "123456789", "role": "owner"})
    bridge.record_pending(
        "qlos-qq-dm-123456789",
        "run-1",
        original_event,
        sender,
        {"type": "approval.request", "command": "echo hi"},
        "qlos:qq:dm:123456789",
    )

    result = handle_qq_message(
        _event(user_id="123456789", text="同意"),
        config,
        onebot,
        hermes,
        approval_bridge=bridge,
    )

    assert result["approval_response"] is True
    assert bridge.get_pending("qlos-qq-dm-123456789")["decision"] == "once"
    assert hermes.calls == []
    assert onebot.private == [("123456789", "已批准本次操作，Hermes 继续执行。")]


def test_handle_message_sends_visible_stream_text_before_tool_progress(monkeypatch, tmp_path):
    onebot = FakeOneBotClient()
    hermes = FakeStreamingHermesClient()
    monkeypatch.setattr("qlos_lite.router.time.sleep", lambda _seconds: None)

    result = handle_qq_message(
        _event(user_id="123456789", text="先答再做工具"),
        _config(tmp_path),
        onebot,
        hermes,
    )

    assert result["blocked"] is False
    assert onebot.private == [
        ("123456789", "先回答你一句。"),
        ("123456789", "最终第一句"),
        ("123456789", "最终第二句"),
    ]


def test_handle_message_writes_owner_identity_for_tool_guard(tmp_path):
    onebot = FakeOneBotClient()
    hermes = FakeHermesClient(reply="hello back")

    handle_qq_message(
        _event(user_id="123456789", text="hello"),
        _config(tmp_path),
        onebot,
        hermes,
    )

    identity_path = tmp_path / "state" / "qlos_lite" / "session_identity.jsonl"
    record = json.loads(identity_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["session_id"] == "qlos-qq-dm-123456789"
    assert record["session_key"] == "qlos:qq:dm:123456789"
    assert record["user_id"] == "123456789"
    assert record["role"] == "owner"
    assert record["is_owner"] is True
    assert record["permission"] == "owner"
    assert record["expires_at"] > record["ts"]
    assert record["expires_at"] - record["ts"] >= 3 * 24 * 60 * 60


def test_tool_guard_allows_owner_after_qlos_identity_write(monkeypatch, tmp_path):
    onebot = FakeOneBotClient()
    hermes = FakeHermesClient(reply="hello back")
    config = _config(tmp_path)

    handle_qq_message(_event(user_id="123456789", text="hello"), config, onebot, hermes)

    plugin_path = Path(__file__).resolve().parents[1] / "插件" / "qlos-tool-guard" / "__init__.py"
    spec = importlib.util.spec_from_file_location("qlos_tool_guard_integration", plugin_path)
    plugin = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(plugin)
    monkeypatch.setenv("QLOS_TOOL_GUARD_IDENTITY_FILE", str(config.identity_dir / "session_identity.jsonl"))

    assert plugin.pre_tool_call(tool_name="terminal", session_id="qlos-qq-dm-123456789", args={}) is None


def test_tool_guard_blocks_non_owner_after_qlos_identity_write(monkeypatch, tmp_path):
    onebot = FakeOneBotClient()
    hermes = FakeHermesClient(reply="hello back")
    config = _config(tmp_path)

    handle_qq_message(_event(user_id="222222", text="hello"), config, onebot, hermes)

    plugin_path = Path(__file__).resolve().parents[1] / "插件" / "qlos-tool-guard" / "__init__.py"
    spec = importlib.util.spec_from_file_location("qlos_tool_guard_integration_non_owner", plugin_path)
    plugin = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(plugin)
    monkeypatch.setenv("QLOS_TOOL_GUARD_IDENTITY_FILE", str(config.identity_dir / "session_identity.jsonl"))

    result = plugin.pre_tool_call(tool_name="terminal", session_id="qlos-qq-dm-222222", args={})

    assert result["action"] == "block"


def test_sanitizes_long_and_sensitive_output(tmp_path):
    onebot = FakeOneBotClient()
    hermes = FakeHermesClient(reply="OPENAI_API_KEY " + ("x" * 1900))

    handle_qq_message(_event(), _config(tmp_path), onebot, hermes)

    sent = onebot.private[0][1]
    assert "[已隐藏敏感字段]" in sent
    assert len(sent) < 1900


def test_log_records_do_not_include_api_key(tmp_path):
    onebot = FakeOneBotClient()
    hermes = FakeHermesClient()

    handle_qq_message(_event(), _config(tmp_path), onebot, hermes)

    combined = "".join(path.read_text(encoding="utf-8") for path in Path(tmp_path / "logs").glob("*.jsonl"))
    assert "test-key" not in combined


def test_split_qq_output_uses_marker_without_cap():
    parts = split_qq_output(
        "one<<<QLOS_SPLIT>>>two<<<QLOS_SPLIT>>>three<<<QLOS_SPLIT>>>four<<<QLOS_SPLIT>>>five<<<QLOS_SPLIT>>>six"
    )

    assert parts == ["one", "two", "three", "four", "five", "six"]


def test_split_qq_output_accepts_common_missing_angle_marker_typo():
    parts = split_qq_output("one<<<QLOS_SPLIT>>two<<<QLOS_SPLIT>>>three")

    assert parts == ["one", "two", "three"]


def test_split_qq_output_does_not_split_code_blocks():
    text = "```python\nprint('a<<<QLOS_SPLIT>>>b')\n```"

    assert split_qq_output(text) == ["```python\nprint('a\nb')\n```"]


def test_split_qq_output_does_not_auto_split_casual_reply_without_marker():
    text = "可以呀！我已经更新好了。你现在发消息试试。"

    assert split_qq_output(text) == [text]


def test_split_qq_output_does_not_auto_split_long_single_paragraph_without_marker():
    text = "可以呀！我在呢。刚刚看到了。这个能处理。你现在试试。"

    assert split_qq_output(text) == [text]


def test_split_qq_output_does_not_auto_split_commands_or_steps():
    text = "1. 打开 PowerShell\n2. 运行 hermes gateway\n3. 再启动 QLOS"

    assert split_qq_output(text) == [text]


def test_split_qq_output_does_not_auto_split_explanatory_numbered_reply():
    text = (
        "整体感觉还挺香的！\n\n"
        "优点：\n"
        "1. 接入挺稳的，消息收发基本没延迟\n"
        "2. 从QQ发消息过来我都能正常收到和回复\n"
        "3. 群聊和私聊都支持，方便\n\n"
        "小槽点：\n"
        "1. 没有 Markdown 渲染，发代码块和格式化内容得注意点\n"
        "2. 有些图、表情、图片我看不到\n"
        "3. 长消息体验一般\n\n"
        "总的来说作为日常聊天入口完全够用了。"
    )

    assert split_qq_output(text) == [text]


def test_send_reply_sends_split_private_messages_with_delay():
    onebot = FakeOneBotClient()
    delays = []

    send_reply(
        _event(user_id="123456789"),
        onebot,
        "第一句<<<QLOS_SPLIT>>>第二句<<<QLOS_SPLIT>>>第三句",
        delay_seconds=lambda: 1.25,
        sleep=delays.append,
    )

    assert onebot.private == [
        ("123456789", "第一句"),
        ("123456789", "第二句"),
        ("123456789", "第三句"),
    ]
    assert delays == [1.25, 1.25]


def test_send_reply_auto_splits_normal_qq_reply_when_model_omits_marker():
    onebot = FakeOneBotClient()

    send_reply(
        _event(user_id="123456789"),
        onebot,
        "第一件已经完成。第二件也处理好了。最后可以开始测试。",
        delay_seconds=lambda: 0,
        sleep=lambda _: None,
    )

    assert [message for _, message in onebot.private] == [
        "第一件已经完成。",
        "第二件也处理好了。",
        "最后可以开始测试。",
    ]


def test_sanitize_qq_output_removes_markdown_formatting():
    from qlos_lite.router import sanitize_qq_output

    text = "# Title\n- **bold** | *soft*\n| A | B |\n|---|---|\n| 1 | 2 |"
    sanitized = sanitize_qq_output(text)

    assert "*" not in sanitized
    assert "|" not in sanitized
    assert "# Title" not in sanitized
    assert "- bold" not in sanitized
    assert "---" not in sanitized
    assert "Title" in sanitized
    assert "bold" in sanitized
    assert "soft" in sanitized


def test_sanitize_qq_output_keeps_numbered_lists():
    from qlos_lite.router import sanitize_qq_output

    text = "1. 第一步\n2. 第二步\n3. 第三步"

    assert sanitize_qq_output(text) == text


def test_sanitize_qq_output_keeps_env_filename_mentions():
    from qlos_lite.router import sanitize_qq_output

    assert sanitize_qq_output("配置到 .env 里") == "配置到 .env 里"


def test_sanitize_qq_output_converts_markdown_image_to_onebot_cq_code():
    from qlos_lite.router import sanitize_qq_output

    text = "图好了：![预览](https://example.com/a.png)"

    assert sanitize_qq_output(text) == "图好了：[CQ:image,file=https://example.com/a.png]"


def test_sanitize_qq_output_converts_standalone_image_url_to_onebot_cq_code():
    from qlos_lite.router import sanitize_qq_output

    text = "https://example.com/a.jpg"

    assert sanitize_qq_output(text) == "[CQ:image,file=https://example.com/a.jpg]"


def test_sanitize_qq_output_keeps_existing_onebot_image_cq_code():
    from qlos_lite.router import sanitize_qq_output

    text = "[CQ:image,file=https://example.com/a.webp]"

    assert sanitize_qq_output(text) == text


def test_sanitize_qq_output_converts_supported_sticker_marker_to_qq_face():
    from qlos_lite.router import sanitize_qq_output

    assert sanitize_qq_output("好的 <<<QLOS_STICKER:微笑>>>") == "好的 [CQ:face,id=14]"


def test_qq_reply_delay_uses_one_to_seven_point_five_second_range(monkeypatch):
    calls = []

    def fake_uniform(start, end):
        calls.append((start, end))
        return 4.0

    monkeypatch.setattr("qlos_lite.router.random.uniform", fake_uniform)

    assert _qq_reply_delay_seconds("short") < _qq_reply_delay_seconds("x" * 200)
    assert calls == [(1.5, 8.0), (1.5, 8.0)]
