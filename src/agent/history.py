"""会话历史持久化：每会话一个 JSON 文件，存展示气泡(display)与模型上下文(conv)。

- display：前端还原展示用的干净气泡（用户原始文本 + 助手 route/sources/tools/正文）。
- conv：模型上下文（含 RAG 注入与工具消息），用于跨重启/重选会话的记忆恢复。
落盘到 src/data/history/{session_id}.json；生产可替换为数据库/Redis。
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List, Optional

from src.config import settings

_HISTORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "history")
_LOCK = threading.Lock()


def _path(session_id: str) -> str:
    # 仅允许安全文件名，避免路径穿越
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return os.path.join(_HISTORY_DIR, f"{safe}.json")


def _ensure_dir() -> None:
    os.makedirs(_HISTORY_DIR, exist_ok=True)


def save(
    session_id: str,
    display: List[Dict[str, Any]],
    conv: List[Dict[str, Any]],
    title: str = "",
) -> None:
    """保存（覆盖写）某会话的历史。"""
    with _LOCK:
        _ensure_dir()
        payload = {
            "id": session_id,
            "title": title,
            "updated_at": __import__("time").time(),
            "display": display,
            "conv": conv,
        }
        tmp = _path(session_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, _path(session_id))  # 原子替换，避免半写文件


def load_conv(session_id: str) -> Optional[List[Dict[str, Any]]]:
    """读取模型上下文；不存在返回 None。"""
    p = _path(session_id)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f).get("conv")
    except Exception:
        return None


def load_display(session_id: str) -> Optional[List[Dict[str, Any]]]:
    """读取展示气泡；不存在返回 None。"""
    p = _path(session_id)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f).get("display")
    except Exception:
        return None


def list_sessions() -> List[Dict[str, Any]]:
    """列出所有会话（按更新时间倒序），每项含 id/title/updated_at。"""
    _ensure_dir()
    out: List[Dict[str, Any]] = []
    for name in os.listdir(_HISTORY_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(_HISTORY_DIR, name), "r", encoding="utf-8") as f:
                data = json.load(f)
            out.append(
                {
                    "id": data.get("id", name[:-5]),
                    "title": data.get("title", "") or "(无标题)",
                    "updated_at": data.get("updated_at", 0),
                }
            )
        except Exception:
            continue
    out.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return out


def delete_session(session_id: str) -> bool:
    """删除某会话历史文件；成功返回 True。"""
    p = _path(session_id)
    if os.path.isfile(p):
        with _LOCK:
            os.remove(p)
        return True
    return False
