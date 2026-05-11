from __future__ import annotations

from app.services.topology import TopologyService
from app.tools.base import AgentTool
from typing import Any


class TopologyQueryTool(AgentTool):
    name = "topology_query"
    description = "查询固定 OSPF 测试拓扑，支持设备列表、链路列表、单设备链路和两设备互联查询。"
    safety = "read_only"

    def __init__(self, topology: TopologyService) -> None:
        self.topology = topology

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": ["summary", "devices", "links", "device_links", "between"],
                },
                "device": {"type": "string", "description": "设备名，例如 R1"},
                "peer": {"type": "string", "description": "对端设备名，例如 R2"},
            },
            "required": ["query_type"],
        }

    async def execute(self, arguments: dict[str, Any]) -> Any:
        query_type = str(arguments["query_type"])
        if query_type == "summary":
            return {"summary": self.topology.prompt_summary()}
        if query_type == "devices":
            return {"devices": self.topology.list_devices()}
        if query_type == "links":
            return {"links": self.topology.list_links()}
        if query_type == "device_links":
            return {
                "links": self.topology.find_link(str(arguments["device"])),
            }
        if query_type == "between":
            return {
                "links": self.topology.find_link(
                    str(arguments["device"]),
                    str(arguments["peer"]),
                )
            }
        raise ValueError(f"不支持的拓扑查询类型: {query_type}")

    def summarize(self, data: Any) -> str:
        if "summary" in data:
            return f"[topology_query]\n{data['summary']}"
        if "devices" in data:
            lines = [
                f"- {item['name']}: {item['model']} 管理 IP {item['management_ip']}"
                for item in data["devices"]
            ]
            return "[topology_query] 设备列表\n" + "\n".join(lines)
        links = data.get("links", [])
        if not links:
            return "[topology_query] 未找到匹配链路"
        lines = []
        for link in links:
            endpoints = " <-> ".join(
                f"{endpoint['device']} {endpoint['interface']} {endpoint['ip']}"
                for endpoint in link["endpoints"]
            )
            lines.append(f"- {endpoints} ({link['description']})")
        return "[topology_query] 链路\n" + "\n".join(lines)
