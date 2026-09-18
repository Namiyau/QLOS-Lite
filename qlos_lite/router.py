from __future__ import annotations

import random
import re
import time
from inspect import Parameter, signature

from .approval_bridge import ApprovalBridge
from .attachments import prepare_attachments
from .hermi_client import HermiGatewayClient
from .hermes_client import build_session_id, build_session_key
from .hermes_runs_client import HermesRunsClient
from .identity import classify_sender
from .identity_sidecar import write_session_identity
from .trusted_context import build_trusted_context
from .logger import AuditLogger
from .private_image_stash import consume_private_images, is_private_image_only, stage_private_images
from .prompt_builder import build_hermes_messages
from .risk import assess_risk
from .roles import load_role_policy


QLOS_SPLIT_MARKER = "<<<QLOS_SPLIT>>>"
QLOS_STICKER_MARKER_PATTERN = re.compile(r"<<<QLOS_STICKER:(?P<tag>[^>]+)>>>")
MAX_QQ_REPLY_PARTS = 5
MAX_QQ_AUTO_REPLY_PARTS = 4

QQ_STICKER_FACE_IDS = {
    "微笑": 14,
    "可爱": 20,
    "坏笑": 43,
    "委屈": 48,
    "呲牙": 13,
    "大哭": 9,
    "发怒": 11,
    "流汗": 26,
    "亲亲": 51,
}


def should_process_event(event, config, role_policy=None) -> bool:
    if event.chat_type == "private":
        return True
    if not config.enable_group:
        return False
    if config.allowed_group_ids and str(event.group_id) not in {str(item) for item in config.allowed_group_ids}:
        return False
    if config.require_at_in_group and not event.is_at_bot:
        if role_policy and role_policy.should_allow_group_without_at(event.user_id, event.group_id):
            return True
        return False
    return True


def sanitize_qq_output(text: str) -> str:
    text = _convert_qq_sticker_output(_convert_qq_image_output(str(text).strip()))
    text = _strip_qq_markdown(text)
    max_len = 1800
    if len(text) > max_len:
        text = text[:max_len] + "\n\n……内容较长，我先发到这里。"
    sensitive_markers = [
        "Authorization: Bearer",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "HERMES_API_KEY",
        "QLOS_HERMES_API_KEY",
        "cookie=",
    ]
    for marker in sensitive_markers:
        if marker in text:
            text = text.replace(marker, "[已隐藏敏感字段]")
    return text


def _convert_qq_sticker_output(text: str) -> str:
    def replace_marker(match: re.Match[str]) -> str:
        tag = match.group("tag").strip()
        face_id = QQ_STICKER_FACE_IDS.get(tag)
        return f"[CQ:face,id={face_id}]" if face_id is not None else ""

    return QLOS_STICKER_MARKER_PATTERN.sub(replace_marker, text)


def _convert_qq_image_output(text: str) -> str:
    if not text:
        return text

    def markdown_image_repl(match: re.Match[str]) -> str:
        url = match.group("url").strip()
        return f"[CQ:image,file={url}]"

    text = re.sub(
        r"!\[[^\]]*]\((?P<url>https?://[^\s)]+|data:image/[^)\s]+)\)",
        markdown_image_repl,
        text,
    )

    converted_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[CQ:image,"):
            converted_lines.append(line)
            continue
        if _is_standalone_image_url(stripped):
            converted_lines.append(f"[CQ:image,file={stripped}]")
        else:
            converted_lines.append(line)
    return "\n".join(converted_lines)


def _is_standalone_image_url(text: str) -> bool:
    if text.startswith("data:image/"):
        return True
    if not text.startswith(("http://", "https://")):
        return False
    return re.search(r"\.(png|jpe?g|gif|webp|bmp)(\?.*)?(#.*)?$", text, re.IGNORECASE) is not None


def _strip_qq_markdown(text: str) -> str:
    lines = []
    table_separator = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
    for line in text.splitlines():
        if table_separator.match(line):
            continue
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        line = re.sub(r"^\s*[-*]\s+", "", line)
        line = re.sub(r"(\*\*|__)(.*?)\1", r"\2", line)
        line = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"\1", line)
        line = line.replace("|", " ")
        line = line.replace("**", "").replace("*", "")
        if re.fullmatch(r"\s*-{3,}\s*", line):
            continue
        lines.append(re.sub(r"[ \t]{2,}", " ", line).strip())
    return "\n".join(line for line in lines if line).strip()


