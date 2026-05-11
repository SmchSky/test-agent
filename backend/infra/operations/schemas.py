"""
设备操作返回值模型

三个执行引擎 (execute_configure, execute_query, execute_operate) 的结构化返回值定义。
使用 Pydantic BaseModel 以便序列化为 JSON。

位于 infra/operations/ 下，供 MCP Server 和 Service 层共同复用。
"""

from typing import Any

from pydantic import BaseModel, Field


# --- configure_device 返回值 ---


class CommandOutput(BaseModel):
    """单条命令的执行结果"""

    command: str = Field(description="实际发送的命令")
    output: str = Field(description="提示符之间的设备回显，成功无输出则为空字符串")


class ConfigureResult(BaseModel):
    """configure_device 的返回值"""

    device_ip: str
    rolled_back: bool = Field(
        description="是否因出错丢弃了未提交的修改",
    )
    results: list[CommandOutput] = Field(
        description="已执行命令的结果列表（出错后停止，后续命令不包含）",
    )


# --- query_device 返回值 ---


class QueryResult(BaseModel):
    """query_device 的返回值"""

    device_ip: str
    command: str = Field(description="执行的查询命令")
    output: str | list[dict[str, Any]] = Field(
        description="解析成功时为 list[dict]，否则为原始回显文本",
    )


# --- operate_device 返回值 ---


class OperateResult(BaseModel):
    """operate_device 的返回值"""

    device_ip: str
    command: str = Field(description="实际发送的命令")
    output: str = Field(
        description="设备回显，原始文本（断连时为断连前收到的部分回显）",
    )
