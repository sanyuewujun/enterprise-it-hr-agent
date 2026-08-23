"""集中配置：所有密钥/模型名/参数均从 .env 读取，代码零硬编码。"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，自动从 .env 加载（.env 优先于环境变量）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # SiliconFlow
    siliconflow_api_key: str = ""
    llm_base_url: str = "https://api.siliconflow.cn/v1"

    # 模型（不写死，可随时替换）
    chat_model: str = "deepseek-ai/DeepSeek-V3"
    small_model: str = "Qwen/Qwen2.5-7B-Instruct"
    embed_model: str = "BAAI/bge-m3"

    # 路由与嵌入
    enable_intent_routing: bool = True
    embed_batch_size: int = 16

    # RAG 分块与检索（中文场景优化）
    chunk_size: int = 500          # 单块最大字符数
    chunk_overlap: int = 80        # 相邻块重叠字符数，避免上下文在边界被切断
    rag_top_k: int = 8             # 向量召回候选数（rerank 前）
    rag_rerank_top_n: int = 3      # 重排序后保留数
    rag_score_threshold: float = 0.25  # 向量相似度阈值（召回阶段过滤噪声）

    # 重排序（硅基流动 rerank 端点，带降级）
    enable_rerank: bool = True
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_score_threshold: float = 0.1  # 重排分数阈值（过滤不相关候选）

    # 提示词注入防护：规则拦截 + 小模型分类兜底（每次请求多一次小模型调用）
    enable_injection_llm_guard: bool = True

    # 模型调用超时（秒）：防止小模型/主模型调用挂起导致整个对话卡死
    llm_timeout: int = 30

    # 服务
    api_key: str = ""
    cors_origins: str = "*"

    # QQ 机器人（官方平台 bot.q.qq.com，WebSocket 网关接入）
    # 在平台创建机器人后获得 AppID / AppSecret；脚本首次运行会自动打开管理页引导填写
    qq_bot_appid: str = ""
    qq_bot_secret: str = ""
    # 事件订阅 intents 位掩码；默认 1<<25 = 群@消息 + 单聊消息
    qq_bot_intents: int = 1 << 25

    @property
    def cors_origin_list(self) -> List[str]:
        """将逗号分隔的 CORS_ORIGINS 解析为列表。"""
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """返回单例配置。"""
    return Settings()


# 全局单例，供各模块直接 import 使用
settings = get_settings()
