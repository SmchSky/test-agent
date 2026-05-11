from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
from typing import Any, Literal

ToolSafety = Literal["read_only", "write", "destructive"]


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionResult(BaseModel):
    tool_name: str
    call_id: str
    arguments: dict[str, Any]
    data: Any
    summary: str
    elapsed_ms: int
    error: str | None = None


class AgentTool(ABC):
    name: str
    description: str
    safety: ToolSafety = "write"
    max_output_chars: int = 30_000
    preview_chars: int = 2_000

    def schema_for_llm(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema(),
            },
        }

    @abstractmethod
    def parameters_schema(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> Any:
        raise NotImplementedError

    @abstractmethod
    def summarize(self, data: Any) -> str:
        raise NotImplementedError

    async def run(self, call: ToolCall) -> ToolExecutionResult:
        started = time.perf_counter()
        try:
            data = await self.execute(call.arguments)
            summary = self._limit_for_llm(self.summarize(data))
            error = None
        except Exception as exc:  # noqa: BLE001 - surface tool failures to the agent.
            data = None
            summary = f"工具 {self.name} 执行失败: {exc}"
            error = str(exc)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return ToolExecutionResult(
            tool_name=self.name,
            call_id=call.id,
            arguments=call.arguments,
            data=data,
            summary=summary,
            elapsed_ms=elapsed_ms,
            error=error,
        )

    def _limit_for_llm(self, text: str) -> str:
        if not text:
            return "命令执行成功，无输出"
        if len(text) <= self.max_output_chars:
            return text
        preview = text[: self.preview_chars]
        return (
            f"输出过长，共 {len(text)} 字符。以下为前 {self.preview_chars} 字符预览:\n"
            f"{preview}\n"
            "请基于预览判断；如需完整输出，可再次执行更精确的查询命令。"
        )
