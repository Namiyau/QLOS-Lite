# QLOS-Lite — QQ / OneBot Safety Gateway

[简体中文](README.md) | English | [日本語](README.ja.md)

QLOS-Lite is a thin safety gateway between QQ/OneBot and Hermes. It handles sender identity, group rules, risk checks, attachment metadata, persistent queues, audit logs, and reply delivery.

## Features

* Owner, friend, group, and blocked-role routing.
* QQ-specific prompt shaping and split markers.
* Attachment metadata and private media references.
* Persistent message queue with deduplication.
* Hermes Gateway and Hermi Gateway clients.
* Approval bridge, diagnostics, trace, and tool-guard integration.

## Build and run

Install Python 3.11+, external NapCatQQ, and Hermes Agent/Gateway:

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
python -m qlos_lite.onebot_server
```

Set `NAPCAT_ROOT` or pass `-NapCatDir` to the stack launcher. NapCatQQ binaries and login state are not included.

## Configuration

Copy `.env.example` and `secrets.local.env.example` to local files. Copy `roles.example.json` to `roles.json`. Keep real QQ IDs, tokens, media, queues, and logs outside Git.

## Architecture

```text
QQ -> NapCatQQ/OneBot -> QLOS-Lite :8766 -> Hermi :8789 -> Hermes :8642
```

Hermi is optional. When enabled, it becomes the unified session, permission, quota, and approval layer.

## Dependencies

Required: Python and an external Hermes Gateway. NapCatQQ is the external QQ/OneBot adapter. Hermi is an optional local gateway.

## License

No open-source license has been selected for this project yet.
