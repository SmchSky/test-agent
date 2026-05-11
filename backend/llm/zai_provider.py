from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from zai import ZhipuAiClient

from core.config import settings
from llm.base import LLMProvider, LLMResponse
from tools.base import ToolCall

logger = logging.getLogger(__name__)


class ZaiLLMProvider(LLMProvider):
    """智谱 GLM Provider using the official zai-sdk client (streaming)."""

    def __init__(self) -> None:
        self._client = ZhipuAiClient(api_key=settings.zai_api_key)

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        payload_messages = [{"role": "system", "content": system_prompt}]
        payload_messages.extend(self._normalise_messages(messages))

        def call_api() -> LLMResponse:
            stream = self._client.chat.completions.create(
                model=settings.zai_model,
                messages=payload_messages,
                thinking={
                    "type": "enabled",
                },
                tools=tools or None,
                tool_choice="auto",
                timeout=settings.zai_timeout_seconds,
                max_tokens=65536,
                temperature=1.0,
                stream=True,
            )
            return self._consume_stream(stream)

        return await asyncio.to_thread(call_api)

    @staticmethod
    def _consume_stream(stream: Any) -> LLMResponse:
        """Iterate over a streaming response and assemble the final result."""
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        # tool_calls are accumulated keyed by index
        tool_call_map: dict[int, dict[str, Any]] = {}

        for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            if choice is None:
                continue

            delta = choice.delta

            # Accumulate reasoning content (thinking tokens)
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                reasoning_parts.append(reasoning)

            # Accumulate main content
            text = getattr(delta, "content", None)
            if text:
                content_parts.append(text)

            # Accumulate streamed tool_calls
            raw_tool_calls = getattr(delta, "tool_calls", None)
            if raw_tool_calls:
                for tc in raw_tool_calls:
                    idx = getattr(tc, "index", 0)
                    if idx not in tool_call_map:
                        tool_call_map[idx] = {
                            "id": getattr(tc, "id", "") or "",
                            "name": "",
                            "arguments": "",
                        }
                    entry = tool_call_map[idx]
                    # Update id if provided
                    tc_id = getattr(tc, "id", None)
                    if tc_id:
                        entry["id"] = tc_id
                    # Update function name / arguments
                    func = getattr(tc, "function", None)
                    if func:
                        fname = getattr(func, "name", None)
                        if fname:
                            entry["name"] = fname
                        fargs = getattr(func, "arguments", None)
                        if fargs:
                            entry["arguments"] += fargs

        # Log reasoning content for debugging purposes
        if reasoning_parts:
            logger.debug("Reasoning: %s", "".join(reasoning_parts))

        # Build final content
        final_content = "".join(content_parts)

        # Build final tool_calls
        tool_calls: list[ToolCall] = []
        for _idx in sorted(tool_call_map):
            entry = tool_call_map[_idx]
            arguments_str = entry["arguments"]
            try:
                arguments = json.loads(arguments_str) if arguments_str else {}
            except json.JSONDecodeError:
                logger.warning(
                    "Failed to parse tool_call arguments: %s", arguments_str
                )
                arguments = {}
            tool_calls.append(
                ToolCall(
                    id=entry["id"],
                    name=entry["name"],
                    arguments=arguments,
                )
            )

        return LLMResponse(text=final_content, tool_calls=tool_calls)

    @staticmethod
    def _normalise_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalised: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            if role in {"user", "assistant"}:
                item: dict[str, Any] = {
                    "role": role,
                    "content": message.get("content", ""),
                }
                if message.get("tool_calls"):
                    item["tool_calls"] = message["tool_calls"]
                normalised.append(item)
            elif role == "tool":
                normalised.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.get("tool_call_id"),
                        "name": message.get("name"),
                        "content": message.get("content", ""),
                    }
                )
        return normalised
