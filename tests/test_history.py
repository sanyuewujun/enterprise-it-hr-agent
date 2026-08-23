"""历史记录单测：落盘/加载/列表/删除，以及 run() 的持久化与恢复。"""
import unittest.mock as mock

from src.agent import agent as agent_mod
from src.agent import history


def _fake_non_injection():
    class FakeMsg:
        content = '{"injection": false}'

    class FakeChoice:
        message = FakeMsg()

    class FakeResp:
        choices = [FakeChoice()]

    return FakeResp()


async def _fake_classify(messages):
    return {"route": "simple", "reason": ""}


async def _fake_simple_stream(messages):
    for t in ["你好呀"]:
        yield t


async def _fake_guard(text):
    return (False, "")


def test_save_load_list_delete():
    sid = "hist-test-123"
    history.delete_session(sid)
    display = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！"},
    ]
    conv = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！"},
    ]
    history.save(sid, display, conv, title="你好")
    assert history.load_conv(sid) == conv
    assert history.load_display(sid) == display
    metas = history.list_sessions()
    assert any(m["id"] == sid for m in metas)
    assert history.delete_session(sid) is True
    assert history.load_conv(sid) is None


def test_run_persists_and_accumulates():
    sid = "hist-run-abc"
    history.delete_session(sid)
    patches = dict(
        classify=mock.patch.object(agent_mod, "aclassify", new=_fake_classify),
        simple=mock.patch.object(agent_mod, "asimple_answer_stream", new=_fake_simple_stream),
        guard=mock.patch.object(agent_mod, "aguard", new=_fake_guard),
    )
    for p in patches.values():
        p.start()
    try:
        list(agent_mod.run("你好", sid))
        disp = history.load_display(sid)
        assert disp is not None
        assert disp[0]["role"] == "user" and disp[0]["content"] == "你好"
        assert disp[1]["role"] == "assistant" and "你好" in disp[1]["content"]

        # 第二轮：conv 应累积（记忆恢复）
        list(agent_mod.run("再问一次", sid))
        conv = history.load_conv(sid)
        assert sum(1 for m in conv if m["role"] == "user") == 2
    finally:
        for p in patches.values():
            p.stop()
    history.delete_session(sid)
