from __future__ import annotations

import json
from pathlib import Path

from qlos_lite.diagnostics import collect_doctor_report, collect_trace, format_doctor_report, format_trace_report


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_collect_trace_links_message_across_logs(tmp_path):
    log_dir = tmp_path / "logs" / "qlos_lite"
    state_dir = tmp_path / "state"
    write_jsonl(
        log_dir / "inbound.jsonl",
        [
            {"ts": "2026-07-05T01:00:00+00:00", "message_id": "m1", "text": "hello", "sender_role": "owner"},
            {"ts": "2026-07-05T01:01:00+00:00", "message_id": "m2", "text": "skip"},
        ],
    )
    write_jsonl(
        log_dir / "outbound.jsonl",
        [{"ts": "2026-07-05T01:00:03+00:00", "message_id": "m1", "reply": "hi"}],
    )
    write_jsonl(
        log_dir / "gateway_http.jsonl",
        [{"ts": "2026-07-05T01:00:01+00:00", "message_id": "m1", "status": 200}],
    )

    trace = collect_trace("m1", log_dir=log_dir, state_dir=state_dir)

    assert trace["message_id"] == "m1"
    assert [item["source"] for item in trace["events"]] == ["inbound", "gateway_http", "outbound"]
    assert "hello" in format_trace_report(trace)
    assert "hi" in format_trace_report(trace)


def test_collect_trace_can_use_user_id_and_text_when_message_id_unknown(tmp_path):
    log_dir = tmp_path / "logs" / "qlos_lite"
    state_dir = tmp_path / "state"
    write_jsonl(
        log_dir / "inbound.jsonl",
        [
            {"ts": "2026-07-05T01:00:00+00:00", "message_id": "m1", "user_id": "u1", "text": "alpha"},
            {"ts": "2026-07-05T01:01:00+00:00", "message_id": "m2", "user_id": "u2", "text": "beta"},
        ],
    )

    trace = collect_trace(None, user_id="u2", text_contains="bet", log_dir=log_dir, state_dir=state_dir)

    assert trace["message_id"] == "m2"
    assert trace["events"][0]["record"]["text"] == "beta"


def test_collect_doctor_report_checks_ports_files_and_recent_errors(tmp_path):
    root = tmp_path
    log_dir = root / "logs" / "qlos_lite"
    state_dir = root / "state"
    write_jsonl(log_dir / "errors.jsonl", [{"ts": "2026-07-05T01:00:00+00:00", "message_id": "m1", "error": "boom"}])
    (state_dir / "hermes_gateway.err.log").parent.mkdir(parents=True, exist_ok=True)
    (state_dir / "hermes_gateway.err.log").write_text("Gemini HTTP 404\n", encoding="utf-8")

    report = collect_doctor_report(root=root, ports=[1], http_checks=[])

    assert report["paths"]["log_dir"]["exists"] is True
    assert report["ports"][0]["port"] == 1
    assert report["ports"][0]["listening"] is False
    assert report["recent_errors"]["qlos_errors"]
    formatted = format_doctor_report(report)
    assert "QLOS doctor" in formatted
    assert "Gemini HTTP 404" in formatted
