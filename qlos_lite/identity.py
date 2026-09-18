from __future__ import annotations

from .models import QQMessageEvent, SenderContext
from .roles import RolePolicy


def classify_sender(event: QQMessageEvent, owner_qq_id: str, role_policy: RolePolicy | None = None) -> SenderContext:
    user_id = str(event.user_id)

    if user_id == str(owner_qq_id):
        return SenderContext(
            user_id=user_id,
            nickname=event.nickname,
            role="owner",
            is_owner=True,
            permission="owner: full control, subject to Hermes safety approvals",
        )

    if role_policy:
        role = role_policy.role_for(user_id, event.group_id)
        permission = role_policy.permission_for(role)
        if role and permission:
            return SenderContext(
                user_id=user_id,
                nickname=event.nickname,
                role=role,
                is_owner=False,
                permission=permission,
            )

    if event.chat_type == "private":
        return SenderContext(
            user_id=user_id,
            nickname=event.nickname,
            role="friend",
            is_owner=False,
            permission=(
                "social chat + sandbox task only; no host shell, no private file access, "
                "no core memory/personality/config changes"
            ),
        )

    return SenderContext(
        user_id=user_id,
        nickname=event.nickname,
        role="group_member",
        is_owner=False,
        permission=(
            "group social chat + sandbox task only; no host shell, no private file access, "
            "no core memory/personality/config changes"
        ),
    )
