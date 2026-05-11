"""
Transport 工厂 — 根据配置统一创建传输层实例

通过 settings.transport_mode 全局切换 mock / scrapli，
所有业务代码只需调用 create_transport() 即可。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from core.config import settings

if TYPE_CHECKING:
    from infra.transport.protocol import DeviceTransport


def create_transport(
    host: str,
    *,
    username: str | None = None,
    password: str | None = None,
    port: int | None = None,
) -> DeviceTransport:
    """根据 TRANSPORT_MODE 配置创建传输层实例

    Args:
        host: 设备 IP 地址
        username: SSH 用户名（可选，默认从 settings 读取）
        password: SSH 密码（可选，默认从 settings 读取）
        port: SSH 端口（可选，默认从 settings 读取）
    """
    mode = settings.transport_mode.lower()

    if mode == "scrapli":
        from infra.transport.scrapli import ScrapliTransport

        return ScrapliTransport(
            host=host,
            username=username or settings.device_ssh_username,
            password=password or settings.device_ssh_password,
            port=port or settings.device_ssh_port,
        )

    if mode == "mock":
        from infra.transport.mock import MockTransport

        return MockTransport(host=host)

    logger.warning("未知的 TRANSPORT_MODE={!r}，回退到 mock", mode)
    from infra.transport.mock import MockTransport

    return MockTransport(host=host)
