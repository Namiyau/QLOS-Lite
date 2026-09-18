# QLOS-Lite QQ to Hermes System Overview

Last updated: 2026-07-03

This document describes the current QQ/NapCat/QLOS-Lite/Hermes integration so another AI or engineer can understand the system, inspect it, and propose follow-up plans. Secrets and API keys are intentionally omitted.

## Purpose

QLOS-Lite is a thin QQ safety gateway for Hermes.

It does not replace Hermes as the main agent. Hermes remains responsible for personality, memory, skills, tool use, file analysis, and task execution. QLOS-Lite only handles QQ transport, sender identity, risk gating, QQ-specific prompt shaping, reply delivery, and audit logs.

Core principle:

```text
QQ chat permission is not host control permission.
Only configured OWNER_QQ_ID is owner.
All other QQ senders are non-owner contacts.
```

## Runtime Chain

```text
QQ user
  -> NapCat / OneBot
  -> QLOS-Lite HTTP server
  -> Hermes Gateway API
  -> Hermes agent / tools / memory / skills
  -> Hermes reply
  -> QLOS-Lite reply splitter and QQ sanitizer
  -> OneBot send_private_msg / send_group_msg
  -> QQ
```

Current local ports:

```text
NapCat OneBot API: 127.0.0.1:3000
QLOS-Lite event receiver: 127.0.0.1:8766
Hermes Gateway API: 127.0.0.1:8642
```

Current IDs:

```text
Owner QQ: 1000000001
Bot QQ: 1000000002
Allowed group: 2000000001
```

## Main Components

QLOS-Lite source:

```text
qlos_lite/
  config.py
  models.py
  onebot_server.py
  onebot_client.py
  identity.py
  risk.py
  prompt_builder.py
  hermes_client.py
  logger.py
  router.py
  identity_sidecar.py
```

Hermes tool guard plugin:

```text
插件/qlos-tool-guard/
  plugin.yaml
  __init__.py
  install.ps1
  README.md
```

Default installed plugin location:

```text
%LOCALAPPDATA%\hermes\plugins\qlos-tool-guard
```

Start/stop scripts:

```text
scripts/start_qlos_stack.ps1
scripts/stop_qlos_stack.ps1
Start_QLOS_Stack.bat
Stop_QLOS_Stack.bat
Start_QLOS_Lite.bat
```

## Event Handling

QLOS-Lite receives OneBot events at:

```text
POST /onebot/event
```

The server parses message events into `QQMessageEvent`:

```text
message_id
chat_type: private | group
user_id
nickname
raw_message
text
group_id
is_at_bot
attachments
```

Group handling:

```text
private chat -> always process
group chat -> process only if group enabled, group whitelisted, and bot mentioned when require_at_in_group=true
```

## Identity Model

Identity is hard-coded by QQ ID.

```text
event.user_id == QLOS_OWNER_QQ_ID -> owner
everything else -> non-owner
```

Nicknames, display names, and claims like "I am the owner" are ignored.

Owner permission:

```text
owner
```

Non-owner private permission:

```text
social chat + sandbox task only; no host shell, no private file access, no core memory/personality/config changes
```

Non-owner group permission:

```text
group social chat + sandbox task only; no host shell, no private file access, no core memory/personality/config changes
```

## Risk Gate

QLOS-Lite has a lightweight keyword risk classifier.

High-risk examples:

```text
rm -rf
powershell
cmd.exe
execute command
delete files
.env
token
cookie
password
read owner files
modify personality / SOUL
disable approval
enable YOLO
proactive private messaging
```

Behavior:

```text
non-owner high-risk request -> blocked by QLOS-Lite, Hermes not called
owner high-risk request -> passed to Hermes, Hermes safety/approval still applies
medium-risk file/code/PPT request -> passed to Hermes with sandbox-only permission for non-owner
normal chat -> passed to Hermes
```

## Hermes Prompt

QLOS-Lite sends Hermes a short per-message user prefix:

```text
[QLOS-Lite]
source=QQ/NapCat/OneBot
chat=private
session_id=qlos-qq-dm-1000000001
session_key=qlos:qq:dm:1000000001
sender_qq=1000000001
role=owner
permission=owner
risk=L0 normal chat

[user_message]
...
```

The system prompt is QQ-specific and only appears for messages routed through QLOS-Lite. Hermes Desktop / local CLI sessions do not receive this QQ prompt.

Current QQ reply rules:

```text
Reply through QQ, naturally and orally.
Split only when meaning and length make splitting useful.
Prefer 2-3 messages.
Keep one connected idea in one message.
Do not split every sentence.
If splitting, use:
<<<QLOS_SPLIT>>>
Professional, code, command, config, long step, or structured answer: do not split.
QQ does not render Markdown well.
Use plain text only.
No tables, Markdown headings, bold markers, bullet styling, numbered-list styling, horizontal rules, or pipe tables.
Emoji and kaomoji are allowed.
```

## Session Handling

Hermes receives two stable headers:

```text
X-Hermes-Session-Id
X-Hermes-Session-Key
```

Session ID controls transcript/session continuity:

```text
private: qlos-qq-dm:<sender>
group: qlos-qq-group:<group>:user:<sender>
```

Session key controls long-term memory scope:

```text
private: qlos:qq:dm:<sender>
group: qlos:qq:group:<group>:user:<sender>
```

