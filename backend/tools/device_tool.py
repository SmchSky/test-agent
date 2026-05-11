from __future__ import annotations

import asyncio
from typing import Any

from infra.operations import execute_configure, execute_operate, execute_query
from infra.transport.pool import TransportPool
from services.topology import TopologyService
from tools.base import AgentTool


class DeviceToolContext:
    def __init__(self, topology: TopologyService, pool: TransportPool) -> None:
        self.topology = topology
        self.pool = pool
        self._locks: dict[str, asyncio.Lock] = {}

    def lock_for(self, device_name: str) -> asyncio.Lock:
        key = device_name.upper()
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]


class QueryDeviceTool(AgentTool):
    name = "query_device"
    description = "在指定设备上执行一条只读查询命令，适用于 display 类命令。入参使用设备名。"
    safety = "read_only"

    def __init__(self, context: DeviceToolContext) -> None:
        self.context = context

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "设备名，例如 R1"},
                "command": {"type": "string", "description": "查询命令"},
                "parse": {"type": "boolean", "default": True},
                "timeout": {"type": "number", "default": 30},
            },
            "required": ["device", "command"],
        }

    async def execute(self, arguments: dict[str, Any]) -> Any:
        device_name = str(arguments["device"])
        device = self.context.topology.resolve_device(device_name)
        transport = await self.context.pool.acquire(device.management_ip)
        return await execute_query(
            transport,
            device.management_ip,
            str(arguments["command"]),
            parse=bool(arguments.get("parse", True)),
            timeout=float(arguments.get("timeout", 30)),
        )

    def summarize(self, data: Any) -> str:
        output = data.output
        if isinstance(output, list):
            output_text = "\n".join(str(row) for row in output) or "无结构化记录"
        else:
            output_text = output or "命令执行成功，无输出"
        return f"[query_device] {data.device_ip} > {data.command}\n{output_text}"


class ConfigureDeviceTool(AgentTool):
    name = "configure_device"
    description = "在指定设备上串行下发一组配置命令，工具会先进入 system-view。入参使用设备名。"
    safety = "write"

    def __init__(self, context: DeviceToolContext) -> None:
        self.context = context

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "设备名，例如 R1"},
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "配置命令列表，不包含 system-view",
                },
                "start_from_system_view": {"type": "boolean", "default": True},
                "timeout": {"type": "number", "default": 60},
            },
            "required": ["device", "commands"],
        }

    async def execute(self, arguments: dict[str, Any]) -> Any:
        device_name = str(arguments["device"])
        device = self.context.topology.resolve_device(device_name)
        commands = [str(command) for command in arguments["commands"]]
        async with self.context.lock_for(device.name):
            transport = await self.context.pool.acquire(device.management_ip)
            return await execute_configure(
                transport,
                device.management_ip,
                commands,
                start_from_system_view=bool(arguments.get("start_from_system_view", True)),
                timeout=float(arguments.get("timeout", 60)),
            )

    def summarize(self, data: Any) -> str:
        lines = [f"[configure_device] {data.device_ip} rolled_back={data.rolled_back}"]
        for item in data.results:
            output = item.output or "命令执行成功，无输出"
            lines.append(f"> {item.command}\n{output}")
        return "\n".join(lines)


class OperateDeviceTool(AgentTool):
    name = "operate_device"
    description = "在指定设备上执行操作性命令，例如 ping、save、reboot。入参使用设备名。"
    safety = "write"

    def __init__(self, context: DeviceToolContext) -> None:
        self.context = context

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "设备名，例如 R1"},
                "command": {"type": "string", "description": "操作命令"},
                "timeout": {"type": "number", "default": 60},
            },
            "required": ["device", "command"],
        }

    async def execute(self, arguments: dict[str, Any]) -> Any:
        device_name = str(arguments["device"])
        device = self.context.topology.resolve_device(device_name)
        async with self.context.lock_for(device.name):
            transport = await self.context.pool.acquire(device.management_ip)
            return await execute_operate(
                transport,
                device.management_ip,
                str(arguments["command"]),
                timeout=float(arguments.get("timeout", 60)),
            )

    def summarize(self, data: Any) -> str:
        output = data.output or "命令执行成功，无输出"
        return f"[operate_device] {data.device_ip} > {data.command}\n{output}"
