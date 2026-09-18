from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_DIR = ROOT / "logs" / "qlos_lite"
DEFAULT_STATE_DIR = ROOT / "state"
TRACE_LOGS = ("inbound", "gateway_http", "gateway", "approval", "blocked", "errors", "outbound")


def _read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if limit is not None:
        lines = lines[-limit:]
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def _sort_key(item: dict[str, Any]) -> str:
    return str(item.get("ts") or "")


def _short(value: Any, max_len: int = 220) -> str:
    text = str(value)
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _record_matches(record: dict[str, Any], message_id: str) -> bool:
    return str(record.get("message_id") or "") == str(message_id)


def _find_message_id(log_dir: Path, user_id: str | None, text_contains: str | None) -> str | None:
    for row in reversed(_read_jsonl(log_dir / "inbound.jsonl", limit=5000)):
        if user_id and str(row.get("user_id") or "") != str(user_id):
            continue
        if text_contains and text_contains not in str(row.get("text") or ""):
            continue
        message_id = row.get("message_id")
        if message_id is not None:
            return str(message_id)
    return None


def collect_trace(
    message_id: str | None,
    *,
    user_id: str | None = None,
    text_contains: str | None = None,
    log_dir: str | Path = DEFAULT_LOG_DIR,
    state_dir: str | Path = DEFAULT_STATE_DIR,
) -> dict[str, Any]:
    log_path = Path(log_dir)
    state_path = Path(state_dir)
    resolved_id = str(message_id) if message_id else _find_message_id(log_path, user_id, text_contains)
    events: list[dict[str, Any]] = []
    if resolved_id:
        for source in TRACE_LOGS:
            for record in _read_jsonl(log_path / f"{source}.jsonl", limit=10000):
                if _record_matches(record, resolved_id):
                    events.append({"source": source, "ts": record.get("ts"), "record": record})
    events.sort(key=_sort_key)
    return {
        "message_id": resolved_id,
        "log_dir": str(log_path),
        "state_dir": str(state_path),
        "events": events,
        "found": bool(events),
    }


def format_trace_report(trace: dict[str, Any]) -> str:
    lines = [f"QLOS trace message_id={trace.get('message_id') or 'NOT_FOUND'}"]
    if not trace.get("events"):
        lines.append("No matching QLOS log events.")
        return "\n".join(lines)
    for item in trace["events"]:
        record = item["record"]
        parts = [
            f"[{item['source']}]",
            str(record.get("ts") or ""),
            f"role={record.get('sender_role', '')}",
            f"risk={record.get('risk', '')}",
        ]
        if record.get("text"):
            parts.append(f"text={_short(record.get('text'))}")
        if record.get("reply"):
            parts.append(f"reply={_short(record.get('reply'))}")
        if record.get("error"):
            parts.append(f"error={_short(record.get('error'))}")
        if record.get("status"):
            parts.append(f"status={record.get('status')}")
        lines.append(" ".join(part for part in parts if part))
    return "\n".join(lines)


def _port_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_check(url: str, timeout: float = 2.0) -> dict[str, Any]:
    try:
        request = Request(url, headers={"User-Agent": "qlos-doctor/0.1"})
        with urlopen(request, timeout=timeout) as response:
            return {"url": url, "ok": 200 <= response.status < 400, "status": response.status}
    except URLError as exc:
        return {"url": url, "ok": False, "error": str(exc.reason)}
    except Exception as exc:
        return {"url": url, "ok": False, "error": str(exc)}


def _tail_matching(path: Path, patterns: tuple[str, ...], limit: int = 20) -> list[str]:
    if not path.exists():
        return []
    matches = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if any(pattern in line for pattern in patterns):
            matches.append(line)
    return matches[-limit:]


def _env_file_keys(path: Path) -> dict[str, bool]:
    if not path.exists():
        return {}
    keys: dict[str, bool] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        keys[key.strip()] = bool(value.strip())
    return keys


