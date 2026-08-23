"""QQ 机器人接入客户端（官方平台 bot.q.qq.com）。

封装官方开放平台的鉴权与 WebSocket 网关协议，将收到的消息转发给现有 Agent 流水线
（src.agent.agent.arun，RAG + 工具调用零改动），并把答复通过 OpenAPI 回传。

协议要点（v2）：
- 凭证：AppID + AppSecret -> POST /app/getAppAccessToken 换 access_token（7200s 有效）
- 网关：GET /gateway 拿到 wss 地址，发送 Op 2 Identify（token="QQBot {token}"）鉴权上线
- 心跳：Op 10 Hello 给出周期，定时发 Op 1；断线 Op 7 重连
- 事件：Op 0 Dispatch，t 为事件名（GROUP_AT_MESSAGE_CREATE / C2C_MESSAGE_CREATE）
- 回包：POST /v2/groups/{group_openid}/messages 或 /v2/users/{openid}/messages
        Header: Authorization: QQBot {token}, X-Union-Appid: {appid}
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, Optional

import httpx
import websockets

from src.agent.agent import arun as agent_arun
from src.config import settings

OPENAPI_BASE = "https://api.bot.qq.com"
# 默认订阅：群@消息 + 单聊消息（v2 同一位 1<<25）
DEFAULT_INTENTS = 1 << 25


class QQBotError(RuntimeError):
    """QQ 机器人接入相关错误。"""


def clean_content(text: str) -> str:
    """去除群消息中的 @机器人 提及标记（<@!xxx> / <@xxx>）。"""
    return re.sub(r"<@!?[^>]+>", "", text or "").strip()


class QQBot:
    """官方 QQ 机器人客户端：鉴权 + 网关事件循环 + 转发 Agent + 回包。"""

    def __init__(
        self,
        appid: str,
        secret: str,
        intents: Optional[int] = None,
        openapi_base: str = OPENAPI_BASE,
    ) -> None:
        if not appid or not secret:
            raise QQBotError("缺少 QQ_BOT_APPID / QQ_BOT_SECRET")
        self.appid = appid
        self.secret = secret
        self.intents = intents if intents is not None else settings.qq_bot_intents or DEFAULT_INTENTS
        self.openapi_base = openapi_base
        self.access_token: Optional[str] = None
        self.ws: Any = None
        self.heartbeat_interval = 30.0
        self._seq: Optional[int] = None
        self._session_id: Optional[str] = None

    # ---------- 鉴权 ----------
    async def get_token(self) -> str:
        """用 AppSecret 换取 access_token（即「授权」）。"""
        async with httpx.AsyncClient(base_url=self.openapi_base, timeout=10) as client:
            resp = await client.post(
                "/app/getAppAccessToken",
                json={"appId": self.appid, "clientSecret": self.secret},
            )
            resp.raise_for_status()
            self.access_token = resp.json()["access_token"]
        return self.access_token

    async def _gateway_url(self) -> str:
        # v2 网关接口需带鉴权头，否则返回 401
        headers = {"Authorization": f"QQBot {self.access_token}"}
        async with httpx.AsyncClient(base_url=self.openapi_base, timeout=10) as client:
            resp = await client.get("/gateway", headers=headers)
            resp.raise_for_status()
            return resp.json()["url"]

    # ---------- 回包 ----------
    async def send_reply(self, event: Dict[str, Any], text: str) -> None:
        """根据事件类型回消息（群@ / 单聊）。"""
        if self.access_token is None:
            raise QQBotError("未鉴权，无法发送消息")
        headers = {
            "Authorization": f"QQBot {self.access_token}",
            "X-Union-Appid": self.appid,
            "Content-Type": "application/json",
        }
        # 超长截断（v2 单条有长度限制，必要时可后续分片）
        content = text[:5000]
        body = {"msg_type": 0, "content": content}
        d = event["d"]
        if event.get("t") == "GROUP_AT_MESSAGE_CREATE":
            url = f"/v2/groups/{d['group_openid']}/messages"
        elif event.get("t") == "C2C_MESSAGE_CREATE":
            url = f"/v2/users/{d['author']['user_openid']}/messages"
        else:
            return
        async with httpx.AsyncClient(base_url=self.openapi_base, timeout=10) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()

    # ---------- Agent 转发 ----------
    async def _agent_reply(self, user_text: str, session_id: str) -> str:
        """调用现有 Agent 流水线（异步），汇聚 token 事件为最终文本。"""
        parts: list[str] = []
        async for ev in agent_arun(user_text, session_id):
            if ev.get("type") == "token":
                parts.append(ev.get("content", ""))
        return "".join(parts).strip() or "（暂无回复）"

    async def _handle(self, event: Dict[str, Any]) -> None:
        """处理一条消息事件：记录日志 -> 调 Agent -> 回包；单条失败不拖垮连接。"""
        try:
            d = event["d"]
            user_text = clean_content(d.get("content", ""))
            openid = d.get("author", {}).get("user_openid") or d.get("group_openid", "")
            print(f"[MSG] {event.get('t')} from {openid}: {user_text[:80]}")
            if not user_text:
                return
            reply = await self._agent_reply(user_text, f"qq-{openid}")
            await self.send_reply(event, reply)
            print(f"[REPLY] -> {openid}: {reply[:80]}")
        except Exception as exc:  # 单条消息异常应被隔离，避免整个 ws 循环崩溃
            print(f"[ERROR] 处理消息失败: {exc!r}")
            try:
                await self.send_reply(event, "（处理失败，请稍后重试或联系管理员）")
            except Exception:
                pass

    # ---------- 网关协议 ----------
    async def _identify(self) -> None:
        await self.ws.send(
            json.dumps(
                {
                    "op": 2,
                    "d": {
                        "token": f"QQBot {self.access_token}",
                        "intents": self.intents,
                        "shard": [0, 1],
                        "properties": {
                            "$os": "win32",
                            "$browser": "rag-agent",
                            "$device": "rag-agent",
                        },
                    },
                }
            )
        )

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            await self.ws.send(json.dumps({"op": 1, "d": self._seq}))

    async def _connect_once(self) -> None:
        """建立一次网关连接并监听，直到断线/重连指令/取消。"""
        await self.get_token()
        url = await self._gateway_url()
        hb_task: Optional[asyncio.Task] = None
        try:
            async with websockets.connect(url) as ws:
                self.ws = ws
                async for raw in ws:
                    msg = json.loads(raw)
                    op = msg.get("op")
                    if op == 10:  # Hello
                        self.heartbeat_interval = msg["d"]["heartbeat_interval"] / 1000.0
                        await self._identify()
                        hb_task = asyncio.create_task(self._heartbeat())
                    elif op == 0:  # Dispatch
                        self._seq = msg.get("s")
                        if msg.get("t") == "READY":
                            self._session_id = msg["d"]["session_id"]
                            print("[OK] QQ 机器人已上线，开始监听消息……")
                        else:
                            try:
                                await self._handle(msg)
                            except Exception as exc:
                                print(f"[ERROR] dispatch 处理异常: {exc!r}")
                    elif op == 7:  # Reconnect：服务端要求重连，外层循环会重连
                        print("[RECONNECT] 收到服务端重连指令，准备重连……")
                        break
                    elif op == 9:  # Invalid Session
                        print("[WARN] 收到 Invalid Session，请检查 intents/凭证，准备重连。")
                        break
                    elif op == 11:  # Heartbeat ack
                        pass
        finally:
            if hb_task is not None:
                hb_task.cancel()

    async def run(self) -> None:
        """连接网关并持续监听；遇到断线/重连指令自动重连（指数退避）。"""
        backoff = 1
        while True:
            try:
                await self._connect_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[ERROR] 连接异常: {exc!r}")
            print(f"[RECONNECT] {backoff}s 后重连……")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
