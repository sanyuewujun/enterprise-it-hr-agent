"""工具层测试（不依赖联网，仅用 Mock 后端）。"""
from src.agent.tools import build_tools, dispatch


def test_build_tools_non_empty():
    tools = build_tools()
    assert len(tools) == 6
    names = {t["function"]["name"] for t in tools}
    assert {"search_policy", "query_employee", "create_it_ticket", "escalate_to_human"} <= names


def test_query_employee_tool():
    res = dispatch("query_employee", {"name": "张伟"})
    assert res["found"] is True
    assert res["employee"]["emp_id"] == "E1001"


def test_check_leave_balance_tool():
    res = dispatch("check_leave_balance", {"emp_id": "E1001"})
    assert res["annual_leave_remaining"] == 7


def test_create_it_ticket_tool():
    res = dispatch("create_it_ticket", {"title": "测试", "description": "单元测试", "priority": "low"})
    assert res["success"] is True
    assert res["ticket_id"].startswith("IT-")


def test_escalate_tool():
    res = dispatch("escalate_to_human", {"reason": "涉及薪资调整"})
    assert res["escalated"] is True


def test_dispatch_unknown():
    assert "error" in dispatch("no_such_tool", {})