def collect_doctor_report(
    *,
    root: str | Path = ROOT,
    ports: list[int] | None = None,
    http_checks: list[str] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    log_dir = root_path / "logs" / "qlos_lite"
    state_dir = root_path / "state"
    media_dir = root_path / "state" / "media"
    queue_dir = root_path / "state" / "qlos_lite" / "queue"
    roles_file = root_path / "roles.json"
    ports = ports or [3000, 8642, 8766]
    if http_checks is None:
        http_checks = ["http://127.0.0.1:8642/health"]

    config_keys = _env_file_keys(root_path / "secrets.local.env")
    required_keys = ["QLOS_OWNER_QQ_ID", "QLOS_BOT_QQ_ID", "QLOS_HERMES_API_KEY", "QLOS_ONEBOT_BASE_URL"]
    qlos_errors = _read_jsonl(log_dir / "errors.jsonl", limit=5)
    stderr_patterns = ("ERROR", "Traceback", "Exception", "Gemini HTTP", "Connection error")
    hermes_stderr = _tail_matching(state_dir / "hermes_gateway.err.log", stderr_patterns)
    qlos_stderr = _tail_matching(state_dir / "qlos_lite.err.log", stderr_patterns)

    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "root": str(root_path),
        "paths": {
            "log_dir": {"path": str(log_dir), "exists": log_dir.exists()},
            "state_dir": {"path": str(state_dir), "exists": state_dir.exists()},
            "media_dir": {"path": str(media_dir), "exists": media_dir.exists(), "optional": True},
            "queue_dir": {"path": str(queue_dir), "exists": queue_dir.exists(), "optional": True},
            "roles.json": {"path": str(roles_file), "exists": roles_file.exists(), "optional": True},
            "secrets.local.env": {"path": str(root_path / "secrets.local.env"), "exists": (root_path / "secrets.local.env").exists()},
        },
        "config": {
            key: {"present": key in config_keys, "has_value": bool(config_keys.get(key))}
            for key in required_keys
        },
        "ports": [{"port": port, "listening": _port_listening(port)} for port in ports],
        "http": [_http_check(url) for url in http_checks],
        "recent_errors": {
            "qlos_errors": qlos_errors,
            "hermes_stderr": hermes_stderr,
            "qlos_stderr": qlos_stderr,
        },
    }


def format_doctor_report(report: dict[str, Any]) -> str:
    lines = [f"QLOS doctor {report.get('ts', '')}", f"root={report.get('root', '')}"]
    lines.append("paths:")
    for name, item in report.get("paths", {}).items():
        state = "OK" if item.get("exists") else ("ABSENT" if item.get("optional") else "MISSING")
        lines.append(f"  {state} {name}: {item.get('path')}")
    lines.append("config:")
    for key, item in report.get("config", {}).items():
        state = "OK" if item.get("present") and item.get("has_value") else "MISSING"
        lines.append(f"  {state} {key}")
    lines.append("ports:")
    for item in report.get("ports", []):
        state = "OPEN" if item.get("listening") else "CLOSED"
        lines.append(f"  {state} {item.get('port')}")
    lines.append("http:")
    for item in report.get("http", []):
        state = "OK" if item.get("ok") else "FAIL"
        detail = item.get("status") or item.get("error") or ""
        lines.append(f"  {state} {item.get('url')} {detail}")
    recent = report.get("recent_errors", {})
    lines.append("recent errors:")
    qlos_errors = recent.get("qlos_errors") or []
    lines.append(f"  qlos_errors={len(qlos_errors)}")
    for row in qlos_errors[-3:]:
        lines.append(f"    {row.get('ts', '')} {row.get('message_id', '')} {_short(row.get('error', row))}")
    for name in ("hermes_stderr", "qlos_stderr"):
        rows = recent.get(name) or []
        lines.append(f"  {name}={len(rows)}")
        for row in rows[-3:]:
            lines.append(f"    {_short(row)}")
    return "\n".join(lines)


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m qlos_lite.diagnostics")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--root", default=str(ROOT))
    trace = sub.add_parser("trace")
    trace.add_argument("message_id", nargs="?")
    trace.add_argument("--user-id")
    trace.add_argument("--text")
    trace.add_argument("--json", action="store_true")
    trace.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)

    if args.command == "doctor":
        report = collect_doctor_report(root=args.root)
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_doctor_report(report))
        return 0

    root = Path(args.root)
    report = collect_trace(
        args.message_id,
        user_id=args.user_id,
        text_contains=args.text,
        log_dir=root / "logs" / "qlos_lite",
        state_dir=root / "state",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_trace_report(report))
    return 0 if report.get("found") else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
