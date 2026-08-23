"""对真实运行的 uvicorn 服务做端到端验证（生产路径）。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"


def test_health():
    with urllib.request.urlopen(f"{BASE}/api/health", timeout=10) as r:
        data = json.loads(r.read())
    assert data["status"] == "ok"
    print("HEALTH OK:", data["chat_model"], data["small_model"])


def test_static():
    with urllib.request.urlopen(f"{BASE}/", timeout=10) as r:
        html = r.read().decode("utf-8")
    assert '<div id="root">' in html
    print("STATIC OK: index.html served")


def test_chat_sse():
    body = json.dumps({"message": "你好，你是谁", "session_id": "live"}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/chat", data=body, headers={"Content-Type": "application/json"}
    )
    seen_route = seen_token = seen_done = False
    with urllib.request.urlopen(req, timeout=60) as r:
        for raw in r:
            line = raw.decode("utf-8").rstrip("\n")
            if not line.startswith("data: "):
                continue
            payload = line[6:].strip()
            if payload == "[DONE]":
                seen_done = True
                break
            ev = json.loads(payload)
            if ev.get("type") == "route":
                seen_route = True
            if ev.get("type") == "token":
                seen_token = True
            if ev.get("type") == "done":
                seen_done = True
    assert seen_route and seen_token and seen_done
    print("CHAT SSE OK: route+token+done received")


if __name__ == "__main__":
    test_health()
    test_static()
    test_chat_sse()
    print("ALL LIVE CHECKS PASSED")
