"""Mock 后端数据层测试（无需联网）。"""
from src.agent.mock_db import get_assets, get_employee, get_leave_balance


def test_get_employee_by_name():
    emp = get_employee(name="张伟")
    assert emp is not None
    assert emp["emp_id"] == "E1001"
    assert emp["department"] == "技术部"


def test_get_employee_by_id():
    emp = get_employee(emp_id="E1003")
    assert emp["name"] == "王芳"


def test_get_employee_not_found():
    assert get_employee(name="不存在的人") is None


def test_get_assets():
    assets = get_assets("E1001")
    assert len(assets) == 3
    assert any(a["type"] == "laptop" for a in assets)


def test_get_leave_balance():
    bal = get_leave_balance("E1001")
    assert bal["annual_leave"] - bal["annual_leave_used"] == 7
