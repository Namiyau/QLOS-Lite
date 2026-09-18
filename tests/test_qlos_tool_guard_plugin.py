from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path


PLUGIN_PATH = Path(__file__).resolve().parents[1] / "插件" / "qlos-tool-guard" / "__init__.py"


def load_plugin():
    spec = importlib.util.spec_from_file_location("qlos_tool_guard_test", PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def write_identity(path: Path, **record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def test_non_owner_qlos_session_blocks_terminal(monkeypatch, tmp_path):
    plugin = load_plugin()
    identity_file = tmp_path / "identity.jsonl"
    monkeypatch.setenv("QLOS_TOOL_GUARD_IDENTITY_FILE", str(identity_file))
    write_identity(
        identity_file,
        session_id="qlos-qq-dm-222222",
        role="friend",
        is_owner=False,
        ts=time.time(),
    )

    result = plugin.pre_tool_call(tool_name="terminal", session_id="qlos-qq-dm-222222", args={})

    assert result["action"] == "block"
    assert "not verified owner" in result["message"]


def test_owner_qlos_session_allows_patch(monkeypatch, tmp_path):
    plugin = load_plugin()
    identity_file = tmp_path / "identity.jsonl"
    monkeypatch.setenv("QLOS_TOOL_GUARD_IDENTITY_FILE", str(identity_file))
    write_identity(
        identity_file,
        session_id="qlos-qq-dm-1000000001",
        role="owner",
        is_owner=True,
        ts=time.time(),
    )

    assert plugin.pre_tool_call(tool_name="patch", session_id="qlos-qq-dm-1000000001", args={}) is None


def test_missing_identity_defaults_non_owner_for_qlos_session(monkeypatch, tmp_path):
    plugin = load_plugin()
    monkeypatch.setenv("QLOS_TOOL_GUARD_IDENTITY_FILE", str(tmp_path / "missing.jsonl"))

    result = plugin.pre_tool_call(tool_name="write_file", session_id="qlos-qq-dm-1000000001", args={})

    assert result["action"] == "block"


def test_non_qlos_session_not_enforced_by_default(monkeypatch, tmp_path):
    plugin = load_plugin()
    monkeypatch.setenv("QLOS_TOOL_GUARD_IDENTITY_FILE", str(tmp_path / "missing.jsonl"))
    monkeypatch.delenv("QLOS_TOOL_GUARD_ENFORCE_ALL", raising=False)

    assert plugin.pre_tool_call(tool_name="terminal", session_id="local-desktop-session", args={}) is None


def test_enforce_all_treats_missing_identity_as_non_owner(monkeypatch, tmp_path):
    plugin = load_plugin()
    monkeypatch.setenv("QLOS_TOOL_GUARD_IDENTITY_FILE", str(tmp_path / "missing.jsonl"))
    monkeypatch.setenv("QLOS_TOOL_GUARD_ENFORCE_ALL", "true")

    result = plugin.pre_tool_call(tool_name="process", session_id="local-desktop-session", args={})

    assert result["action"] == "block"

