"""FastAPI 后端：提供对话 SSE 接口、入库、工具清单、健康检查，并托管前端构建产物。"""
from __future__ import annotations

import asyncio
import json
import os
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from src.agent.agent import arun, reset_session, request_cancel
from src.agent.history import delete_session, list_sessions, load_display
from src.agent.tools import build_tools
from src.config import settings

app = FastAPI(title="企业智能 IT/HR 助手", version="1.0.0")


# ---------- 中间件：可选 API Key 校验 ----------
@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    if settings.api_key:
        # 健康检查与静态资源不强制校验
        path = request.url.path
        if not (path.startswith("/api/health") or path == "/" or path.startswith("/assets")):
            provided = request.headers.get("X-API-Key", "")
            if provided != settings.api_key:
                # middleware 必须返回 Response，不能返回 HTTPException 实例
                return JSONResponse(status_code=401, content={"detail": "Invalid API Key"})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 请求模型 ----------
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class IngestRequest(BaseModel):
    force: bool = False


# ---------- 接口 ----------
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "chat_model": settings.chat_model,
        "small_model": settings.small_model,
        "embed_model": settings.embed_model,
        "intent_routing": settings.enable_intent_routing,
    }


@app.get("/api/tools")
def list_tools():
    return {"tools": build_tools()}


@app.post("/api/ingest")
async def ingest(req: IngestRequest):
    from scripts.ingest import run as ingest_run

    # 入库为批量嵌入的阻塞 IO，放到线程池执行，避免阻塞事件循环
    summary = await asyncio.to_thread(ingest_run, force=req.force)
    return {"status": "ingested", **summary}


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    async def event_stream():
        try:
            async for ev in arun(req.message, req.session_id):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:  # 流式中断时给出错误事件
            err = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/reset")
def reset(req: ChatRequest):
    reset_session(req.session_id)
    return {"status": "reset"}


@app.post("/api/cancel")
def cancel(req: ChatRequest):
    """取消该会话正在进行的生成（避免上一个问题卡死）。"""
    request_cancel(req.session_id)
    return {"status": "cancelled", "session_id": req.session_id}


@app.get("/api/sessions")
def get_sessions():
    """列出历史会话（按更新时间倒序）。"""
    return {"sessions": list_sessions()}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    """读取某会话的展示气泡，用于前端还原并继续对话。"""
    display = load_display(session_id)
    if display is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "messages": display}


@app.delete("/api/sessions/{session_id}")
def delete_session_endpoint(session_id: str):
    """删除某会话历史。"""
    ok = delete_session(session_id)
    return {"status": "deleted" if ok else "not_found", "session_id": session_id}


# ---------- 托管前端构建产物（生产）----------
_DIST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "web", "dist"
)
if os.path.isdir(_DIST):
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_DIST, html=True), name="static")
