"""意图路由：用云端小模型（settings.small_model）做意图分类，并对简单问题直答。

设计目标：简单问题（问候/自我介绍/闲聊）由小模型快速回答，不进入 RAG/工具链路，
降低主模型调用成本与延迟；复杂问题交由主 Agent 处理。
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from src.agent.llm import achat, chat
from src.agent.prompts import ROUTER_SYSTEM, SIMPLE_SYSTEM
from src.config import settings


def classify(messages: List[Dict[str, str]]) -> Dict[str, str]:
    """返回 {"route": "simple"|"complex", "reason": str}。

    使用小模型 + JSON 输出模式，速度快、成本低。
    """
    if not settings.enable_intent_routing:
        return {"route": "complex", "reason": "路由已关闭，默认走主Agent"}

    last_user = ""
    for m in reversed(messages):
        if m["role"] == "user":
            last_user = m["content"]
            break

    # 极短且无业务语义的问候直接判 simple，省一次模型调用
    if last_user.strip() in {"你好", "您好", "hi", "hello", "在吗", "谢谢", "感谢"}:
        return {"route": "simple", "reason": "纯问候/致谢"}

    try:
        resp = chat(
            [{"role": "system", "content": ROUTER_SYSTEM}] + messages,
            model=settings.small_model,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)
        route = data.get("route", "complex")
        if route not in ("simple", "complex"):
            route = "complex"
        return {"route": route, "reason": data.get("reason", "")}
    except Exception as e:  # 分类失败则保守走主Agent
        return {"route": "complex", "reason": f"分类异常: {e}"}


async def aclassify(messages: List[Dict[str, str]]) -> Dict[str, str]:
    """异步版意图分类（在线服务路径使用，不阻塞事件循环）。"""
    if not settings.enable_intent_routing:
        return {"route": "complex", "reason": "路由已关闭，默认走主Agent"}

    last_user = ""
    for m in reversed(messages):
        if m["role"] == "user":
            last_user = m["content"]
            break

    # 极短且无业务语义的问候直接判 simple，省一次模型调用
    if last_user.strip() in {"你好", "您好", "hi", "hello", "在吗", "谢谢", "感谢"}:
        return {"route": "simple", "reason": "纯问候/致谢"}

    try:
        resp = await achat(
            [{"role": "system", "content": ROUTER_SYSTEM}] + messages,
            model=settings.small_model,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)
        route = data.get("route", "complex")
        if route not in ("simple", "complex"):
            route = "complex"
        return {"route": route, "reason": data.get("reason", "")}
    except Exception as e:  # 分类失败则保守走主Agent
        return {"route": "complex", "reason": f"分类异常: {e}"}


def simple_answer(messages: List[Dict[str, str]]) -> str:
    """用轻量小模型直接回答简单问题（不思考、低延迟）。"""
    resp = chat(
        [{"role": "system", "content": SIMPLE_SYSTEM}] + messages,
        model=settings.small_model,
        temperature=0.3,
        stream=False,
    )
    return resp.choices[0].message.content or ""


def simple_answer_stream(messages: List[Dict[str, str]]):
    """流式直答，返回 token 迭代器。"""
    stream = chat(
        [{"role": "system", "content": SIMPLE_SYSTEM}] + messages,
        model=settings.small_model,
        temperature=0.3,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content


async def asimple_answer_stream(messages: List[Dict[str, str]]):
    """异步流式直答，返回 token 异步迭代器（在线服务路径使用）。"""
    stream = await achat(
        [{"role": "system", "content": SIMPLE_SYSTEM}] + messages,
        model=settings.small_model,
        temperature=0.3,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content
