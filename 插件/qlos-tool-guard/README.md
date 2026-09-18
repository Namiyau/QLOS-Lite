# QLOS Tool Guard

Hermes plugin. Registers `pre_tool_call` and blocks high-risk tools when the QLOS sender is not verified owner.

## Blocks For Non-Owner

- `write_file`
- `patch`
- `terminal`
- `process`

## Identity Contract

QLOS-Lite should write JSONL records to:

```text
state/qlos_lite/session_identity.jsonl
```

Each record:

```json
{
  "session_id": "qlos-qq-dm-1000000001",
  "session_key": "qlos:qq:dm:1000000001",
  "user_id": "1000000001",
  "role": "owner",
  "is_owner": true,
  "permission": "owner",
  "ts": 1782980000,
  "expires_at": 1782980600
}
```

If identity is missing, unreadable, expired, or not owner, QLOS sessions are treated as non-owner.

## Scope

Default scope only enforces sessions whose `session_id` starts with `qlos-` or `qlos:`.

Set this to enforce all Hermes sessions:

```powershell
$env:QLOS_TOOL_GUARD_ENFORCE_ALL="true"
```

## Install

Copy this folder to:

```text
%HERMES_HOME%\plugins\qlos-tool-guard
```

If `HERMES_HOME` is unset, use `%USERPROFILE%\.hermes\plugins\qlos-tool-guard`.

Then enable:

```powershell
hermes plugins enable qlos-tool-guard
```

Restart Hermes gateway.

