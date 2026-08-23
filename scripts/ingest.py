"""知识库入库脚本：扫描 docs/*.md，按文件哈希增量嵌入；--force 全量重嵌。

用法：
    python scripts/ingest.py            # 仅嵌入新增/变更文档
    python scripts/ingest.py --force    # 清空后全量重嵌
"""
from __future__ import annotations

import argparse
import json
import os

from src.agent.rag import ChromaStore, chunk_markdown, file_hash
from src.config import settings

DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "data", "docs")
HASH_FILE = os.path.join(os.path.dirname(__file__), "..", "src", "data", "chroma", ".ingested.json")


def _load_hashes() -> dict:
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_hashes(hashes: dict) -> None:
    os.makedirs(os.path.dirname(HASH_FILE), exist_ok=True)
    with open(HASH_FILE, "w", encoding="utf-8") as f:
        json.dump(hashes, f, ensure_ascii=False, indent=2)


def run(force: bool = False) -> dict:
    """执行入库，返回统计信息（供 CLI 与 API 复用）。"""
    store = ChromaStore()
    if force:
        print("强制模式：清空集合...")
        store.reset()
        hashes: dict = {}
    else:
        hashes = _load_hashes()

    files = sorted(f for f in os.listdir(DOCS_DIR) if f.endswith(".md"))
    changed = 0
    for fname in files:
        path = os.path.join(DOCS_DIR, fname)
        h = file_hash(path)
        if not force and hashes.get(fname) == h:
            print(f"跳过（未变更）: {fname}")
            continue
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        chunks = chunk_markdown(text, source=fname)
        store.add(chunks)
        hashes[fname] = h
        changed += 1
        print(f"已嵌入: {fname} ({len(chunks)} 块)")

    _save_hashes(hashes)
    summary = {"changed": changed, "total": store.count()}
    print(f"\n完成：新增/变更 {changed} 篇，集合当前共 {store.count()} 块。")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="清空后全量重嵌")
    args = parser.parse_args()
    run(force=args.force)


if __name__ == "__main__":
    main()
