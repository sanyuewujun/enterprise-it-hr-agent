"""主 Agent：复杂问题走 记忆 -> RAG 注入 -> 工具调用循环 -> SSE 流式输出。

对外暴露异步生成器 arun()，逐条产出事件字典（在线服务路径，不阻塞事件循环）：
  {"type":"route", "route": "simple"|"complex"|"blocked", "reason": str}
  {"type":"source", "items":[{"source","heading","score"}]}
  {"type":"token", "content": str}
  {"type":"tool", "name": str, "arguments": dict, "result": any}
  {"type":"done", "note": str}
API 层负责将其序列化为 SSE。

为兼容单测与遗留同步调用，另提供同步包装 run()（在独立事件循环中驱动 arun）。
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from src.agent.guard import SAFE_REFUSAL, aguard
from src.agent.history import delete_session, load_conv, save as save_history
from src.agent.llm import achat
from src.agent.prompts import AGENT_SYSTEM, RAG_CONTEXT_TMPL
from src.agent.rag import ChromaStore
from src.agent.router import aclassify, asimple_answer_stream
from src.agent.tools import adispatch, build_tools
from src.config import settings

# 会话记忆（内存；生产可替换为 Redis 等外部存储）
_SESSIONS: Dict[str, List[Dict[str, Any]]] = {}
_SESSION_LOCK = threading.Lock()
_MAX_TURNS = 5  # 工具调用最大轮次

# 代次令牌：每次新消息或显式取消都会使该会话的「当前生成」失效，
# 正在运行的 arun() 在下一轮检测时退出，从而支持「取消提问」与「新消息打断旧请求」。
_GEN: Dict[str, int] = {}
_GEN_LOCK = threading.Lock()


def request_cancel(session_id: str) -> None:
    """使该会话正在进行的生成失效（取消提问）。"""
    with _GEN_LOCK:
        _GEN[session_id] = _GEN.get(session_id, 0) + 1


def _get_conv(session_id: str) -> List[Dict[str, Any]]:
    with _SESSION_LOCK:
        if session_id not in _SESSIONS:
            # 内存无则尝试从历史落盘恢复（跨重启/重选会话的记忆）
            conv = load_conv(session_id)
            _SESSIONS[session_id] = conv if conv is not None else []
        return _SESSIONS[session_id]


async def _aget_conv(session_id: str) -> List[Dict[str, Any]]:
    with _SESSION_LOCK:
        if session_id not in _SESSIONS:
            # 文件读取为阻塞 IO，交给线程池执行，避免阻塞事件循环
            conv = await asyncio.to_thread(load_conv, session_id)
            _SESSIONS[session_id] = conv if conv is not None else []
        return _SESSIONS[session_id]


def reset_session(session_id: str) -> None:
    with _SESSION_LOCK:
        _SESSIONS.pop(session_id, None)
    delete_session(session_id)
    request_cancel(session_id)


def _wrap_user(text: str) -> str:
    """将用户原文包裹为不可信数据标签，配合系统提示中的安全约束。"""
    return f"<<USER>>\n{text}\n<</USER>>"


def _title(text: str, limit: int = 20) -> str:
    t = text.strip().replace("\n", " ")
    return t[:limit] + ("…" if len(t) > limit else "")


async def arun(user_msg: str, session_id: str = "default") -> AsyncIterator[Dict[str, Any]]:
    """处理一条用户消息，异步产出事件流（不阻塞事件循环）。"""
    conv = await _aget_conv(session_id)

    # 代次令牌：本生成的有效代号；一旦被取消或新消息到来即失效
    with _GEN_LOCK:
        my_gen = _GEN.get(session_id, 0) + 1
        _GEN[session_id] = my_gen

    def _cancelled() -> bool:
        return _GEN.get(session_id) != my_gen

    # 展示气泡（用于前端历史还原）；助手气泡随事件累积
    display: List[Dict[str, Any]] = [{"role": "user", "content": user_msg}]
    abubble: Dict[str, Any] = {
        "role": "assistant",
        "content": "",
        "route": None,
        "sources": [],
        "tools": [],
    }

    def _persist() -> None:
        # 助手气泡写入展示历史并落盘（display + 模型上下文 conv）
        if abubble["content"] or abubble["route"] or abubble["tools"]:
            display.append(dict(abubble))
        save_history(session_id, display, conv, title=_title(user_msg))

    # 0) 提示词注入防护（规则 + 小模型兜底）
    blocked, reason = await aguard(user_msg)
    if blocked:
        yield {"type": "route", "route": "blocked", "reason": reason}
        abubble["route"] = "blocked"
        abubble["content"] = SAFE_REFUSAL
        yield {"type": "token", "content": SAFE_REFUSAL}
        await asyncio.to_thread(_persist)
        yield {"type": "done", "note": None}
        return

    try:
        # 1) 意图路由
        route = await aclassify(conv + [{"role": "user", "content": _wrap_user(user_msg)}])
        if _cancelled():
            yield {"type": "done", "note": "已取消"}
            return
        yield {"type": "route", "route": route["route"], "reason": route.get("reason", "")}
        abubble["route"] = route["route"]

        # 2) 简单问题：小模型直答（流式）
        if route["route"] == "simple":
            full: List[str] = []
            async for tok in asimple_answer_stream(
                conv + [{"role": "user", "content": _wrap_user(user_msg)}]
            ):
                if _cancelled():
                    break
                full.append(tok)
                yield {"type": "token", "content": tok}
            abubble["content"] = "".join(full)
            # 轻量速答也写入会话历史，保证多轮上下文
            conv.append({"role": "user", "content": user_msg})
            conv.append({"role": "assistant", "content": abubble["content"]})
            yield {"type": "done", "note": "已取消" if _cancelled() else None}
            return

        # 3) 复杂问题：RAG 预检索 + 注入上下文（向量召回 + 重排序精排）
        store = ChromaStore()
        results = await store.aquery(user_msg, k=settings.rag_top_k, score_threshold=settings.rag_score_threshold)
        yield {
            "type": "source",
            "items": [
                {"source": r["source"], "heading": r["heading"], "score": r["score"]}
                for r in results
            ],
        }
        if _cancelled():
            yield {"type": "done", "note": "已取消"}
            return
        abubble["sources"] = [
            {"source": r["source"], "heading": r["heading"], "score": r["score"]}
            for r in results
        ]
        context = "\n\n".join(
            f"[{i+1}] 来源《{r['source']}》- {r['heading']}\n{r['content']}"
            for i, r in enumerate(results)
        )
        user_content = RAG_CONTEXT_TMPL.format(
            context=context or "（无相关制度）", question=_wrap_user(user_msg)
        )
        conv.append({"role": "user", "content": user_content})

        # 4) 工具调用循环
        for _ in range(_MAX_TURNS):
            if _cancelled():
                break
            stream = await achat(
                [{"role": "system", "content": AGENT_SYSTEM}] + conv,
                model=settings.chat_model,
                tools=build_tools(),
                stream=True,
                temperature=0.3,
            )
            assistant_msg: Dict[str, Any] = {"role": "assistant", "content": ""}
            tool_calls_acc: Dict[int, Dict[str, Any]] = {}
            finish_reason: Optional[str] = None

            async for chunk in stream:
                if _cancelled():
                    break
                choice = chunk.choices[0]
                delta = choice.delta
                finish_reason = choice.finish_reason or finish_reason
                if delta.content:
                    assistant_msg["content"] += delta.content
                    abubble["content"] += delta.content
                    yield {"type": "token", "content": delta.content}
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index if tc.index is not None else 0
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "args": ""}
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                        if tc.function and tc.function.name:
                            tool_calls_acc[idx]["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            tool_calls_acc[idx]["args"] += tc.function.arguments

            # 有工具调用 -> 执行并继续循环
            if tool_calls_acc:
                tool_calls_for_api = []
                for idx in sorted(tool_calls_acc):
                    t = tool_calls_acc[idx]
                    tool_calls_for_api.append(
                        {
                            "id": t["id"] or f"call_{idx}",
                            "type": "function",
                            "function": {"name": t["name"], "arguments": t["args"]},
                        }
                    )
                assistant_msg["tool_calls"] = tool_calls_for_api
                conv.append(assistant_msg)

                for t in tool_calls_for_api:
                    name = t["function"]["name"]
                    try:
                        args = json.loads(t["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = await adispatch(name, args)
                    tool_badge = {
                        "name": name,
                        "arguments": args,
                        "result": result,
                    }
                    abubble["tools"].append(tool_badge)
                    yield {"type": "tool", "name": name, "arguments": args, "result": result}
                    conv.append(
                        {
                            "role": "tool",
                            "tool_call_id": t["id"],
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                if _cancelled():
                    yield {"type": "done", "note": "已取消"}
                    return
                continue

            # 无工具调用 -> 最终答复
            conv.append(assistant_msg)
            yield {"type": "done", "note": "已取消" if _cancelled() else None}
            return

        if _cancelled():
            yield {"type": "done", "note": "已取消"}
        else:
            yield {"type": "done", "note": "已达到最大工具调用轮次，请简化问题或转人工。"}
    finally:
        await asyncio.to_thread(_persist)


def run(user_msg: str, session_id: str = "default") -> Iterator[Dict[str, Any]]:
    """同步兼容包装：在独立事件循环中驱动 arun（供单测 / 遗留同步调用）。

    在线服务路径请直接使用 arun()（异步），以获得并发能力。
    """
    import asyncio

    async def _collect() -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        async for ev in arun(user_msg, session_id):
            out.append(ev)
        return out

    return iter(asyncio.run(_collect()))
