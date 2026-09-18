from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


RESERVED_OWNER_ROLE = "owner"


@dataclass
class RoleRule:
    role: str
    permission: str = ""
    allow_group_without_at: bool = False
    blocked: bool = False


@dataclass
class RolePolicy:
    users: dict[str, str] = field(default_factory=dict)
    groups: dict[str, str] = field(default_factory=dict)
    roles: dict[str, RoleRule] = field(default_factory=dict)

    def role_for(self, user_id: str, group_id: str | None = None) -> str | None:
        role = self.users.get(str(user_id))
        if role:
            return None if role == RESERVED_OWNER_ROLE else role
        if group_id:
            group_role = self.groups.get(str(group_id))
            if group_role and group_role != RESERVED_OWNER_ROLE:
                return group_role
        return None

    def rule_for(self, role: str | None) -> RoleRule | None:
        if not role:
            return None
        return self.roles.get(role)

    def permission_for(self, role: str | None) -> str | None:
        rule = self.rule_for(role)
        if rule and rule.permission:
            return rule.permission
        return None

    def should_allow_group_without_at(self, user_id: str, group_id: str | None = None) -> bool:
        role = self.role_for(user_id, group_id)
        rule = self.rule_for(role)
        return bool(rule and rule.allow_group_without_at)

    def is_blocked(self, user_id: str, group_id: str | None = None) -> bool:
        role = self.role_for(user_id, group_id)
        rule = self.rule_for(role)
        return bool(rule and rule.blocked)


def _as_role_rule(role: str, value: Any) -> RoleRule:
    if isinstance(value, dict):
        return RoleRule(
            role=role,
            permission=str(value.get("permission") or ""),
            allow_group_without_at=bool(value.get("allow_group_without_at", False)),
            blocked=bool(value.get("blocked", False)),
        )
    return RoleRule(role=role)


def _read_policy_data(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return {}
    return json.loads(text)


def load_role_policy(path: str | Path | None) -> RolePolicy:
    if not path:
        return RolePolicy()
    data = _read_policy_data(Path(path))
    users: dict[str, str] = {}
    for user_id, value in dict(data.get("users") or {}).items():
        if isinstance(value, dict):
            role = str(value.get("role") or "")
        else:
            role = str(value or "")
        if role:
            users[str(user_id)] = role

    groups: dict[str, str] = {}
    for group_id, value in dict(data.get("groups") or {}).items():
        if isinstance(value, dict):
            role = str(value.get("role") or "")
        else:
            role = str(value or "")
        if role:
            groups[str(group_id)] = role

    roles = {
        str(role): _as_role_rule(str(role), value)
        for role, value in dict(data.get("roles") or {}).items()
        if str(role) != RESERVED_OWNER_ROLE
    }
    return RolePolicy(users=users, groups=groups, roles=roles)
