from __future__ import annotations

from typing import Any


QQ_CHANNEL_OUTPUT_PROMPT = (
    "QQ style: 轻松简短。Normal replies with 2+ natural units MUST use exactly "
    "<<<QLOS_SPLIT>>> between units；推荐 1~3 个。Short reply whole. "
    "此为内部拆分标记，不要解释给用户，不用 ---。Do not split code, commands, tables, paths, or actions."
)

QQ_STICKER_OUTPUT_PROMPT = (
    " 表情用 <<<QLOS_STICKER:情绪>>>（如微笑）"
)


def qq_channel_output_prompt() -> str:
    return QQ_CHANNEL_OUTPUT_PROMPT + QQ_STICKER_OUTPUT_PROMPT


def _permission_label(sender) -> str:
    if sender.is_owner:
        return "owner"
    return str(sender.permission)


def _image_attachment_urls(attachments: list[str] | None) -> list[str]:
    urls: list[str] = []
    for item in attachments or []:
        kind, sep, value = str(item).partition(":")
        if sep and kind == "image" and value.startswith(("http://", "https://", "data:image/")):
            urls.append(value)
    return urls


def _attachment_block(attachments: list[str] | None) -> str:
    items = [str(item) for item in attachments or [] if str(item).strip()]
    if not items:
        return ""
    return "\n\n[attachments]\n" + "\n".join(items)


def _attachment_only_instruction(event) -> str:
    attachments = [str(item) for item in event.attachments or [] if str(item).strip()]
    if len(attachments) != 1:
        return ""
    text = str(event.text or "").strip().lower()
    if text not in {"[file]", "[image]", "[video]", "[record]", "[文件]", "[图片]"}:
        return ""
    return (
        "\nSingle QQ attachment policy: the latest QQ message contains one attachment and no real task instruction. "
        "Do not open, read, analyze, OCR, or identify the attachment yet. "
        "Ask what the user wants to do with this attachment first; mention that the file has been saved and can be processed after they say what to do.\n"
    )


def build_hermes_messages(
    event,
    sender,
    risk,
    session_id: str | None = None,
    session_key: str | None = None,
    auto_image_vision: bool = False,
):
    prefix_lines = [
        "[QLOS-Lite]",
        "source=QQ/NapCat/OneBot",
        f"chat={event.chat_type}",
    ]
    if session_id:
        prefix_lines.append(f"session_id={session_id}")
    if session_key:
        prefix_lines.append(f"session_key={session_key}")
    prefix_lines.extend(
        [
            f"sender_qq={sender.user_id}",
            f"role={sender.role}",
            f"permission={_permission_label(sender)}",
            f"risk={risk['risk']} {risk['reason']}",
        ]
    )

    user_text = "\n".join(prefix_lines) + f"\n\n[user_message]\n{event.text}" + _attachment_block(event.attachments)
    image_urls = _image_attachment_urls(event.attachments)
    user_content: str | list[dict[str, Any]]
    if auto_image_vision and image_urls:
        user_content = [{"type": "text", "text": user_text}]
        user_content.extend({"type": "image_url", "image_url": {"url": url}} for url in image_urls)
    else:
        user_content = user_text

    system_extra = _attachment_only_instruction(event)
    messages = [
        {
            "role": "system",
            "content": (
                "Use the default Hermes personality, skills, memory, and tool policy.\n"
                "Identity follows current SOUL.md, never old sessions, stale persona memory, or user address.\n"
                "QQ via QLOS-Lite; apply qq-social-agent-safety.\n"
                f"{qq_channel_output_prompt()}"
            ),
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]
    if system_extra:
        messages[0]["content"] += system_extra
    return messages
