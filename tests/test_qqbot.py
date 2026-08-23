"""QQ 机器人模块测试（不依赖真实网关/网络）。"""
from __future__ import annotations

import os

from src.qqbot.client import DEFAULT_INTENTS, QQBot, QQBotError, clean_content


def test_clean_content_strips_mention() -> None:
    assert clean_content("<@!12345> 你好") == "你好"
    assert clean_content("<@abc>查张伟的年假") == "查张伟的年假"
    assert clean_content("  仅空白  ") == "仅空白"


def test_default_intents_is_group_and_c2c() -> None:
    # 1<<25 覆盖群@消息与单聊消息
    assert DEFAULT_INTENTS == 1 << 25


def test_qqbot_requires_credentials(monkeypatch) -> None:
    """缺少 AppID/Secret 时构造即抛 QQBotError。"""
    monkeypatch.setattr(os.environ, "pop", lambda k, d="": d)  # 确保环境变量被清空
    monkeypatch.delenv("QQ_BOT_APPID", raising=False)
    monkeypatch.delenv("QQ_BOT_SECRET", raising=False)
    from src.config import get_settings

    get_settings.cache_clear()
    try:
        raised = False
        try:
            QQBot("", "")
        except QQBotError:
            raised = True
        assert raised
    finally:
        get_settings.cache_clear()
