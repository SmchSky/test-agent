from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from agent.prompts import build_system_prompt
from core.config import settings
from llm.base import LLMProvider
from services.context_window import is_context_overflow, micro_compact_messages
from services.topology import TopologyService
from tools.base import ToolCall, ToolExecutionResult
from tools.registry import ToolRegistry


class AgentRunner:
    def __init__(
        self,
        *,
        topology: TopologyService,
        tools: ToolRegistry,
        llm: LLMProvider,
    ) -> None:
        self.topology = topology
        self.tools = tools
        self.llm = llm
        self.messages: list[dict[str, Any]] = []

    async def run(self, content: str, *, max_turns: int | None = None) -> AsyncIterator[dict[str, Any]]:
        max_turns = max_turns or settings.max_turns
        self.messages.append({"role": "user", "content": content})
        system_prompt = build_system_prompt(self.topology)
        turn_count = 0

        while True:
            llm_messages = micro_compact_messages(self.messages)
            if is_context_overflow(llm_messages):
                yield self._event(
                    "agent_done",
                    {"reason": "context_overflow", "turn_count": turn_count},
                )
                return

            try:
                response = await self.llm.complete(
                    system_prompt=system_prompt,
                    messages=llm_messages,
                    tools=self.tools.schemas_for_llm(),
                )
            except Exception as exc:  # noqa: BLE001
                yield self._event("error", {"code": "api_error", "message": str(exc)})
                yield self._event("agent_done", {"reason": "api_error", "turn_count": turn_count})
                return

            if response.text:
                yield self._event("agent_text_delta", {"content": response.text})

            assistant_message = {
                "role": "assistant",
                "content": response.text,
            }
            if response.tool_calls:
                assistant_message["tool_calls"] = [
                    self._serialise_tool_call(call) for call in response.tool_calls
                ]
            self.messages.append(assistant_message)

            if not response.tool_calls:
                yield self._event("agent_done", {"reason": "completed", "turn_count": turn_count})
                return

            for call in response.tool_calls:
                yield self._event(
                    "tool_call_start",
                    {"call_id": call.id, "tool_name": call.name, "arguments": call.arguments},
                )
                result = await self.tools.get(call.name).run(call)
                self.messages.append(self._tool_message(result))
                yield self._event("tool_call_result", result.model_dump(mode="json"))

            turn_count += 1
            if turn_count >= max_turns:
                yield self._event("agent_done", {"reason": "max_turns", "turn_count": turn_count})
                return

    @staticmethod
    def _event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"type": event_type, "data": data}

    @staticmethod
    def _serialise_tool_call(call: ToolCall) -> dict[str, Any]:
        return {
            "id": call.id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": call.arguments,
            },
        }

    @staticmethod
    def _tool_message(result: ToolExecutionResult) -> dict[str, Any]:
        return {
            "role": "tool",
            "name": result.tool_name,
            "tool_call_id": result.call_id,
            "content": result.summary,
        }
