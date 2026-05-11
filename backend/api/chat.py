from __future__ import annotations

from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agent import AgentRunner
from llm import create_llm_provider
from tools import build_tool_registry

router = APIRouter()


@router.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    topology = websocket.app.state.topology
    pool = websocket.app.state.transport_pool
    tools = build_tool_registry(topology, pool)
    runner = AgentRunner(topology=topology, tools=tools, llm=create_llm_provider())

    try:
        while True:
            payload: dict[str, Any] = await websocket.receive_json()
            if payload.get("type") != "user_message":
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "code": "unsupported_message",
                            "message": "仅支持 user_message 消息",
                        },
                    }
                )
                continue

            data = payload.get("data") or {}
            content = str(data.get("content", "")).strip()
            if not content:
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {"code": "empty_message", "message": "消息不能为空"},
                    }
                )
                continue

            max_turns = data.get("max_turns")
            max_turns = int(max_turns) if max_turns else None
            async for event in runner.run(content, max_turns=max_turns):
                await websocket.send_json(event)

    except WebSocketDisconnect:
        return
