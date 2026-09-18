from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ChatType = Literal["private", "group"]
SenderRole = str
RiskLevel = Literal["L0", "L1", "L2", "L2_SANDBOX_ONLY", "L3", "L4", "L5"]


@dataclass
class QQMessageEvent:
    message_id: str
    chat_type: ChatType
    user_id: str
    nickname: str | None
    raw_message: str
    text: str
    group_id: str | None = None
    is_at_bot: bool = False
    attachments: list[str] | None = None


@dataclass
class SenderContext:
    user_id: str
    nickname: str | None
    role: SenderRole
    is_owner: bool
    permission: str


@dataclass
class RiskDecision:
    risk: RiskLevel
    blocked: bool
    reason: str
    safe_reply: str | None = None
