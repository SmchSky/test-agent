from __future__ import annotations

from abc import ABC, abstractmethod
from app.tools.base import ToolCall
from pydantic import BaseModel, Field
from typing import Any
from uuid import uuid4


class LLMResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        raise NotImplementedError


def new_tool_call(name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(id=f"call_{uuid4().hex[:12]}", name=name, arguments=arguments)
