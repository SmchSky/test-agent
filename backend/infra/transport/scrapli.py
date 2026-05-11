"""
ScrapliTransport — 基于 Scrapli + 华为 VRP 社区驱动的设备传输层

自动处理:
  - ---- More ---- 分页
  - 命令提示符匹配
  - SSH 认证

依赖: scrapli[asyncssh] + scrapli-community
"""

import time
from datetime import datetime, timezone

from loguru import logger
from scrapli import AsyncScrapli
from scrapli.exceptions import (
    ScrapliAuthenticationFailed,
    ScrapliConnectionError,
    ScrapliTimeout,
)

from infra.exceptions import (
    AuthenticationError,
    CommandExecutionError,
    CommandTimeoutError,
    DeviceConnectionError,
)
from infra.transport.protocol import CommandResult, DeviceTransport


class ScrapliTransport(DeviceTransport):
    """基于 Scrapli + 华为 VRP 社区驱动的设备传输层

    Args:
        host: 设备 IP
        username: SSH 用户名
        password: SSH 密码
        port: SSH 端口，默认 22
        connect_timeout: 连接超时（秒），默认 10
    """

    _PLATFORM = "huawei_vrp"

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 22,
        connect_timeout: float = 10.0,
    ) -> None:
        self._host = host
        self._username = username
        self._password = password
        self._port = port
        self._connect_timeout = connect_timeout
        self._driver: AsyncScrapli | None = None

    def _build_driver(self) -> AsyncScrapli:
        """构造 AsyncScrapli 驱动实例"""
        return AsyncScrapli(
            host=self._host,
            port=self._port,
            auth_username=self._username,
            auth_password=self._password,
            auth_strict_key=False,
            platform=self._PLATFORM,
            transport="asyncssh",
            timeout_socket=self._connect_timeout,
            timeout_transport=self._connect_timeout,
            timeout_ops=30.0,
        )

    async def connect(self) -> None:
        """建立 SSH 连接"""
        try:
            self._driver = self._build_driver()
            assert self._driver is not None  # for type checker
            await self._driver.open()
            logger.info(
                "ScrapliTransport 连接成功: host={}:{}, user={}",
                self._host,
                self._port,
                self._username,
            )
        except ScrapliAuthenticationFailed as e:
            raise AuthenticationError(
                f"SSH 认证失败: host={self._host}, user={self._username}"
            ) from e
        except ScrapliConnectionError as e:
            raise DeviceConnectionError(
                f"SSH 连接失败: host={self._host}:{self._port} — {e}"
            ) from e
        except ScrapliTimeout as e:
            raise DeviceConnectionError(
                f"SSH 连接超时: host={self._host}:{self._port} — {e}"
            ) from e
        except Exception as e:
            # 捕获 asyncssh 底层异常
            error_lower = str(e).lower()
            if any(
                kw in error_lower
                for kw in ("auth", "permission", "password", "credential")
            ):
                raise AuthenticationError(f"认证相关错误: {e}") from e
            raise DeviceConnectionError(f"连接异常: {e}") from e

    async def execute(
        self,
        command: str,
        timeout: float = 30.0,
    ) -> CommandResult:
        """执行单条命令，返回结构化结果

        Args:
            command: 要执行的 CLI 命令
            timeout: 命令超时时间（秒）
        """
        if not self._driver or not self._driver.isalive():
            raise DeviceConnectionError(
                "ScrapliTransport: 连接已断开，请重新连接"
            )

        started = time.monotonic()
        timestamp = datetime.now(timezone.utc)

        try:
            response = await self._driver.send_command(
                command,
                timeout_ops=timeout,
            )
            elapsed = time.monotonic() - started

            if response.failed:
                logger.warning(
                    "命令执行失败: host={}, command={!r}, elapsed={:.3f}s",
                    self._host,
                    command,
                    elapsed,
                )
                return CommandResult(
                    command=command,
                    output=response.result,
                    elapsed_seconds=elapsed,
                    timestamp=timestamp,
                    success=False,
                    error="Scrapli 报告命令失败",
                )

            logger.debug(
                "命令执行成功: host={}, command={!r}, elapsed={:.3f}s, output_len={}",
                self._host,
                command,
                elapsed,
                len(response.result),
            )
            return CommandResult(
                command=command,
                output=response.result,
                elapsed_seconds=elapsed,
                timestamp=timestamp,
                success=True,
            )

        except ScrapliTimeout as e:
            raise CommandTimeoutError(
                f"命令超时: host={self._host}, command={command!r}, timeout={timeout}s"
            ) from e
        except Exception as e:
            raise CommandExecutionError(
                f"命令执行异常: host={self._host}, command={command!r} — {e}"
            ) from e

    async def send_interactive(
        self,
        interact_events: list[tuple[str, str] | tuple[str, str, bool]],
        timeout: float = 30.0,
    ) -> CommandResult:
        """执行交互式命令序列，包装 Scrapli send_interactive

        用于 FTP 等需要多轮非标准提示符交互的场景。
        """
        if not self._driver or not self._driver.isalive():
            raise DeviceConnectionError(
                "ScrapliTransport: 连接已断开，请重新连接"
            )

        started = time.monotonic()
        timestamp = datetime.now(timezone.utc)

        try:
            response = await self._driver.send_interactive(
                interact_events=interact_events,  # type: ignore
                timeout_ops=timeout,
            )
            elapsed = time.monotonic() - started

            if response.failed:
                logger.warning(
                    "交互式命令执行失败: host={}, elapsed={:.3f}s",
                    self._host,
                    elapsed,
                )
                return CommandResult(
                    command="[interactive]",
                    output=response.result,
                    elapsed_seconds=elapsed,
                    timestamp=timestamp,
                    success=False,
                    error="交互式命令执行失败",
                )

            logger.debug(
                "交互式命令执行成功: host={}, elapsed={:.3f}s, output_len={}",
                self._host,
                elapsed,
                len(response.result),
            )
            return CommandResult(
                command="[interactive]",
                output=response.result,
                elapsed_seconds=elapsed,
                timestamp=timestamp,
                success=True,
            )

        except ScrapliTimeout as e:
            raise CommandTimeoutError(
                f"交互式命令超时: host={self._host}, timeout={timeout}s"
            ) from e
        except Exception as e:
            raise CommandExecutionError(
                f"交互式命令执行异常: host={self._host} — {e}"
            ) from e

    async def is_alive(self) -> bool:
        """检查 SSH 连接是否存活"""
        if not self._driver:
            return False
        try:
            return self._driver.isalive()
        except Exception:
            return False

    async def close(self) -> None:
        """关闭连接（幂等）"""
        if self._driver:
            try:
                await self._driver.close()
                logger.info(
                    "ScrapliTransport 连接关闭: host={}", self._host
                )
            except Exception as e:
                logger.warning(
                    "关闭连接时出错 (已忽略): host={}, error={}", self._host, e
                )
            finally:
                self._driver = None
