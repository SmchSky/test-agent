from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.config import settings


def estimate_message_chars(messages: list[dict[str, Any]]) -> int:
    return sum(len(str(message.get("content", ""))) for message in messages)


def micro_compact_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trim old verbose tool results before sending history back to the LLM."""
    compacted = deepcopy(messages)
    tool_indexes = [
        index
        for index, message in enumerate(compacted)
        if message.get("role") == "tool" and len(str(message.get("content", ""))) > 2000
    ]
    keep = set(tool_indexes[-settings.keep_recent_tool_results:])
    for index in tool_indexes:
        if index in keep:
            continue
        content = str(compacted[index].get("content", ""))
        compacted[index]["content"] = f"[命令输出已清理，共 {len(content)} 字符]"
        compacted[index]["compacted"] = True
    return compacted


def is_context_overflow(messages: list[dict[str, Any]]) -> bool:
    return estimate_message_chars(messages) > settings.context_char_limit
