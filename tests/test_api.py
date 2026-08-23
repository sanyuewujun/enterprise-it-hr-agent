"""API 层测试：健康检查、工具清单（无需联网）；对话接口（需联网，轻量）。"""
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["chat_model"]
    assert data["small_model"]


def test_tools_endpoint():
    r = client.get("/api/tools")
    assert r.status_code == 200
    assert len(r.json()["tools"]) == 6


def test_chat_simple_route():
    # 简单问候走小模型直答，验证 SSE 能产出 token 与 done
    seen_token = False
    seen_done = False
    with client.stream("POST", "/api/chat", json={"message": "你好", "session_id": "test-api"}) as resp:
        for line in resp.iter_lines():
            if line and line.startswith("data: "):
                payload = line[6:]
                if payload == "[DONE]":
                    seen_done = True
                    break
                import json

                ev = json.loads(payload)
                if ev.get("type") == "token":
                    seen_token = True
                if ev.get("type") == "done":
                    seen_done = True
    assert seen_token
    assert seen_done
