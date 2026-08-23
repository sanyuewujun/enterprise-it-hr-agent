"""RAG 分块与路由（不联网部分）测试。"""
import asyncio

import src.agent.llm as llm_mod
from src.agent.rag import chunk_markdown
from src.agent.router import classify
from src.config import settings


def test_chunk_markdown_splits_by_heading():
    text = "# 标题一\n第一段内容。\n## 小标题\n第二段内容较长需要切分的内容用于测试分块逻辑是否正常工作并且不超过单块上限。\n第三段。"
    chunks = chunk_markdown(text, source="test.md")
    assert len(chunks) >= 2
    assert chunks[0].source == "test.md"
    # 至少一块带 heading
    assert any(c.heading for c in chunks)


def test_chunk_markdown_size_limit():
    long_text = "这是一段很长的文本。" * 200  # 远超 CHUNK_SIZE
    chunks = chunk_markdown(long_text, source="big.md")
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.content) <= 600  # 含标题行余量


def test_chunk_markdown_overlap():
    """单段超长文本（多行）应采用滑动窗口，相邻块共享 overlap 个字符。"""
    sentence = "这是一段用于测试分块重叠的连续文本。"
    para = "\n".join([sentence] * 60)  # 多行，单行不超长，整体远超 chunk_size
    text = f"# 标题\n{para}"
    chunks = chunk_markdown(text, source="overlap.md")
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.content) <= settings.chunk_size
    overlap = settings.chunk_overlap
    # 校验相邻「满长」窗口的重叠特性
    checked = 0
    for a, b in zip(chunks, chunks[1:]):
        if len(a.content) == settings.chunk_size and len(b.content) == settings.chunk_size:
            assert a.content[-overlap:] == b.content[:overlap]
            checked += 1
    assert checked >= 1  # 至少存在一对重叠窗口


def test_arerank_fallback_on_error(monkeypatch):
    """rerank 端点不可用时降级为保持原顺序、分数置 1.0。"""

    class _FakePost:
        async def __call__(self, *args, **kwargs):
            raise RuntimeError("rerank unavailable")

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def post(self, *args, **kwargs):
            return _FakePost()()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _FakeClient)
    res = asyncio.run(llm_mod.arerank("查询年假", ["doc-a", "doc-b", "doc-c"]))
    assert len(res) == 3
    assert [r["index"] for r in res] == [0, 1, 2]
    assert all(r["score"] == 1.0 for r in res)



def test_classify_exact_greeting_no_network():
    # 纯问候走快捷判定，不调用模型
    res = classify([{"role": "user", "content": "你好"}])
    assert res["route"] == "simple"


def test_classify_disabled_returns_complex():
    original = settings.enable_intent_routing
    settings.enable_intent_routing = False
    try:
        res = classify([{"role": "user", "content": "你好"}])
        assert res["route"] == "complex"
    finally:
        settings.enable_intent_routing = original
