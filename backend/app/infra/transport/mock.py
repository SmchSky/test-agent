"""
MockTransport — 基于 JSON 文件的模拟传输层

用途:
  - 单元测试（无需真实设备）
  - 开发环境调试
  - CI/CD 流水线

JSON 文件格式:
  {
    "display version": "Huawei Versatile Routing Platform Software...",
    "display ip routing-table": "..."
  }
"""

import json
import time
from app.infra.exceptions import (
    AuthenticationError,
    DeviceConnectionError,
    DeviceUnreachableError,
)
from app.infra.transport.protocol import CommandResult, DeviceTransport
from datetime import datetime, timezone
from loguru import logger
from pathlib import Path

# 基于文件位置的默认 Mock 数据目录（确保从任意工作目录运行都能找到）
# __file__ = app/infra/transport/mock.py → parent×2 = app/infra/
_DEFAULT_MOCK_DATA_DIR = Path(__file__).parent.parent / "mock_data"


class MockTransport(DeviceTransport):
    """基于 JSON 文件的模拟传输层

    Args:
        host: 设备 IP（仅用于日志标识）
        responses_file: JSON 响应文件路径（Path 或 str）
        fail_on_unknown: 遇到未知命令时是否报告失败（默认宽松模式）
        simulate_auth_failure: 模拟认证失败
        simulate_connect_failure: 模拟连接失败
        reboot_recovery_seconds: 模拟重启后恢复所需秒数
    """

    def __init__(
        self,
        host: str,
        responses_file: Path | str | None = None,
        *,
        fail_on_unknown: bool = False,
        simulate_auth_failure: bool = False,
        simulate_connect_failure: bool = False,
        reboot_recovery_seconds: float = 5.0,
    ) -> None:
        self._host = host
        # 如果未指定文件，使用基于 __file__ 定位的默认文件
        if responses_file is None:
            self._responses_file = _DEFAULT_MOCK_DATA_DIR / "huawei_vrp_default.json"
        else:
            self._responses_file = Path(responses_file)
        self._fail_on_unknown = fail_on_unknown
        self._simulate_auth_failure = simulate_auth_failure
        self._simulate_connect_failure = simulate_connect_failure
        self._reboot_recovery_seconds = reboot_recovery_seconds
        self._responses: dict[str, str] = {}
        self._connected = False
        self._reboot_triggered_at: float | None = None

    async def connect(self) -> None:
        """加载 JSON 响应文件，模拟连接建立"""
        if self._simulate_connect_failure:
            raise DeviceConnectionError(f"Mock: 模拟连接失败 → {self._host}")
        if self._simulate_auth_failure:
            raise AuthenticationError(f"Mock: 模拟认证失败 → {self._host}")

        if not self._responses_file.exists():
            raise FileNotFoundError(
                f"Mock 响应文件不存在: {self._responses_file}"
            )

        with self._responses_file.open(encoding="utf-8") as f:
            self._responses = json.load(f)

        self._connected = True
        logger.info(
            "MockTransport 连接成功: host={}, file={}",
            self._host,
            self._responses_file,
        )

    async def execute(
        self,
        command: str,
        timeout: float = 30.0,
    ) -> CommandResult:
        """从预加载的字典中查找命令响应"""
        if not self._connected:
            if self._reboot_triggered_at is not None:
                raise DeviceUnreachableError(
                    f"MockTransport: 设备正在重启中 → {self._host}"
                )
            raise DeviceConnectionError(
                "MockTransport: 未连接，请先调用 connect()"
            )

        started = time.monotonic()
        timestamp = datetime.now(timezone.utc)

        # 精确匹配优先，其次做 strip() 后匹配
        output = self._responses.get(command) or self._responses.get(
            command.strip()
        )

        if output is None:
            if self._fail_on_unknown:
                elapsed = time.monotonic() - started
                return CommandResult(
                    command=command,
                    output="",
                    elapsed_seconds=elapsed,
                    timestamp=timestamp,
                    success=False,
                    error=f"Mock: 未找到命令 '{command}' 的预设响应",
                )
            output = ""

        elapsed = time.monotonic() - started
        logger.debug(
            "MockTransport 执行命令: host={}, command={!r}, elapsed={:.3f}s",
            self._host,
            command,
            elapsed,
        )

        return CommandResult(
            command=command,
            output=output,
            elapsed_seconds=elapsed,
            timestamp=timestamp,
            success=True,
        )

    async def send_interactive(
        self,
        interact_events: list[tuple[str, str] | tuple[str, str, bool]],
        timeout: float = 30.0,
    ) -> CommandResult:
        """模拟交互式命令序列

        将所有交互步骤拼接为组合输出。
        支持通过 responses_file 中的 "__interactive__" key 预设响应。
        """
        if not self._connected:
            raise DeviceConnectionError(
                "MockTransport: 未连接，请先调用 connect()"
            )

        started = time.monotonic()
        timestamp = datetime.now(timezone.utc)

        # 优先使用预设的交互式响应
        interactive_output = self._responses.get("__interactive__")
        if interactive_output is None:
            # 自动拼接交互序列
            parts = []
            for event in interact_events:
                input_text = event[0]
                expected_prompt = event[1]
                hidden = event[2] if len(event) > 2 else False
                if hidden:
                    parts.append(f"{expected_prompt}")
                else:
                    parts.append(f"{input_text}\n{expected_prompt}")
            interactive_output = "\n".join(parts)

        elapsed = time.monotonic() - started
        logger.debug(
            "MockTransport 交互式命令: host={}, steps={}, elapsed={:.3f}s",
            self._host,
            len(interact_events),
            elapsed,
        )

        return CommandResult(
            command="[interactive]",
            output=interactive_output,
            elapsed_seconds=elapsed,
            timestamp=timestamp,
            success=True,
        )

    async def is_alive(self) -> bool:
        """检查模拟连接是否存活

        重启期间返回 False，经过 reboot_recovery_seconds 后自动恢复为 True。
        """
        if self._reboot_triggered_at is not None:
            elapsed = time.monotonic() - self._reboot_triggered_at
            if elapsed >= self._reboot_recovery_seconds:
                # 恢复就绪，但需要调用 reconnect() 才真正重新连接
                return False
            return False
        return self._connected

    def trigger_reboot(self) -> None:
        """模拟设备重启：立即断开连接，经过配置的恢复时间后可重连"""
        self._connected = False
        self._reboot_triggered_at = time.monotonic()
        logger.info(
            "MockTransport 模拟重启: host={}, 预计 {}s 后可重连",
            self._host,
            self._reboot_recovery_seconds,
        )

    @property
    def is_reboot_ready(self) -> bool:
        """检查设备是否已从重启中恢复，可以重新连接"""
        if self._reboot_triggered_at is None:
            return True
        return (time.monotonic() - self._reboot_triggered_at) >= self._reboot_recovery_seconds

    async def reconnect(self) -> None:
        """重启恢复后重新建立连接"""
        if self._reboot_triggered_at is not None:
            elapsed = time.monotonic() - self._reboot_triggered_at
            if elapsed < self._reboot_recovery_seconds:
                raise DeviceUnreachableError(
                    f"MockTransport: 设备仍在重启中 "
                    f"(已等待 {elapsed:.1f}s / 需要 {self._reboot_recovery_seconds}s)"
                )
            # 恢复完成
            self._reboot_triggered_at = None
            self._connected = True
            logger.info("MockTransport 重启恢复: host={}", self._host)
        elif not self._connected:
            # 非重启场景的重连，重新加载响应文件
            await self.connect()
        # 已连接则幂等

    async def close(self) -> None:
        """关闭模拟连接"""
        self._connected = False
        logger.info("MockTransport 连接关闭: host={}", self._host)
