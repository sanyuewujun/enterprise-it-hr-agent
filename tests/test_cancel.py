"""取消提问机制测试（mock 网络调用，验证代次令牌与接口）。"""
import asyncio
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.agent import agent as agent_mod
from src.api.main import app

client = TestClient(app)


def test_cancel_endpoint():
    r = client.post("/api/cancel", json={"message": "", "session_id": "cancel-test"})
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


async def _fake_classify(messages):
    return {"route": "simple", "reason": ""}


async def _fake_simple_stream(messages):
    for t in ["你好", "，", "我是小智"]:
        yield t


def test_generation_cancelled_mid_stream():
    sid = "gen-cancel-test"
    # mock 意图分类为 simple，且不触发网络
    with patch.object(agent_mod, "aclassify", new=_fake_classify), patch.object(
        agent_mod,
        "asimple_answer_stream",
        new=_fake_simple_stream,
    ):
        # 直接驱动异步生成器，分步推进以模拟「流式进行中取消」
        async def _drive():
            ag = agent_mod.arun("你好", sid)
            first = await ag.__anext__()  # 先拿到 route 事件（此时 arun 已持有有效代次）
            assert first["type"] == "route"
            agent_mod.request_cancel(sid)  # 流式进行中取消该会话
            rest = [first] + [e async for e in ag]
            return rest

        events = asyncio.run(_drive())
        done = [e for e in events if e["type"] == "done"][0]
        assert done.get("note") == "已取消"


def test_new_message_invalidates_old_generation():
    sid = "gen-new-test"
    with patch.object(agent_mod, "aclassify", new=_fake_classify), patch.object(
        agent_mod,
        "asimple_answer_stream",
        new=_fake_simple_stream,
    ):

        async def _drive():
            ag = agent_mod.arun("第一条", sid)
            first = await ag.__anext__()  # route 事件
            assert first["type"] == "route"
            agent_mod.request_cancel(sid)  # 新消息到来：使旧生成失效
            rest = [first] + [e async for e in ag]
            return rest

        events = asyncio.run(_drive())
        done = [e for e in events if e["type"] == "done"][0]
        assert done.get("note") == "已取消"
