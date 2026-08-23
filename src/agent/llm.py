"""LLM 接入层：封装 SiliconFlow（OpenAI 兼容）的对话、嵌入与重排序调用。

性能说明（异步化）：
- 同步版本 `chat` / `embed_texts` 保留，供入库脚本（scripts/ingest.py）与单测使用；
- 异步版本 `achat` / `aembed_texts` / `arerank` 供在线服务路径（agent.arun / API 异步端点）
  使用，避免在网络 IO 期间阻塞事件循环，从而支持并发请求。

所有模型名均来自 settings，不在此处硬编码。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Sequence

import httpx
from openai import AsyncOpenAI, OpenAI

from src.config import settings

# 异步客户端按事件循环缓存：uvicorn 单循环复用同一实例；
# 测试用 asyncio.run 每次新建循环时也能拿到独立实例，避免 "Event loop is closed"。
_async_clients: Dict[int, AsyncOpenAI] = {}


def get_client() -> OpenAI:
    """返回 SiliconFlow OpenAI 兼容同步客户端（单例式复用）。"""
    return OpenAI(
        api_key=settings.siliconflow_api_key,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout,
    )


def get_async_client() -> AsyncOpenAI:
    """返回绑定到当前事件循环的 SiliconFlow 异步客户端（按 loop 缓存）。"""
    loop = asyncio.get_event_loop()
    key = id(loop)
    client = _async_clients.get(key)
    if client is None:
        client = AsyncOpenAI(
            api_key=settings.siliconflow_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout,
        )
        _async_clients[key] = client
    return client


def chat(
    messages: Sequence[Dict[str, str]],
    *,
    model: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    stream: bool = False,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict[str, str]] = None,
    enable_thinking: Optional[bool] = None,
) -> Any:
    """同步对话补全（供入库脚本 / 单测 / 遗留同步路径使用）。"""
    client = get_client()
    kwargs: Dict[str, Any] = {
        "model": model or settings.chat_model,
        "messages": list(messages),
        "temperature": temperature,
        "stream": stream,
    }
    if tools is not None:
        kwargs["tools"] = tools
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if response_format is not None:
        kwargs["response_format"] = response_format
    if enable_thinking is not None:
        kwargs["extra_body"] = {"enable_thinking": enable_thinking}
    return client.chat.completions.create(**kwargs)


async def achat(
    messages: Sequence[Dict[str, str]],
    *,
    model: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    stream: bool = False,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict[str, str]] = None,
    enable_thinking: Optional[bool] = None,
) -> Any:
    """异步对话补全（在线服务路径使用，不阻塞事件循环）。"""
    client = get_async_client()
    kwargs: Dict[str, Any] = {
        "model": model or settings.chat_model,
        "messages": list(messages),
        "temperature": temperature,
        "stream": stream,
    }
    if tools is not None:
        kwargs["tools"] = tools
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if response_format is not None:
        kwargs["response_format"] = response_format
    if enable_thinking is not None:
        kwargs["extra_body"] = {"enable_thinking": enable_thinking}
    return await client.chat.completions.create(**kwargs)


def embed_texts(texts: Sequence[str]) -> List[List[float]]:
    """同步批量获取文本嵌入向量（单次请求传数组，入库更快）。"""
    if not texts:
        return []
    client = get_client()
    resp = client.embeddings.create(
        model=settings.embed_model,
        input=list(texts),
    )
    return [item.embedding for item in resp.data]


async def aembed_texts(texts: Sequence[str]) -> List[List[float]]:
    """异步批量获取文本嵌入向量（在线检索路径使用）。"""
    if not texts:
        return []
    client = get_async_client()
    resp = await client.embeddings.create(
        model=settings.embed_model,
        input=list(texts),
    )
    return [item.embedding for item in resp.data]


async def arerank(
    query: str,
    documents: Sequence[str],
    *,
    top_n: Optional[int] = None,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """异步重排序：调用 SiliconFlow rerank 端点，对候选文档按与 query 相关性打分。

    返回与输入顺序一致的列表，每项含 {"index": int, "score": float, "text": str}，
    已按 score 降序排列。任何异常（模型不可用 / 网络错误）均降级为「保持原顺序、
    分数置 1.0」，保证检索链路不中断。

    时间复杂度：单次 HTTP 调用 O(1) 网络往返；rerank 模型内部 O(n)（n=候选数）。
    """
    if not documents:
        return []
    model = model or settings.rerank_model
    top_n = top_n if top_n is not None else len(documents)
    payload = {
        "model": model,
        "query": query,
        "documents": list(documents),
        "top_n": min(top_n, len(documents)),
        "return_documents": True,
    }
    try:
        async with httpx.AsyncClient(base_url=settings.llm_base_url, timeout=settings.llm_timeout) as client:
            resp = await client.post(
                "/rerank",
                headers={"Authorization": f"Bearer {settings.siliconflow_api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        results = data.get("results", [])
        out: List[Dict[str, Any]] = []
        for r in results:
            idx = r.get("index", 0)
            out.append(
                {
                    "index": idx,
                    "score": float(r.get("relevance_score", 0.0)),
                    "text": documents[idx] if 0 <= idx < len(documents) else "",
                }
            )
        return out
    except Exception:
        # 降级：保持原顺序，分数置 1.0（调用方按阈值过滤时需注意）
        return [
            {"index": i, "score": 1.0, "text": documents[i]}
            for i in range(len(documents))
        ]
