from __future__ import annotations

from app.infra.transport.pool import TransportPool
from app.services.topology import TopologyService
from app.tools.base import AgentTool
from app.tools.device_tool import (
    ConfigureDeviceTool,
    DeviceToolContext,
    OperateDeviceTool,
    QueryDeviceTool,
)
from app.tools.topology_tool import TopologyQueryTool


class ToolRegistry:
    def __init__(self, tools: list[AgentTool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def get(self, name: str) -> AgentTool:
        if name not in self._tools:
            raise ValueError(f"未知工具: {name}")
        return self._tools[name]

    def list(self) -> list[AgentTool]:
        return list(self._tools.values())

    def schemas_for_llm(self) -> list[dict]:
        return [tool.schema_for_llm() for tool in self.list()]


def build_tool_registry(topology: TopologyService, pool: TransportPool) -> ToolRegistry:
    device_context = DeviceToolContext(topology=topology, pool=pool)
    return ToolRegistry(
        [
            TopologyQueryTool(topology),
            QueryDeviceTool(device_context),
            ConfigureDeviceTool(device_context),
            OperateDeviceTool(device_context),
        ]
    )
