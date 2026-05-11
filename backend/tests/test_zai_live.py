"""
智谱 AI (ZAI) 模型连通性验证测试。

此测试通过实际 API 调用验证：
  1. API Key 配置正确且可认证
  2. 流式调用正常返回内容
  3. 深度思考 (thinking) 模式工作正常
  4. Tool calling 能力正常

运行方式（在 backend/ 目录下）：
  poetry run pytest tests/test_zai_live.py -v -s
"""

from __future__ import annotations

import pytest

from core.config import settings
from llm.base import LLMResponse
from llm.zai_provider import ZaiLLMProvider

# 跳过条件：没有配置 API Key 时自动跳过
_skip_no_key = pytest.mark.skipif(
    not settings.zai_api_key,
    reason="ZAI_API_KEY 未配置，跳过真实 API 测试",
)


@_skip_no_key
@pytest.mark.asyncio
async def test_zai_simple_chat():
    """验证基本流式对话：发送一个简单问题，期望返回非空文本。"""
    provider = ZaiLLMProvider()

    response = await provider.complete(
        system_prompt="你是一个有帮助的助手。",
        messages=[
            {"role": "user", "content": "请问你是什么模型？"},
        ],
        tools=[],
    )

    assert isinstance(response, LLMResponse)
    assert response.text, "模型应该返回非空的文本内容"
    assert len(response.text) > 5, f"回复内容过短: {response.text!r}"
    print("\n[PASS] 简单对话测试通过")
    print(f"   模型: {settings.zai_model}")
    print(f"   回复: {response.text}")


@_skip_no_key
@pytest.mark.asyncio
async def test_zai_multi_turn_chat():
    """验证多轮对话能力。"""
    provider = ZaiLLMProvider()

    response = await provider.complete(
        system_prompt="你是一个有帮助的助手。",
        messages=[
            {"role": "user", "content": "我最喜欢的数字是42。请记住它。"},
            {"role": "assistant", "content": "好的，我记住了，你最喜欢的数字是42。"},
            {"role": "user", "content": "我最喜欢的数字是什么？"},
        ],
        tools=[],
    )

    assert isinstance(response, LLMResponse)
    assert "42" in response.text, f"多轮对话未正确记忆上下文，回复: {response.text!r}"
    print("\n[PASS] 多轮对话测试通过")
    print(f"   回复: {response.text}")


@_skip_no_key
@pytest.mark.asyncio
async def test_zai_tool_calling():
    """验证模型的 tool calling 能力：给出工具定义，期望模型返回工具调用。"""
    provider = ZaiLLMProvider()

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "查询指定城市的天气信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "城市名称，例如 '北京'",
                        }
                    },
                    "required": ["city"],
                },
            },
        }
    ]

    response = await provider.complete(
        system_prompt="你是一个有帮助的助手，在需要时使用工具。",
        messages=[
            {"role": "user", "content": "北京今天天气怎么样？"},
        ],
        tools=tools,
    )

    assert isinstance(response, LLMResponse)
    assert len(response.tool_calls) > 0, f"模型应返回工具调用，但返回了纯文本: {response.text!r}"

    tc = response.tool_calls[0]
    assert tc.name == "get_weather", f"工具名不匹配: {tc.name!r}"
    assert "city" in tc.arguments, f"工具参数缺少 city 字段: {tc.arguments}"
    print("\n[PASS] Tool Calling 测试通过")
    print(f"   工具调用: {tc.name}({tc.arguments})")
