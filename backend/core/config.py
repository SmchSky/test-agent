"""
全局配置。

加载优先级（高 → 低）：
  1. 操作系统环境变量
  2. backend/.env 文件
  3. 字段默认值

使用 pydantic-settings 的 BaseSettings，天然支持 .env 文件与环境变量覆盖。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 根目录
_BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """应用配置，通过 .env 文件 + 环境变量加载。"""

    model_config = SettingsConfigDict(
        env_file=_BASE_DIR / ".env",
        env_file_encoding="utf-8",
        # 环境变量不区分大小写
        case_sensitive=False,
        # 如果字段在 .env 中没有定义，使用默认值；不报错
        extra="ignore",
    )

    # ---------- 应用 ----------
    app_name: str = "Test Agent"
    app_env: str = "dev"
    debug: bool = True

    # ---------- 拓扑 ----------
    topology_seed_path: Path = _BASE_DIR / "seeds" / "ospf_basic.yml"

    # ---------- 设备传输层 ----------
    transport_mode: str = "mock"
    transport_idle_ttl: float = 300
    transport_reap_interval: float = 60
    device_ssh_username: str = ""
    device_ssh_password: str = ""
    device_ssh_port: int = 22

    # ---------- Agent ----------
    llm_provider: str = "mock"
    max_turns: int = 30
    context_char_limit: int = 120_000
    keep_recent_tool_results: int = 4

    # ---------- 智谱 AI ----------
    zai_api_key: str = ""
    zai_model: str = "glm-5.1"
    zai_timeout_seconds: float = 120

    @property
    def base_dir(self) -> Path:
        """返回 backend/ 根目录。"""
        return _BASE_DIR


@lru_cache(maxsize=1)
def _get_settings() -> Settings:
    """单例 + 懒加载，确保整个进程共用同一份配置。"""
    return Settings()


# 对外暴露的单例，与原有 `from core.config import settings` 完全兼容
settings: Settings = _get_settings()
