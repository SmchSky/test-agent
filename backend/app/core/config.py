from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "Test Agent"
    app_env: str = os.getenv("APP_ENV", "dev")
    debug: bool = _bool_env("DEBUG", True)

    base_dir: Path = Path(__file__).resolve().parents[2]
    topology_seed_path: Path = Path(
        os.getenv(
            "TOPOLOGY_SEED_PATH",
            str(Path(__file__).resolve().parents[2] / "seeds" / "ospf_basic.yml"),
        )
    )

    transport_mode: str = os.getenv("TRANSPORT_MODE", "mock")
    transport_idle_ttl: float = float(os.getenv("TRANSPORT_IDLE_TTL", "300"))
    transport_reap_interval: float = float(os.getenv("TRANSPORT_REAP_INTERVAL", "60"))
    device_ssh_username: str = os.getenv("DEVICE_SSH_USERNAME", "")
    device_ssh_password: str = os.getenv("DEVICE_SSH_PASSWORD", "")
    device_ssh_port: int = int(os.getenv("DEVICE_SSH_PORT", "22"))

    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    max_turns: int = int(os.getenv("MAX_TURNS", "30"))
    context_char_limit: int = int(os.getenv("CONTEXT_CHAR_LIMIT", "120000"))
    keep_recent_tool_results: int = int(os.getenv("KEEP_RECENT_TOOL_RESULTS", "4"))

    zai_api_key: str = os.getenv("ZAI_API_KEY", "")
    zai_base_url: str = os.getenv(
        "ZAI_BASE_URL",
        "https://open.bigmodel.cn/api/paas/v4/",
    )
    zai_model: str = os.getenv("ZAI_MODEL", "glm-5.1")
    zai_timeout_seconds: float = float(os.getenv("ZAI_TIMEOUT_SECONDS", "120"))


settings = Settings()
