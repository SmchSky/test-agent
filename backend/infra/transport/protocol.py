"""
DeviceTransport 协议定义 + CommandResult 数据类

协议（structural subtyping）允许 ScrapliTransport 和 MockTransport
在不继承共同基类的情况下满足类型约束。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass
class CommandResult:
    """单条命令执行结果"""

    command: str  # 执行的命令
    output: str  # 原始回显文本
    elapsed_seconds: float  # 执行耗时
    timestamp: datetime  # 执行时间
    success: bool  # 是否成功（提示符正常返回）
    error: str | None = None  # 错误信息（如超时、连接断开）


@runtime_checkable
class DeviceTransport(Protocol):
    """设备传输层协议

    所有具体传输实现（Scrapli、Mock 等）必须满足此接口。
    使用 @runtime_checkable 以支持 isinstance() 检查。
    """

    async def connect(self) -> None:
        """建立到设备的连接。失败抛出 DeviceConnectionError。"""
        ...

    async def execute(
        self,
        command: str,
        timeout: float = 30.0,
    ) -> CommandResult:
        """执行单条命令并等待标准提示符回显。"""
        ...

    async def send_interactive(
        self,
        interact_events: list[tuple[str, str] | tuple[str, str, bool]],
        timeout: float = 30.0,
    ) -> CommandResult:
        """执行交互式命令序列（多轮提示/应答）。

        用于 FTP、SCP 等需要非标准提示符交互的场景。

        interact_events 中每个元素为 (input, expected_prompt[, hidden]) 元组：
          - input: 发送的输入文本
          - expected_prompt: 发送后等待出现的提示符/模式
          - hidden: 可选，True 表示输入应被隐藏（如密码），默认 False

        最后一个元素的 expected_prompt 通常为空字符串，表示等待设备标准提示符。
        """
        ...

    async def is_alive(self) -> bool:
        """轻量级连接存活探测（不发送业务命令）。"""
        ...

    async def close(self) -> None:
        """关闭连接并释放资源。必须幂等。"""
        ...
