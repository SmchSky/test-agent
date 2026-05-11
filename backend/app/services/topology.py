from __future__ import annotations

import yaml
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Any


class Device(BaseModel):
    name: str
    type: str = "router"
    model: str = ""
    management_ip: str = Field(alias="management-ip")


class Endpoint(BaseModel):
    device: str
    interface: str
    ip: str


class Link(BaseModel):
    endpoints: list[Endpoint]
    description: str = ""


class Topology(BaseModel):
    name: str
    description: str = ""
    version: str = "1.0"
    devices: list[Device]
    links: list[Link]


class TopologyService:
    def __init__(self, topology: Topology) -> None:
        self.topology = topology
        self._devices = {device.name.upper(): device for device in topology.devices}

    @classmethod
    def from_yaml(cls, path: Path) -> "TopologyService":
        with path.open("r", encoding="utf-8") as file:
            payload = yaml.safe_load(file)
        return cls(Topology.model_validate(payload))

    def device_names(self) -> list[str]:
        return [device.name for device in self.topology.devices]

    def resolve_device(self, device_name: str) -> Device:
        key = device_name.upper()
        if key not in self._devices:
            known = ", ".join(self.device_names())
            raise ValueError(f"未知设备 {device_name!r}，当前拓扑设备: {known}")
        return self._devices[key]

    def list_devices(self) -> list[dict[str, str]]:
        return [
            {
                "name": device.name,
                "type": device.type,
                "model": device.model,
                "management_ip": device.management_ip,
            }
            for device in self.topology.devices
        ]

    def list_links(self) -> list[dict[str, Any]]:
        return [
            {
                "description": link.description,
                "endpoints": [endpoint.model_dump() for endpoint in link.endpoints],
            }
            for link in self.topology.links
        ]

    def find_link(self, device: str, peer: str | None = None) -> list[dict[str, Any]]:
        device_key = device.upper()
        peer_key = peer.upper() if peer else None
        matches: list[dict[str, Any]] = []
        for link in self.topology.links:
            names = {endpoint.device.upper() for endpoint in link.endpoints}
            if device_key not in names:
                continue
            if peer_key and peer_key not in names:
                continue
            matches.append(
                {
                    "description": link.description,
                    "endpoints": [endpoint.model_dump() for endpoint in link.endpoints],
                }
            )
        return matches

    def prompt_summary(self) -> str:
        devices = "\n".join(
            f"- {device.name}: {device.model or device.type}, 管理 IP {device.management_ip}"
            for device in self.topology.devices
        )
        links = "\n".join(
            "- "
            + " <-> ".join(
                f"{endpoint.device} {endpoint.interface} {endpoint.ip}"
                for endpoint in link.endpoints
            )
            + (f" ({link.description})" if link.description else "")
            for link in self.topology.links
        )
        return (
            f"拓扑名称: {self.topology.name}\n"
            f"说明: {self.topology.description}\n"
            f"设备:\n{devices}\n"
            f"链路:\n{links}"
        )
