"""QQ 机器人一键接入脚本（官方平台 bot.q.qq.com）。

流程：
  1) 无凭证时自动打开官方机器人管理页链接，引导你创建/获取 AppID 与 AppSecret；
  2) 将凭证写入 .env（QQ_BOT_APPID / QQ_BOT_SECRET）；
  3) 用 AppSecret 换取 AccessToken（即「授权」）；
  4) 连接官方 WSS 网关鉴权上线（即「把机器人跑起来」）；
  5) 监听群@消息 / 单聊消息，转发给现有 Agent 流水线（RAG + 工具），回传答复。

依赖：websockets（已在 requirements.txt）；httpx 已有。
运行：PYTHONPATH=. python scripts/connect_qqbot.py
"""
from __future__ import annotations

import os
import webbrowser
from typing import Dict

from src.config import settings
from src.qqbot.client import QQBot, QQBotError

BOT_MANAGE_URL = "https://bot.q.qq.com/"


def _write_env(updates: Dict[str, str]) -> None:
    """把新增/更新的配置写回 .env（保留其它配置）。"""
    path = ".env"
    lines = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
    idx = {ln.split("=")[0].strip(): i for i, ln in enumerate(lines) if "=" in ln}
    for key, val in updates.items():
        if key in idx:
            lines[idx[key]] = f"{key}={val}"
        else:
            lines.append(f"{key}={val}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def ensure_credentials() -> None:
    """无凭证时引导用户在官网创建机器人并填写 AppID/AppSecret。"""
    if settings.qq_bot_appid and settings.qq_bot_secret:
        return
    print("未检测到 QQ 机器人凭证，正在打开官方机器人管理页……")
    print(f"请创建/选择机器人并复制 AppID 与 AppSecret：{BOT_MANAGE_URL}")
    webbrowser.open(BOT_MANAGE_URL)  # 点链接即打开管理页（Windows 下默认浏览器）
    appid = input("QQ_BOT_APPID: ").strip()
    secret = input("QQ_BOT_SECRET: ").strip()
    if not appid or not secret:
        raise SystemExit("已取消：缺少凭证，无法启动机器人。")
    _write_env({"QQ_BOT_APPID": appid, "QQ_BOT_SECRET": secret})
    # 注入本次运行环境，避免重新加载模块
    os.environ["QQ_BOT_APPID"] = appid
    os.environ["QQ_BOT_SECRET"] = secret


def main() -> None:
    ensure_credentials()
    appid = os.getenv("QQ_BOT_APPID") or settings.qq_bot_appid
    secret = os.getenv("QQ_BOT_SECRET") or settings.qq_bot_secret
    intents = settings.qq_bot_intents
    try:
        import asyncio

        asyncio.run(QQBot(appid, secret, intents).run())
    except QQBotError as e:
        raise SystemExit(f"QQ 机器人启动失败：{e}")
    except KeyboardInterrupt:
        print("\n已停止机器人。")


if __name__ == "__main__":
    main()
