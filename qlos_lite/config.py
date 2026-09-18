from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_SECRET_ENV = ROOT / "secrets.local.env"
DOTENV_LOCAL = ROOT / ".env.local"
DOTENV = ROOT / ".env"


def default_media_dir() -> Path:
    return Path.home() / "Documents" / "Hermi资料"


def load_local_secret_env(path: str | Path | None = None) -> None:
    paths = [Path(path)] if path else [LOCAL_SECRET_ENV, DOTENV_LOCAL, DOTENV]
    for env_path in paths:
        _load_one_env_file(env_path)


def _load_one_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _csv_env(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return default


@dataclass
class QLOSLiteConfig:
    owner_qq_id: str
    enable_group: bool = True
    allowed_group_ids: list[str] = field(default_factory=list)
    require_at_in_group: bool = True
    hermes_api_url: str = "http://127.0.0.1:8642/v1/chat/completions"
    hermes_api_key: str = ""
    bot_qq_id: str = ""
    bot_names: list[str] = field(default_factory=lambda: ["Memory\u00b0", "Qiling", "QLOS"])
    onebot_base_url: str = "http://127.0.0.1:3000"
    onebot_access_token: str = ""
    onebot_inbound_token: str = ""
    enable_high_risk_block: bool = True
    enable_logging: bool = True
    sandbox_dir: Path = Path("./sandbox")
    log_dir: Path = Path("./logs/qlos_lite")
    identity_dir: Path = Path("./state/qlos_lite")
    roles_file: Path = Path("./roles.json")
    media_dir: Path = field(default_factory=default_media_dir)
    queue_dir: Path = Path("./state/qlos_lite/queue")
    enable_queue: bool = True
    queue_stale_after_seconds: float = 120.0
    hermes_timeout: int = 180
    onebot_timeout: int = 30
    enable_approval_bridge: bool = False
    hermes_runs_api_url: str = ""
    hermi_gateway_url: str = ""
    hermi_gateway_token: str = ""
    approval_wait_timeout: int = 600
    approval_poll_interval: float = 1.0
    auto_image_vision: bool = False


def load_qlos_lite_config() -> QLOSLiteConfig:
    load_local_secret_env()
    return QLOSLiteConfig(
        owner_qq_id=os.environ.get("QLOS_OWNER_QQ_ID", "").strip(),
        enable_group=_bool_env("QLOS_ENABLE_GROUP", True),
        allowed_group_ids=_csv_env("QLOS_ALLOWED_GROUP_IDS"),
        require_at_in_group=_bool_env("QLOS_REQUIRE_AT_IN_GROUP", True),
        hermes_api_url=os.environ.get(
            "QLOS_HERMES_API_URL",
            "http://127.0.0.1:8642/v1/chat/completions",
        ).strip(),
        hermes_api_key=os.environ.get("QLOS_HERMES_API_KEY", "").strip(),
        bot_qq_id=os.environ.get("QLOS_BOT_QQ_ID", "").strip(),
        bot_names=_csv_env("QLOS_BOT_NAMES") or ["Memory\u00b0", "Qiling", "QLOS"],
        onebot_base_url=_env_first("QLOS_ONEBOT_BASE_URL", "QILING_ONEBOT_BASE_URL", default="http://127.0.0.1:3000"),
        onebot_access_token=_env_first("QLOS_ONEBOT_ACCESS_TOKEN", "QILING_ONEBOT_ACCESS_TOKEN"),
        onebot_inbound_token=_env_first("QLOS_ONEBOT_INBOUND_TOKEN", "QILING_ONEBOT_INBOUND_TOKEN"),
        enable_high_risk_block=_bool_env("QLOS_ENABLE_HIGH_RISK_BLOCK", True),
        enable_logging=_bool_env("QLOS_ENABLE_LOGGING", True),
        sandbox_dir=Path(os.environ.get("QLOS_SANDBOX_DIR", "./sandbox")),
        log_dir=Path(os.environ.get("QLOS_LOG_DIR", "./logs/qlos_lite")),
        identity_dir=Path(os.environ.get("QLOS_IDENTITY_DIR", "./state/qlos_lite")),
        roles_file=Path(os.environ.get("QLOS_ROLES_FILE", "./roles.json")),
        media_dir=Path(os.environ.get("QLOS_MEDIA_DIR", str(default_media_dir()))),
        queue_dir=Path(os.environ.get("QLOS_QUEUE_DIR", "./state/qlos_lite/queue")),
        enable_queue=_bool_env("QLOS_ENABLE_QUEUE", True),
        queue_stale_after_seconds=float(os.environ.get("QLOS_QUEUE_STALE_AFTER_SECONDS", "120")),
        hermes_timeout=int(os.environ.get("QLOS_HERMES_TIMEOUT", "180")),
        onebot_timeout=int(os.environ.get("QLOS_ONEBOT_TIMEOUT", "30")),
        enable_approval_bridge=_bool_env("QLOS_ENABLE_APPROVAL_BRIDGE", True),
        hermes_runs_api_url=os.environ.get("QLOS_HERMES_RUNS_API_URL", "").strip(),
        hermi_gateway_url=_env_first("QLOS_HERMI_GATEWAY_URL", "HERMI_GATEWAY_URL"),
        hermi_gateway_token=_env_first("QLOS_HERMI_GATEWAY_TOKEN", "HERMI_CHANNEL_TOKEN"),
        approval_wait_timeout=int(os.environ.get("QLOS_APPROVAL_WAIT_TIMEOUT", "600")),
        approval_poll_interval=float(os.environ.get("QLOS_APPROVAL_POLL_INTERVAL", "1.0")),
        auto_image_vision=_bool_env("QLOS_AUTO_IMAGE_VISION", False),
    )
