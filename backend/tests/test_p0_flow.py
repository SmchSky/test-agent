from __future__ import annotations

import pytest

from agent import AgentRunner
from core.config import settings
from infra.transport.pool import TransportPool
from llm.mock_provider import MockLLMProvider
from services.context_window import micro_compact_messages
from services.topology import TopologyService
from tools import build_tool_registry


def test_topology_seed_loads_fixed_ospf_topology() -> None:
    topology = TopologyService.from_yaml(settings.topology_seed_path)

    assert topology.device_names() == ["R1", "R2", "R3"]
    assert topology.resolve_device("R1").management_ip == "10.10.10.1"
    assert len(topology.find_link("R1", "R2")) == 1


def test_micro_compact_clears_old_verbose_tool_outputs() -> None:
    messages = [
        {"role": "tool", "content": "a" * 3000},
        {"role": "tool", "content": "b" * 3000},
        {"role": "tool", "content": "c" * 3000},
        {"role": "tool", "content": "d" * 3000},
        {"role": "tool", "content": "e" * 3000},
        {"role": "assistant", "content": "ok"},
    ]

    compacted = micro_compact_messages(messages)

    assert compacted[0]["content"].startswith("[命令输出已清理")
    assert compacted[1]["content"] == "b" * 3000


@pytest.mark.asyncio
async def test_mock_agent_runs_p0_ospf_flow() -> None:
    topology = TopologyService.from_yaml(settings.topology_seed_path)
    pool = TransportPool(idle_ttl=30, reap_interval=60)
    await pool.startup()
    try:
        runner = AgentRunner(
            topology=topology,
            tools=build_tool_registry(topology, pool),
            llm=MockLLMProvider(),
        )
        events = [
            event
            async for event in runner.run(
                "在 R1 和 R2 之间配置 OSPF 邻居，area 0，验证邻居建立成功",
                max_turns=5,
            )
        ]
    finally:
        await pool.shutdown()

    assert [event["type"] for event in events].count("tool_call_result") == 4
    assert events[-1] == {
        "type": "agent_done",
        "data": {"reason": "completed", "turn_count": 3},
    }