def split_qq_output(text: str, max_parts: int = MAX_QQ_REPLY_PARTS) -> list[str]:
    text = str(text).strip()
    text = re.sub(r"<<<QLOS_SPLIT>>(?!>)", QLOS_SPLIT_MARKER, text)
    if QLOS_SPLIT_MARKER not in text:
        return [text]

    if "```" in text:
        return [text.replace(QLOS_SPLIT_MARKER, "\n").strip()]

    parts = [part.strip() for part in text.split(QLOS_SPLIT_MARKER) if part.strip()]
    return parts or [""]


def _cap_reply_parts(parts: list[str], max_parts: int) -> list[str]:
    if not parts:
        return [""]
    if len(parts) <= max_parts:
        return parts
    return parts[: max_parts - 1] + ["\n".join(parts[max_parts - 1 :])]


def _group_short_reply_parts(parts: list[str], max_chars: int = 12) -> list[str]:
    grouped = []
    current = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not current:
            current = part
            continue
        if len(current) + len(part) <= max_chars:
            current += part
            continue
        grouped.append(current)
        current = part
    if current:
        grouped.append(current)
    return grouped or [""]


def _looks_code_or_command_like(text: str) -> bool:
    if "```" in text:
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    command_prefixes = ("$", ">", "PS ", "PS>", "python ", "pip ", "npm ", "git ", "hermes ", "cmd ", "powershell ")
    if any(line.startswith(command_prefixes) for line in lines):
        return True
    if any("|" in line and line.count("|") >= 2 for line in lines):
        return True
    if any("=" in line and re.match(r"^[A-Z0-9_]+\s*=", line) for line in lines):
        return True
    normalized_lines = [re.sub(r"^\d+[.)、]\s*", "", line).strip().lower() for line in lines]
    command_like_starts = (
        "运行 ",
        "执行 ",
        "打开 powershell",
        "启动 qlos",
        "启动 hermes",
        "hermes gateway",
        "python -m ",
        "pip ",
        "npm ",
        "git ",
    )
    return any(line.startswith(command_like_starts) for line in normalized_lines)


