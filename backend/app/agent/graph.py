from __future__ import annotations

from typing import Any, TypedDict


class TestAgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    turn_count: int
    termination_reason: str


def build_graph() -> Any:
    """Build a minimal LangGraph object when the dependency is available.

    P0 uses AgentRunner for explicit WebSocket event control; this function keeps
    the LangGraph integration point concrete for the next phase.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("langgraph 未安装，无法构建 Agent 图") from exc

    graph = StateGraph(TestAgentState)
    graph.add_node("done", lambda state: state)
    graph.add_edge(START, "done")
    graph.add_edge("done", END)
    return graph.compile()
