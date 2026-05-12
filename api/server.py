"""FastAPI 服务入口：提供 /api/chat SSE 接口。"""

from __future__ import annotations

import uuid
from typing import Generator, Iterable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.agent_factory import build_user_agent
from api.map_extractor import extract_map_route
from api.sse import event_to_sse

app = FastAPI(title="Travel Agent Microservice", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    user_id: str = Field(..., description="用户唯一标识，用于隔离上下文")
    query: str = Field(..., description="用户提问")


def _chunk_text(text: str, chunk_size: int = 180) -> Iterable[str]:
    content = text.strip()
    if not content:
        return []
    return [content[i : i + chunk_size] for i in range(0, len(content), chunk_size)]


def chat_stream(user_id: str, query: str) -> Generator[str, None, None]:
    request_id = str(uuid.uuid4())[:8]
    agent = None
    yield event_to_sse({"type": "status", "request_id": request_id, "content": "正在初始化Agent..."})
    try:
        agent = build_user_agent(user_id=user_id)
        yield event_to_sse({"type": "status", "request_id": request_id, "content": "正在执行任务..."})
        final_text = agent.run(query)
        for chunk in _chunk_text(final_text):
            yield event_to_sse({"type": "text", "request_id": request_id, "content": chunk})

        route = extract_map_route(final_text, llm_client=agent.llm_client)
        yield event_to_sse({"type": "map_data", "request_id": request_id, "route": route})
        yield event_to_sse({"type": "done", "request_id": request_id})
    except Exception as exc:  # noqa: BLE001
        yield event_to_sse({"type": "error", "request_id": request_id, "content": str(exc)})
    finally:
        if agent is not None:
            agent.close()


@app.post("/api/chat")
def chat_api(payload: ChatRequest) -> StreamingResponse:
    stream = chat_stream(user_id=payload.user_id, query=payload.query)
    return StreamingResponse(stream, media_type="text/event-stream")

