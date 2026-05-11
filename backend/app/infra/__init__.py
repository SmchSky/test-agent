"""
app/infra/ — 设备自动化基础设施层

Transport Layer（传输层）:
  - DeviceTransport: 传输层协议定义
  - CommandResult: 命令执行结果数据类
  - ScrapliTransport: 基于 scrapli + 华为 VRP 的 SSH 传输实现
  - MockTransport: 基于 JSON 文件的模拟传输（测试 / 开发）

Operations Layer（操作层）（未导出）:
  - check_device_connectivity: 设备连通性检查
  - execute_configure: 事务性配置下发执行引擎
  - execute_query: 查询命令执行引擎（含 TextFSM 解析）
  - execute_operate: 操作性命令执行引擎（断连韧性）
  - parse_output: TextFSM 结构化输出解析

Errors（错误体系）:
  - DeviceError 及其子类：统一的设备通信异常层次
"""

from .exceptions import (
    AuthenticationError,
    CommandExecutionError,
    CommandTimeoutError,
    DeviceConnectionError,
    DeviceError,
    DeviceUnreachableError,
)
from .transport import CommandResult, DeviceTransport, MockTransport, ScrapliTransport, create_transport

__all__ = [
    "DeviceError",
    "DeviceConnectionError",
    "AuthenticationError",
    "CommandTimeoutError",
    "DeviceUnreachableError",
    "CommandExecutionError",
    "CommandResult",
    "DeviceTransport",
    "MockTransport",
    "ScrapliTransport",
    "create_transport",
]
