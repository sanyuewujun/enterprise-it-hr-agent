"""RAG 管线：文档分块 -> 批量嵌入 -> Chroma 持久化 -> 带出处检索（含重排序）。

嵌入使用 SiliconFlow 云端模型，按 settings.embed_batch_size 批量调用以加速入库。
运行时仅嵌入用户查询（单条），开销极低。

质量优化（相对旧版）：
- 分块采用「标题分段 + 滑动窗口 overlap」，避免上下文在块边界被生硬切断；
- 检索先向量召回 top_k 候选，再用交叉编码器重排序（SiliconFlow rerank 端点）
  精排取 top_n，显著降低噪声、提升相关段落命中率；rerank 不可用时自动降级。
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

import chromadb

from src.agent.llm import aembed_texts, arerank, embed_texts
from src.config import settings

CHROMA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "chroma")
COLLECTION = "enterprise_kb"


@dataclass
class Chunk:
    content: str
    source: str
    heading: str


def chunk_markdown(text: str, source: str) -> List[Chunk]:
    """将 markdown 按标题层级分段，段内超长时以滑动窗口切分（带 overlap）。

    设计要点（中文场景）：
    - 以 #~### 标题划分语义段落，heading 作为块元数据便于溯源；
    - 单段长度 <= chunk_size 时整段成块；否则按 step = chunk_size - overlap 滑动，
      相邻窗口共享 overlap 个字符，缓解「一句话被切两半、语义断裂」问题；
    - 超长单行（无换行）直接按 chunk_size 硬切，避免单窗口溢出。
    """
    chunk_size = settings.chunk_size
    overlap = settings.chunk_overlap
    step = max(1, chunk_size - overlap)

    chunks: List[Chunk] = []
    heading = ""
    section_lines: List[str] = []

    def flush_section() -> None:
        nonlocal heading
        if not section_lines:
            return
        body = "\n".join(section_lines).strip()
        section_lines.clear()
        if not body:
            return
        if len(body) <= chunk_size:
            chunks.append(Chunk(content=body, source=source, heading=heading))
            return
        # 滑动窗口：保证每个窗口长度 <= chunk_size，相邻窗口重叠 overlap
        start = 0
        while True:
            window = body[start : start + chunk_size]
            if window.strip():
                chunks.append(Chunk(content=window, source=source, heading=heading))
            if start + chunk_size >= len(body):
                break
            start += step

    for raw in text.splitlines():
        line = raw.rstrip()
        m = re.match(r"^#{1,3}\s+(.*)$", line)
        if m:
            flush_section()
            heading = m.group(1).strip()
            continue
        if not line.strip():
            continue
        # 超长单行强制切分
        if len(line) > chunk_size:
            flush_section()
            for i in range(0, len(line), chunk_size):
                chunks.append(
                    Chunk(content=line[i : i + chunk_size], source=source, heading=heading)
                )
            continue
        section_lines.append(line)
    flush_section()
    return chunks


class ChromaStore:
    """基于 Chroma 的向量存储，封装批量嵌入与检索。"""

    def __init__(self, path: str = CHROMA_PATH, collection: str = COLLECTION) -> None:
        self.client = chromadb.PersistentClient(path=path)
        self.collection = self.client.get_or_create_collection(
            name=collection, metadata={"hnsw:space": "cosine"}
        )

    def count(self) -> int:
        return self.collection.count()

    def reset(self) -> None:
        """清空集合（--force 全量重嵌时使用）。"""
        try:
            self.client.delete_collection(COLLECTION)
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION, metadata={"hnsw:space": "cosine"}
        )

    def add(self, chunks: List[Chunk]) -> None:
        """批量嵌入并写入（按 embed_batch_size 分批，加速入库）。"""
        if not chunks:
            return
        batch = settings.embed_batch_size
        for i in range(0, len(chunks), batch):
            part = chunks[i : i + batch]
            texts = [c.content for c in part]
            embeddings = embed_texts(texts)
            ids = [f"{c.source}#{i + j}" for j, c in enumerate(part)]
            metas = [
                {"source": c.source, "heading": c.heading, "content": c.content}
                for c in part
            ]
            self.collection.add(
                ids=ids, embeddings=embeddings, documents=texts, metadatas=metas
            )

    def query(self, text: str, k: int = 5, score_threshold: float = 0.3) -> List[Dict]:
        """同步检索（向量召回，无重排；供遗留/调试路径使用）。

        分数 = 1 - cosine_distance，越大越相关。
        """
        if self.count() == 0:
            return []
        emb = embed_texts([text])[0]
        res = self.collection.query(
            query_embeddings=[emb], n_results=min(k, self.count())
        )
        out: List[Dict] = []
        docs = res["documents"][0]
        metas = res["metadatas"][0]
        dists = res["distances"][0]
        for doc, meta, dist in zip(docs, metas, dists):
            score = 1.0 - dist
            if score < score_threshold:
                continue
            out.append(
                {
                    "content": doc,
                    "source": meta.get("source", ""),
                    "heading": meta.get("heading", ""),
                    "score": round(score, 4),
                }
            )
        return out

    async def aquery(
        self,
        text: str,
        k: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> List[Dict]:
        """异步检索：向量召回 top_k 候选 -> 重排序精排 top_n。

        流程：
          1. 嵌入 query，Chroma 召回 top_k（settings.rag_top_k）候选；
          2. 向量相似度低于 score_threshold 的噪声先过滤；
          3. 若启用 rerank 且候选 > 1，调用 arerank 按相关性精排，取 top_n
             （settings.rag_rerank_top_n）且 rerank 分数 >= rerank_score_threshold；
             rerank 不可用或仅 1 个候选时，退化为按向量分数取 top_n。

        返回带出处与分数的结果列表（已按相关性降序）。
        """
        if self.count() == 0:
            return []
        k = k or settings.rag_top_k
        score_threshold = (
            score_threshold if score_threshold is not None else settings.rag_score_threshold
        )

        emb = (await aembed_texts([text]))[0]
        res = self.collection.query(
            query_embeddings=[emb], n_results=min(k, self.count())
        )
        docs = res["documents"][0]
        metas = res["metadatas"][0]
        dists = res["distances"][0]

        candidates: List[Dict] = []
        for doc, meta, dist in zip(docs, metas, dists):
            score = 1.0 - dist
            if score < score_threshold:
                continue
            candidates.append(
                {
                    "content": doc,
                    "source": meta.get("source", ""),
                    "heading": meta.get("heading", ""),
                    "score": round(score, 4),
                }
            )
        if not candidates:
            return []

        # 重排序精排
        if settings.enable_rerank and len(candidates) > 1:
            reranked = await arerank(
                text,
                [c["content"] for c in candidates],
                top_n=min(settings.rag_rerank_top_n, len(candidates)),
            )
            passed = [
                {**candidates[r["index"]], "score": round(r["score"], 4)}
                for r in reranked
                if r["score"] >= settings.rerank_score_threshold
            ]
            if passed:
                return passed
            # 全部低于阈值：退化为重排最高的一项，避免「空检索」导致无中生有
            if reranked:
                top = reranked[0]
                return [{**candidates[top["index"]], "score": round(top["score"], 4)}]
            return candidates[: settings.rag_rerank_top_n]

        # 未启用 rerank 或仅 1 个候选：按向量分数取 top_n
        return candidates[: settings.rag_rerank_top_n]


def file_hash(path: str) -> str:
    """计算文件 sha256，用于判断是否需要重新嵌入。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
