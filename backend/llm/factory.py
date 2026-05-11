from __future__ import annotations

from core.config import settings
from llm.base import LLMProvider
from llm.mock_provider import MockLLMProvider
from llm.zai_provider import ZaiLLMProvider


def create_llm_provider() -> LLMProvider:
    provider = settings.llm_provider.lower()
    if provider == "mock":
        return MockLLMProvider()
    if provider in {"zai"}:
        return ZaiLLMProvider()
    raise ValueError(f"不支持的 LLM_PROVIDER: {settings.llm_provider}")
