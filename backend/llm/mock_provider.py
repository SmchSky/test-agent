from __future__ import annotations

from typing import Any

from llm.base import LLMProvider, LLMResponse, new_tool_call


class MockLLMProvider(LLMProvider):
    """Deterministic local provider for P0 demos without an API key."""

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        del system_prompt, tools
        user_text = self._last_user_text(messages)
        tool_names = [message.get("name") for message in messages if message.get("role") == "tool"]

        if "topology_query" not in tool_names:
            return LLMResponse(
                text="我先读取固定 OSPF 拓扑，确认设备互联关系。\n",
                tool_calls=[
                    new_tool_call(
                        "topology_query",
                        {
                            "query_type": "between" if ("R1" in user_text and "R2" in user_text) else "summary",
                            "device": "R1",
                            "peer": "R2",
                        },
                    )
                ],
            )

        if "configure_device" not in tool_names and "删除" not in user_text:
            return LLMResponse(
                text="拓扑已确认。开始在相关设备上下发 OSPF area 0 配置。\n",
                tool_calls=[
                    new_tool_call(
                        "configure_device",
                        {
                            "device": "R1",
                            "commands": ["ospf 1", "area 0", "network 10.1.1.0 0.0.0.3"],
                        },
                    ),
                    new_tool_call(
                        "configure_device",
                        {
                            "device": "R2",
                            "commands": ["ospf 1", "area 0", "network 10.1.1.0 0.0.0.3"],
                        },
                    ),
                ],
            )

        if "删除" in user_text and "configure_device" not in tool_names:
            return LLMResponse(
                text="我先查看当前 OSPF 配置，然后删除 OSPF 进程 1。\n",
                tool_calls=[
                    new_tool_call(
                        "query_device",
                        {"device": "R1", "command": "display current-configuration | section ospf"},
                    ),
                    new_tool_call(
                        "configure_device",
                        {"device": "R1", "commands": ["undo ospf 1"]},
                    ),
                ],
            )

        if "query_device" not in tool_names:
            return LLMResponse(
                text="配置下发完成。现在查询 OSPF 邻居状态进行验证。\n",
                tool_calls=[
                    new_tool_call(
                        "query_device",
                        {"device": "R1", "command": "display ospf peer brief", "parse": False},
                    )
                ],
            )

        if any("Full" in str(message.get("content", "")) for message in messages if message.get("role") == "tool"):
            return LLMResponse(text="验证通过：查询输出包含 Full 状态，OSPF 邻居已建立。\n")

        return LLMResponse(text="无法判断：已完成查询，但输出中没有明确的 Full 状态。\n")

    @staticmethod
    def _last_user_text(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                return str(message.get("content", ""))
        return ""
