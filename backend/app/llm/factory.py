from __future__ import annotations

from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.mock_provider import MockLLMProvider
from app.llm.zai_provider import ZaiLLMProvider


def create_llm_provider() -> LLMProvider:
    provider = settings.llm_provider.lower()
    if provider == "mock":
        return MockLLMProvider()
    if provider in {"zai", "glm", "zhipu"}:
        return ZaiLLMProvider()
    raise ValueError(f"不支持的 LLM_PROVIDER: {settings.llm_provider}")