This prevents every QQ message from becoming an unrelated Hermes conversation and keeps memory scoped by QQ sender/group context.

## Tool Guard Plugin

The Hermes plugin `qlos-tool-guard` registers a `pre_tool_call` hook.

It blocks these tools for non-owner QLOS sessions:

```text
write_file
patch
terminal
process
```

It reads sender identity from:

```text
state/qlos_lite/session_identity.jsonl
```

Optional relative override:

```text
QLOS_TOOL_GUARD_IDENTITY_FILE=state/qlos_lite/session_identity.jsonl
```

QLOS-Lite writes identity records before calling Hermes:

```json
{
  "session_id": "qlos-qq-dm-1000000001",
  "session_key": "qlos:qq:dm:1000000001",
  "user_id": "1000000001",
  "role": "owner",
  "is_owner": true,
  "permission": "owner",
  "expires_at": 1783052577.23
}
```

If the plugin cannot find a valid identity record, it defaults to non-owner for QLOS sessions.

## QQ Reply Splitting

QLOS-Lite reply behavior:

```text
If Hermes returns <<<QLOS_SPLIT>>>:
  split exactly on markers.
  no hard cap.

If Hermes returns no marker:
  QLOS-Lite may auto-split short casual sentence-like replies.
  short adjacent sentences are grouped into natural chunks.
  structured/code/command/table-like text is not auto-split.
```

Send interval:

```text
base = random.uniform(1, 7.5)
short message -> slightly shorter delay
long message -> slightly longer delay
final clamp: 1 to 7.5 seconds
```

## QQ Output Sanitization

Before sending to QQ, QLOS-Lite:

```text
trims whitespace
limits long replies to 1800 chars
hides known secret markers
removes common Markdown formatting
```

Examples:

```text
**bold** -> bold
*soft* -> soft
# Title -> Title
- item -> item
| table | -> table text without pipes
table separator lines -> removed
```

This is necessary because QQ does not render Markdown like Hermes Desktop; raw symbols become visual noise.

## Logs And Debugging

QLOS-Lite logs:

```text
logs/qlos_lite/inbound.jsonl
logs/qlos_lite/outbound.jsonl
logs/qlos_lite/blocked.jsonl
logs/qlos_lite/errors.jsonl
logs/qlos_lite/gateway.jsonl
logs/qlos_lite/gateway_http.jsonl
```

Hermes process logs:

```text
state/hermes_gateway.out.log
state/hermes_gateway.err.log
```

QLOS-Lite process logs:

```text
state/qlos_lite.out.log
state/qlos_lite.err.log
```

Useful checks:

```powershell
Get-Content .\logs\qlos_lite\outbound.jsonl -Tail 20
Get-Content .\logs\qlos_lite\inbound.jsonl -Tail 20
Get-Content .\state\qlos_lite\session_identity.jsonl -Tail 5
```

Port checks:

```text
3000 -> NapCat
8766 -> QLOS-Lite
8642 -> Hermes Gateway
```

## Current Verified State

As of this document:

```text
QLOS-Lite tests pass.
Tool guard plugin tests pass.
QLOS-Lite process runs as python -m qlos_lite.onebot_server.
QLOS-Lite port 8766 is open.
Hermes gateway is expected on port 8642.
NapCat is expected on port 3000.
```

Recent verification command:

```powershell
python -m pytest tests\test_qlos_lite_prompt.py tests\test_qlos_lite_router.py tests\test_qlos_tool_guard_plugin.py -q
```

## Known Issues / Watch Items

1. Hermes may still produce Markdown-like text. QLOS-Lite now cleans common patterns, but prompt tuning may still be needed.
2. Hermes may overuse split markers if prompt is too aggressive. The current prompt says prefer 2-3 and do not split every sentence.
3. Gateway logs show occasional DeepSeek connection retries. These recover but may delay replies.
4. Auxiliary providers may be unhealthy if OpenRouter credit or Nous auth is missing. This can affect vision, compression, web extraction, title generation, and other auxiliary tasks.
5. Browser/image/web tools may be unavailable until their providers/API keys are configured.
6. Logs contain message content. They should not contain API keys, but they may contain private chat text.

## Recommended Next Plans

Short-term:

```text
1. Keep QLOS-Lite thin.
2. Continue tuning QQ prompt style from real outbound logs.
3. Add a diagnostic command or small script that prints current service health.
4. Add a "trace one QQ message" tool that links inbound -> Hermes call -> outbound -> OneBot send result.
```

Medium-term:

```text
1. Move QQ style rules into a Hermes skill if Hermes reliably loads it only for QQ sessions.
2. Keep hard security in plugin/hooks, not prompt text.
3. Add richer non-owner sandbox task handling.
4. Add optional owner-only proactive messaging via cron/webhook/event triggers.
```

Long-term:

```text
1. Build a small observability dashboard for QLOS-Lite logs and message trace.
2. Add per-contact social memory policy and review.
3. Add safe event-triggered proactive messages.
4. Add configurable reply style profiles for private/group chats.
```

## Boundary Summary

QLOS-Lite:

```text
identity
permission prefix
risk gate
session headers
QQ prompt
reply splitting
QQ output sanitization
logging
```

Hermes:

```text
main reasoning
personality
memory
skills
tools
file analysis
sandbox work
approvals
```

Hermes plugin:

```text
hard pre-tool-call authorization for QLOS sessions
```

