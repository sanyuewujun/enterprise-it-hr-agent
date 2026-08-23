"""提示词注入防护：规则快速拦截 + 小模型分类兜底。

设计原则（克制使用 LLM）：
- 先用低成本正则规则拦截明显注入特征，命中即阻断，不消耗模型调用。
- 规则未命中时，若开启 enable_injection_llm_guard，再用小模型做一次分类兜底，
  覆盖伪装巧妙的注入；分类器调用失败按「非注入」处理，避免误伤正常业务请求。
"""
from __future__ import annotations

import json
import re
from typing import Tuple

from src.agent.llm import achat, chat
from src.agent.prompts import GUARD_SYSTEM
from src.config import settings

# 中英文常见注入特征（忽略指令、角色扮演、泄露提示词、越狱等）
_RULE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"忽略.{0,12}(之前|上面|先前|以上|所有|前面)"),
    re.compile(r"忘记.{0,12}(之前|上面|先前|以上|所有|前面)"),
    re.compile(r"覆盖.{0,12}(之前|上面|先前|以上|所有|前面).{0,6}(指令|提示|设定)"),
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above|previous\s+instructions)", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)", re.I),
    re.compile(r"system\s+prompt", re.I),
    re.compile(r"系统提示词|系统提示|你的提示词|你的指令|内部提示"),
    re.compile(r"你(现在|当前)?(的)?(指令|设定|人设|角色).{0,8}(改成|变为|覆盖|忽略|忘记|解除)"),
    re.compile(r"(扮演|假装|模拟|成为)\s*(一个|一名|成)?", re.I),
    re.compile(r"(role\s*play|pretend\s+to\s+be|act\s+as|you\s+are\s+now)", re.I),
    re.compile(r"(越狱|jailbreak|\bdan\b|developer\s+mode)", re.I),
    re.compile(r"repeat\s+your\s+instructions", re.I),
    re.compile(r"输出(你|上面|之前|内部).{0,8}(提示|指令|prompt|设定)", re.I),
    re.compile(r"把(上面|之前|以下|这些).{0,10}(当作|作为|覆盖|替换|视为).{0,8}(指令|提示|规则)"),
]

# 注入被拦截时的安全拒绝文案（引导回 IT/HR 正事，不泄露任何内部信息）
SAFE_REFUSAL = (
    "抱歉，我无法执行该请求。我是企业 IT/HR 智能助手，只能协助你解答公司制度、"
    "查询信息或办理相关业务（如查假期、查资产、建工单）。如果你有这类需求，请直接告诉我～"
)


def rule_check(text: str) -> Tuple[bool, str]:
    """正则规则快速拦截；命中返回 (True, 命中片段说明)。"""
    for pat in _RULE_PATTERNS:
        m = pat.search(text)
        if m:
            return True, f"命中注入特征：{m.group(0)}"
    return False, ""


def _extract_json(s: str) -> str:
    """从模型可能包裹了 ```json 的代码块中提取 JSON 字符串。"""
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.startswith("json"):
            s = s[4:]
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end >= 0:
        s = s[start : end + 1]
    return s


def llm_check(text: str) -> Tuple[bool, str]:
    """用小模型判断是否为提示词注入。失败按非注入处理，避免误伤正常请求。"""
    try:
        resp = chat(
            [
                {"role": "system", "content": GUARD_SYSTEM},
                {"role": "user", "content": text},
            ],
            model=settings.small_model,
            stream=False,
            temperature=0,
        )
        content = resp.choices[0].message.content or ""
        data = json.loads(_extract_json(content))
        if bool(data.get("injection")):
            return True, str(data.get("reason", "小模型判定为注入"))
    except Exception:
        return False, ""
    return False, ""


async def allm_check(text: str) -> Tuple[bool, str]:
    """异步版小模型注入判定（在线服务路径使用）。"""
    try:
        resp = await achat(
            [
                {"role": "system", "content": GUARD_SYSTEM},
                {"role": "user", "content": text},
            ],
            model=settings.small_model,
            stream=False,
            temperature=0,
        )
        content = resp.choices[0].message.content or ""
        data = json.loads(_extract_json(content))
        if bool(data.get("injection")):
            return True, str(data.get("reason", "小模型判定为注入"))
    except Exception:
        return False, ""
    return False, ""


def guard(text: str) -> Tuple[bool, str]:
    """综合防护：规则命中即拦截；否则按需调用小模型分类。返回 (blocked, reason)。"""
    blocked, reason = rule_check(text)
    if blocked:
        return True, reason
    if settings.enable_injection_llm_guard:
        return llm_check(text)
    return False, ""


async def aguard(text: str) -> Tuple[bool, str]:
    """异步版综合防护（在线服务路径使用）。"""
    blocked, reason = rule_check(text)
    if blocked:
        return True, reason
    if settings.enable_injection_llm_guard:
        return await allm_check(text)
    return False, ""
