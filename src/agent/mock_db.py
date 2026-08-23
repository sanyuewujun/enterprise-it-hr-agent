"""Mock 企业后端：员工目录 / IT 资产 / 假期余额。

当前用本地 JSON 模拟。生产环境应替换为真实 HR / IT 系统 API（如北森、Moka、SAP、ITSM 等）。
每个函数都给出了「真实接入示例」分支（注释态，带 TODO(生产)），工具与 Agent 逻辑无需改动，
只需把数据来源从本地 JSON 换成真实接口调用即可。
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

_MOCK_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "mock")

# ===== 生产接入示例所需的配置（从环境变量读取，避免硬编码）=====
# HR_API_BASE = os.getenv("HR_API_BASE", "https://hr.internal.example.com/api")
# HR_API_TOKEN = os.getenv("HR_API_TOKEN", "")
# ITSM_API_BASE = os.getenv("ITSM_API_BASE", "https://itsm.internal.example.com/api")
# ITSM_API_TOKEN = os.getenv("ITSM_API_TOKEN", "")


def _load(name: str) -> list:
    path = os.path.join(_MOCK_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_employee(name: Optional[str] = None, emp_id: Optional[str] = None) -> Optional[Dict]:
    """按姓名或工号查询员工目录。

    TODO(生产): 替换为 HR 系统 API，例如：
        import requests
        resp = requests.get(
            f"{HR_API_BASE}/employees",
            params={"name": name, "emp_id": emp_id},
            headers={"Authorization": f"Bearer {HR_API_TOKEN}"},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json().get("data")
        return data[0] if data else None
    """
    employees: List[Dict] = _load("employees.json")
    for e in employees:
        if emp_id and e["emp_id"] == emp_id:
            return e
        if name and e["name"] == name:
            return e
    return None


def get_assets(emp_id: str) -> List[Dict]:
    """查询员工名下 IT 资产。

    TODO(生产): 替换为 ITAM / ITSM 系统 API，例如：
        resp = requests.get(
            f"{ITSM_API_BASE}/assets",
            params={"emp_id": emp_id, "status": "in_use"},
            headers={"Authorization": f"Bearer {ITSM_API_TOKEN}"},
            timeout=5,
        )
        return resp.json().get("data", [])
    """
    records: List[Dict] = _load("it_assets.json")
    for r in records:
        if r["emp_id"] == emp_id:
            return r["assets"]
    return []


def get_leave_balance(emp_id: str) -> Optional[Dict]:
    """查询员工假期余额。

    TODO(生产): 替换为 HR 系统考勤模块 API，例如：
        resp = requests.get(
            f"{HR_API_BASE}/attendance/leave-balance",
            params={"emp_id": emp_id},
            headers={"Authorization": f"Bearer {HR_API_TOKEN}"},
            timeout=5,
        )
        return resp.json().get("data")
    """
    balances: List[Dict] = _load("leave_balances.json")
    for b in balances:
        if b["emp_id"] == emp_id:
            return b
    return None


if __name__ == "__main__":
    print(get_employee(name="张伟"))
    print(get_assets("E1001"))
    print(get_leave_balance("E1001"))
