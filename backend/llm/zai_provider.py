from __future__ import annotations

import asyncio
from typing import Any

from core.config import settings
from llm.base import LLMProvider, LLMResponse
from tools.base import ToolCall


class ZaiLLMProvider(LLMProvider):
    """智谱 GLM Provider using the official zai-sdk client."""

    def __init__(self) -> None:
        if not settings.zai_api_key:
            raise ValueError("LLM_PROVIDER=zai 时必须设置 ZAI_API_KEY")
        try:
            from zai import ZhipuAiClient
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("未安装 zai-sdk，无法使用智谱 GLM Provider") from exc
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

        def call_api() -> Any:
            return self._client.chat.completions.create(
                model=settings.zai_model,
                messages=payload_messages,
                tools=tools,
                tool_choice="auto",
                timeout=settings.zai_timeout_seconds,
            )

        response = await asyncio.to_thread(call_api)
        return self._parse_response(response)

    def _normalise_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
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

    @staticmethod
    def _parse_response(response: Any) -> LLMResponse:
        message = response.choices[0].message
        content = getattr(message, "content", "") or ""
        raw_tool_calls = getattr(message, "tool_calls", None) or []
        tool_calls: list[ToolCall] = []
        for raw in raw_tool_calls:
            function = getattr(raw, "function", None)
            if function is None:
                continue
            arguments = getattr(function, "arguments", {}) or {}
            if isinstance(arguments, str):
                import json

                arguments = json.loads(arguments or "{}")
            tool_calls.append(
                ToolCall(
                    id=str(getattr(raw, "id", "")),
                    name=str(getattr(function, "name", "")),
                    arguments=arguments,
                )
            )
        return LLMResponse(text=content, tool_calls=tool_calls)