def _group_units(units: list[str], max_parts: int, separator: str = "") -> list[str]:
    units = [unit.strip() for unit in units if unit.strip()]
    if not units:
        return [""]
    if len(units) <= max_parts:
        return units

    total_chars = sum(len(unit) for unit in units)
    target_chars = max(1, total_chars // max_parts)
    grouped: list[str] = []
    current: list[str] = []
    for index, unit in enumerate(units):
        remaining_units = len(units) - index
        remaining_slots = max_parts - len(grouped)
        current_text = separator.join(current)
        if current and len(current_text) + len(unit) > target_chars and remaining_units >= remaining_slots:
            grouped.append(current_text)
            current = [unit]
        else:
            current.append(unit)
    if current:
        grouped.append(separator.join(current))

    if len(grouped) <= max_parts:
        return grouped
    return grouped[: max_parts - 1] + [separator.join(grouped[max_parts - 1 :])]


def _sentence_units(text: str) -> list[str]:
    sentences = [match.group(0).strip() for match in re.finditer(r"[^。！？!?…\n]+[。！？!?…]+", text)]
    remainder = re.sub(r"[^。！？!?…\n]+[。！？!?…]+", "", text).strip()
    if remainder:
        sentences.append(remainder)
    return sentences


def _auto_split_qq_output(text: str, max_parts: int = MAX_QQ_REPLY_PARTS) -> list[str]:
    if not text or _looks_code_or_command_like(text):
        return [text]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
    if len(paragraphs) > 1:
        return _group_units(paragraphs, max_parts=max_parts, separator="\n\n")

    if len(text) < 18:
        return [text]

    sentences = _sentence_units(text)
    if 1 < len(sentences) and all(1 <= len(part) <= 120 for part in sentences):
        return _group_units(_group_short_reply_parts(sentences), max_parts=max_parts)
    if 1 < len(sentences):
        return _group_units(sentences, max_parts=max_parts)
    return [text]


def _qq_reply_delay_seconds(part: str = "") -> float:
    base = random.uniform(1.5, 8.0)
    length_factor = min(len(str(part).strip()) / 200, 1)
    delay = base + ((length_factor - 0.5) * 1.5)
    return max(1.5, min(8.0, delay))


def _reply_delay(delay_seconds, part: str) -> float:
    try:
        return delay_seconds(part)
    except TypeError:
        return delay_seconds()


def send_reply(event, onebot_client, reply: str, delay_seconds=None, sleep=None):
    delay_seconds = delay_seconds or _qq_reply_delay_seconds
    sleep = sleep or time.sleep
    replies = split_qq_output(reply)
    if len(replies) == 1 and QLOS_SPLIT_MARKER not in str(reply):
        replies = _auto_split_qq_output(replies[0])
    replies = [sanitize_qq_output(part) for part in replies]
    results = []
    for index, part in enumerate(replies):
        if index > 0:
            sleep(_reply_delay(delay_seconds, part))
        if event.chat_type == "private":
            results.append(onebot_client.send_private_msg(event.user_id, part))
        else:
            results.append(onebot_client.send_group_msg(event.group_id, part))
    return results


class StreamingQQReplyDispatcher:
    def __init__(self, event, onebot_client):
        self.event = event
        self.onebot_client = onebot_client
        self.buffer = ""
        self.seen_stream_content = False
        self.sent_any = False

    def handle_event(self, event: dict[str, object]) -> None:
        event_type = str(event.get("type") or "")
        if event_type == "content":
            text = str(event.get("text") or "")
            if not text:
                return
            self.seen_stream_content = True
            self.buffer += text
            self._flush_complete_marker_parts()
            return
        if event_type == "tool_progress":
            self.flush_remaining()

    def flush_remaining(self) -> None:
        if not self.buffer.strip():
            self.buffer = ""
            return
        send_reply(self.event, self.onebot_client, self.buffer)
        self.sent_any = True
        self.buffer = ""

    def _flush_complete_marker_parts(self) -> None:
        if QLOS_SPLIT_MARKER not in self.buffer or "```" in self.buffer:
            return
        parts = self.buffer.split(QLOS_SPLIT_MARKER)
        self.buffer = parts[-1]
        ready = [part.strip() for part in parts[:-1] if part.strip()]
        for part in ready:
            send_reply(self.event, self.onebot_client, part)
            self.sent_any = True


def _chat_supports_stream_events(hermes_client) -> bool:
    try:
        params = signature(hermes_client.chat).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(param.name == "on_stream_event" or param.kind == Parameter.VAR_KEYWORD for param in params)


def _call_hermes_chat(hermes_client, messages, session_key, session_id, on_stream_event=None) -> str:
    if on_stream_event and _chat_supports_stream_events(hermes_client):
        return hermes_client.chat(
            messages,
            session_key=session_key,
            session_id=session_id,
            on_stream_event=on_stream_event,
        )
    return hermes_client.chat(messages, session_key=session_key, session_id=session_id)


def _send_hermi_event(hermi_client, event, sender, risk, session_id, session_key, trusted_context):
    """Use the new optional context without breaking an older Hermi client shim."""
    try:
        parameters = signature(hermi_client.send_qq_event).parameters.values()
        supports_context = any(param.name == "trusted_context" or param.kind == Parameter.VAR_KEYWORD for param in parameters)
    except (TypeError, ValueError):
        supports_context = False
    if supports_context:
        return hermi_client.send_qq_event(event, sender, risk, session_id, session_key, trusted_context=trusted_context)
    return hermi_client.send_qq_event(event, sender, risk, session_id, session_key)


def _approval_choice_ack(choice: str) -> str:
    if choice == "deny":
        return "已拒绝，Hermes 不会继续这个操作。"
    if choice == "session":
        return "已批准本会话，Hermes 继续执行。"
    if choice == "always":
        return "已批准长期规则，Hermes 继续执行。"
    return "已批准本次操作，Hermes 继续执行。"


def _make_approval_bridge(config) -> ApprovalBridge:
    return ApprovalBridge(
        config.identity_dir,
        wait_timeout=getattr(config, "approval_wait_timeout", 600),
        poll_interval=getattr(config, "approval_poll_interval", 1.0),
    )


def _make_runs_client(config) -> HermesRunsClient:
    api_url = getattr(config, "hermes_runs_api_url", "") or config.hermes_api_url
    return HermesRunsClient(api_url, config.hermes_api_key, timeout=config.hermes_timeout)


def _make_hermi_client(config) -> HermiGatewayClient:
    return HermiGatewayClient(
        getattr(config, "hermi_gateway_url", ""),
        getattr(config, "hermi_gateway_token", ""),
        timeout=getattr(config, "hermes_timeout", 180),
    )


def _should_use_runs_api(event, sender, risk: dict[str, object], bridge_enabled: bool) -> bool:
    # QQ owner messages use chat/completions so Hermes can restore session context.
    # Existing pending approvals are still handled before this routing decision.
    return False


def handle_qq_message(
    event,
    config,
    onebot_client,
    hermes_client,
    audit_logger=None,
    runs_client=None,
    approval_bridge=None,
    hermi_client=None,
) -> dict[str, object] | None:
    role_policy = load_role_policy(getattr(config, "roles_file", None))
    if not should_process_event(event, config, role_policy):
        return {"ok": True, "ignored": True}
    if role_policy.is_blocked(event.user_id, event.group_id):
        return {"ok": True, "ignored": True, "blocked_user": True}

    audit_logger = audit_logger or AuditLogger(config.log_dir, enabled=config.enable_logging)
    if event.attachments:
        resolver = getattr(onebot_client, "get_file", None)
        event.attachments = prepare_attachments(event, getattr(config, "media_dir", "./state/media"), resolve_file=resolver)
    sender = classify_sender(event, config.owner_qq_id, role_policy)
    risk = assess_risk(event.text, sender.is_owner)
    if not config.enable_high_risk_block:
        risk = {**risk, "blocked": False}

    session_id = build_session_id(event, sender)
    session_key = build_session_key(event, sender)

    audit_logger.log_inbound(event, sender, risk)
    write_session_identity(event, sender, risk, session_id, session_key, config.identity_dir)

    if getattr(config, "hermi_gateway_url", "") and is_private_image_only(event):
        stage_private_images(config.identity_dir, event.user_id, event.attachments or [])
        reply = "图片已暂存。下一条私聊文字会作为这张图片的处理要求。"
        send_reply(event, onebot_client, reply)
        audit_logger._write(
            "attachment",
            {"event": "private_image_staged", "message_id": event.message_id, "user_id": event.user_id},
        )
        audit_logger.log_outbound(event, sender, reply)
        return {"ok": True, "staged_attachment": True, "reply": reply}

    if event.chat_type == "private" and not event.attachments:
        staged_attachments = consume_private_images(config.identity_dir, event.user_id)
        if staged_attachments:
            event.attachments = staged_attachments
            audit_logger._write(
                "attachment",
                {"event": "private_image_attached", "message_id": event.message_id, "user_id": event.user_id},
            )

    bridge_enabled = bool(getattr(config, "enable_approval_bridge", False))
    approval_bridge = approval_bridge or _make_approval_bridge(config)
    if bridge_enabled and approval_bridge.has_pending(session_id):
        choice = approval_bridge.parse_approval_choice(event.text)
        if choice is None:
            reply = "当前有 Hermes 审批在等待。请回复：同意 / 拒绝 / 本会话同意。"
            send_reply(event, onebot_client, reply)
            audit_logger._write(
                "approval",
                {
                    "event": "pending_prompt_repeat",
                    "session_id": session_id,
                    "user_id": sender.user_id,
                    "sender_role": sender.role,
                },
            )
            return {"ok": True, "approval_pending": True}
        if not sender.is_owner:
            reply = "只有 owner QQ 可以批准这个操作。"
            send_reply(event, onebot_client, reply)
            audit_logger._write(
                "approval",
                {
                    "event": "approval_denied_non_owner",
                    "session_id": session_id,
                    "user_id": sender.user_id,
                    "choice": choice,
                },
            )
            return {"ok": True, "approval_response": False, "forbidden": True}
        approval_bridge.set_decision(session_id, choice)
        reply = _approval_choice_ack(choice)
        send_reply(event, onebot_client, reply)
        audit_logger._write(
            "approval",
            {
                "event": "approval_decision_received",
                "session_id": session_id,
                "run_id": approval_bridge.get_pending(session_id).get("run_id")
                if approval_bridge.get_pending(session_id)
                else None,
                "user_id": sender.user_id,
                "choice": choice,
            },
        )
        return {"ok": True, "approval_response": True, "choice": choice}

    if risk["blocked"]:
        reply = str(risk["safe_reply"] or "这个请求需要主人授权。")
        send_reply(event, onebot_client, reply)
        audit_logger.log_blocked(event, sender, risk, reply)
        return {"ok": True, "blocked": True, "reply": reply}

    if getattr(config, "hermi_gateway_url", ""):
        try:
            hermi_client = hermi_client or _make_hermi_client(config)
            trusted_context = build_trusted_context(
                event, sender, session_id, session_key, getattr(config, "hermi_gateway_token", "")
            )
            result = _send_hermi_event(hermi_client, event, sender, risk, session_id, session_key, trusted_context)
            if result.get("duplicate"):
                audit_logger._write(
                    "gateway",
                    {"event": "hermi_duplicate", "message_id": event.message_id, "session_id": session_id},
                )
                return {"ok": True, "blocked": False, "duplicate": True, "transport": "hermi"}
            reply = str(result.get("reply") or "")
            if not reply:
                reply = "Hermi Gateway 没有返回内容。"
        except Exception as exc:
            audit_logger.log_error(event, exc)
            reply = "我这边调用 Hermi Gateway 出错了，稍后再试。"
        send_reply(event, onebot_client, reply)
        audit_logger.log_outbound(event, sender, reply)
        return {"ok": True, "blocked": False, "reply": reply, "transport": "hermi"}

    messages = build_hermes_messages(
        event,
        sender,
        risk,
        session_id=session_id,
        session_key=session_key,
        auto_image_vision=bool(getattr(config, "auto_image_vision", False)),
    )
    stream_dispatcher = StreamingQQReplyDispatcher(event, onebot_client)
    use_runs_api = _should_use_runs_api(event, sender, risk, bridge_enabled)

    try:
        if use_runs_api:
            runs_client = runs_client or _make_runs_client(config)
            approval_seen = False

            def approval_handler(run_id: str, approval_event: dict[str, object]) -> str:
                nonlocal approval_seen
                approval_seen = True
                stream_dispatcher.flush_remaining()
                approval_bridge.record_pending(session_id, run_id, event, sender, approval_event, session_key)
                prompt = approval_bridge.format_approval_prompt(approval_event)
                send_reply(event, onebot_client, prompt)
                audit_logger._write(
                    "approval",
                    {
                        "event": "approval_request_sent",
                        "session_id": session_id,
                        "run_id": run_id,
                        "user_id": sender.user_id,
                        "approval": approval_event,
                    },
                )
                choice = approval_bridge.wait_for_decision(session_id)
                if choice is None:
                    choice = "deny"
                    send_reply(event, onebot_client, "审批等待超时，已自动拒绝。")
                    audit_logger._write(
                        "approval",
                        {"event": "approval_timeout", "session_id": session_id, "run_id": run_id},
                    )
                approval_bridge.clear_pending(session_id)
                audit_logger._write(
                    "approval",
                    {"event": "approval_choice_sent", "session_id": session_id, "run_id": run_id, "choice": choice},
                )
                return choice

            try:
                reply = runs_client.chat_with_approval(
                    messages,
                    session_key=session_key,
                    session_id=session_id,
                    approval_handler=approval_handler,
                    on_stream_event=stream_dispatcher.handle_event,
                )
            except Exception:
                if approval_seen or stream_dispatcher.sent_any:
                    raise
                reply = _call_hermes_chat(
                    hermes_client,
                    messages,
                    session_key=session_key,
                    session_id=session_id,
                    on_stream_event=stream_dispatcher.handle_event,
                )
        else:
            reply = _call_hermes_chat(
                hermes_client,
                messages,
                session_key=session_key,
                session_id=session_id,
                on_stream_event=stream_dispatcher.handle_event,
            )
    except Exception as exc:
        audit_logger.log_error(event, exc)
        reply = "我这边调用 Hermes 出错了，稍后再试。"

    if stream_dispatcher.seen_stream_content:
        stream_dispatcher.flush_remaining()
    else:
        send_reply(event, onebot_client, reply)
    audit_logger.log_outbound(event, sender, reply)
    return {"ok": True, "blocked": False, "reply": reply, "transport": "runs" if use_runs_api else "chat"}
