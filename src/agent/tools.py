"""工具层：以装饰器注册可被模型 function-calling 调用的 HR/IT 工具。

工具实现当前对接 Mock 后端（src/agent/mock_db.py），生产替换为真实系统 API 即可。
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Dict, List

from src.agent.mock_db import get_assets, get_employee, get_leave_balance
from src.agent.rag import ChromaStore

# 工具注册表与 OpenAI 工具描述
TOOL_REGISTRY: Dict[str, Callable[..., Any]] = {}
TOOL_SPECS: Dict[str, Any] = {}

_store = ChromaStore()
_ticket_counter = {"n": 1000}
_ticket_lock = threading.Lock()
_created_tickets: List[Dict] = []


def tool(name: str, description: str, parameters: Dict[str, Any]) -> Callable:
    """装饰器：注册一个工具并生成 OpenAI function 描述。"""

    def deco(func: Callable) -> Callable:
        TOOL_REGISTRY[name] = func
        TOOL_SPECS[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }
        return func

    return deco


def build_tools() -> List[Dict[str, Any]]:
    """返回 OpenAI 工具定义列表。"""
    return list(TOOL_SPECS.values())


def dispatch(name: str, arguments: Dict[str, Any]) -> Any:
    """按名称分发执行工具（同步）。"""
    if name not in TOOL_REGISTRY:
        return {"error": f"未知工具: {name}"}
    return TOOL_REGISTRY[name](**arguments)


async def adispatch(name: str, arguments: Dict[str, Any]) -> Any:
    """按名称分发执行工具（异步）。

    若工具函数返回协程（如 search_policy 需异步检索），则 await 之；
    否则直接返回同步结果。供 agent.arun 在线路径使用。
    """
    if name not in TOOL_REGISTRY:
        return {"error": f"未知工具: {name}"}
    result = TOOL_REGISTRY[name](**arguments)
    if asyncio.iscoroutine(result):
        result = await result
    return result


@tool(
    "search_policy",
    "在企业制度知识库中检索与问题相关的政策条款，返回带出处的文本。当用户询问公司制度、流程、规范时使用。",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索关键词或问题"}
        },
        "required": ["query"],
    },
)
async def search_policy(query: str) -> Dict[str, Any]:
    """在企业制度知识库中检索与问题相关的政策条款（异步，含重排序精排）。"""
    results = await _store.aquery(query, k=6, score_threshold=0.2)
    if not results:
        return {"found": False, "context": "未检索到相关政策。"}
    formatted = []
    for i, r in enumerate(results, 1):
        formatted.append(
            f"[{i}] 来源《{r['source']}》- {r['heading']}（相关度 {r['score']}）\n{r['content']}"
        )
    return {"found": True, "context": "\n\n".join(formatted)}


@tool(
    "query_employee",
    "按姓名或工号查询员工基本信息（部门、职位、邮箱、直属上级等）。",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "员工姓名，如 张伟"},
            "emp_id": {"type": "string", "description": "员工工号，如 E1001"},
        },
        "required": [],
    },
)
def query_employee(name: str = "", emp_id: str = "") -> Dict[str, Any]:
    emp = get_employee(name=name or None, emp_id=emp_id or None)
    if not emp:
        return {"found": False, "message": f"未找到员工 name={name} emp_id={emp_id}"}
    return {"found": True, "employee": emp}


@tool(
    "query_it_assets",
    "查询指定员工名下的 IT 资产（笔记本、显示器、外设及序列号）。",
    {
        "type": "object",
        "properties": {
            "emp_id": {"type": "string", "description": "员工工号，如 E1001"}
        },
        "required": ["emp_id"],
    },
)
def query_it_assets(emp_id: str) -> Dict[str, Any]:
    assets = get_assets(emp_id)
    if not assets:
        return {"found": False, "message": f"工号 {emp_id} 暂无登记资产"}
    return {"found": True, "emp_id": emp_id, "assets": assets}


@tool(
    "check_leave_balance",
    "查询员工假期余额（年假剩余、已用、调休、病假）。",
    {
        "type": "object",
        "properties": {
            "emp_id": {"type": "string", "description": "员工工号，如 E1001"}
        },
        "required": ["emp_id"],
    },
)
def check_leave_balance(emp_id: str) -> Dict[str, Any]:
    bal = get_leave_balance(emp_id)
    if not bal:
        return {"found": False, "message": f"工号 {emp_id} 无假期记录"}
    remaining = bal["annual_leave"] - bal["annual_leave_used"]
    return {
        "found": True,
        "emp_id": emp_id,
        "annual_leave_remaining": remaining,
        "overtime_leave": bal["overtime_leave"],
        "sick_leave": bal["sick_leave"],
        "detail": bal,
    }


@tool(
    "create_it_ticket",
    "为员工创建 IT 支持工单（如设备申领、故障报修、权限申请）。返回工单号。",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "工单标题，如 笔记本无法开机"},
            "description": {"type": "string", "description": "问题详细描述"},
            "priority": {
                "type": "string",
                "enum": ["low", "normal", "high"],
                "description": "优先级，默认 normal",
            },
            "emp_id": {"type": "string", "description": "报单员工工号，可选"},
        },
        "required": ["title", "description"],
    },
)
def create_it_ticket(
    title: str, description: str, priority: str = "normal", emp_id: str = ""
) -> Dict[str, Any]:
    with _ticket_lock:
        _ticket_counter["n"] += 1
        tid = f"IT-{_ticket_counter['n']}"
        ticket = {
            "ticket_id": tid,
            "title": title,
            "description": description,
            "priority": priority,
            "emp_id": emp_id,
            "status": "open",
        }
        _created_tickets.append(ticket)
    return {"success": True, "ticket_id": tid, "status": "open"}


@tool(
    "escalate_to_human",
    "当问题超出 AI 助手能力或涉及敏感/人工决策时，转接人工客服，并说明原因。",
    {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "需要转人工的原因"}
        },
        "required": ["reason"],
    },
)
def escalate_to_human(reason: str) -> Dict[str, Any]:
    return {
        "escalated": True,
        "reason": reason,
        "message": "已为您转接人工客服，请稍候，客服将尽快与您联系。",
    }


if __name__ == "__main__":
    import asyncio

    print("已注册工具:", list(TOOL_REGISTRY.keys()))
    print(asyncio.run(search_policy("年假怎么算"))["context"][:200])
    print(create_it_ticket("VPN 连不上", "办公室网络正常但 VPN 提示证书错误", "high", "E1001"))
    print(check_leave_balance("E1001"))
