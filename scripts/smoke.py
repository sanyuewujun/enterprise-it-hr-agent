"""三路冒烟测试：主模型 / 小模型 / 嵌入，验证 SiliconFlow 接入可用。"""
from __future__ import annotations

from src.agent.llm import chat, embed_texts
from src.config import settings


def main() -> None:
    print("=== 1) 主模型对话 ===")
    r1 = chat(
        [{"role": "user", "content": "用一句话介绍你自己。"}],
        model=settings.chat_model,
        stream=False,
    )
    print(f"[{settings.chat_model}] -> {r1.choices[0].message.content}\n")

    print("=== 2) 小模型对话（不思考）===")
    r2 = chat(
        [{"role": "user", "content": "你好，你是谁？"}],
        model=settings.small_model,
        stream=False,
        temperature=0.3,
    )
    print(f"[{settings.small_model}] -> {r2.choices[0].message.content}\n")

    print("=== 3) 嵌入维度 ===")
    vecs = embed_texts(["测试嵌入向量", "企业年假制度"])
    print(f"[{settings.embed_model}] 条数={len(vecs)} 维度={len(vecs[0])}\n")

    print("ALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
