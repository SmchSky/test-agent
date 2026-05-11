"""
Operations 层 — 可复用的设备业务操作

无状态的 async 函数，接收 transport 等基础设施对象，
可被多个 module、MCP Server、Python import 共享。
"""

from .command import execute_configure, execute_operate, execute_query
from .connectivity import DeviceBasicInfo, check_device_connectivity
from .file_transfer import ftp_file_to_device
from .parser import get_supported_commands, parse_output
from .schemas import (
    CommandOutput,
    ConfigureResult,
    OperateResult,
    QueryResult,
)

__all__ = [
    "check_device_connectivity",
    "CommandOutput",
    "ConfigureResult",
    "DeviceBasicInfo",
    "execute_configure",
    "execute_operate",
    "execute_query",
    "ftp_file_to_device",
    "get_supported_commands",
    "OperateResult",
    "parse_output",
    "QueryResult",
]
