"""实时验证取消机制（需先启动 uvicorn 于 8000）。"""
import json
import threading
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def post(path, payload):
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def stream_events(message, session, cancel_after_route=False):
    body = json.dumps({"message": message, "session_id": session}).encode()
    req = urllib.request.Request(f"{BASE}/api/chat", data=body, headers={"Content-Type": "application/json"})
    events = []
    with urllib.request.urlopen(req, timeout=60) as r:
        # 若需中途取消，另起线程在拿到 route 后调用 /api/cancel
        cancelled = {"fired": False}

        def fire_cancel():
            # 等待拿到 route 事件
            while not cancelled["fired"]:
                time.sleep(0.05)
            try:
                post("/api/cancel", {"message": "", "session_id": session})
            except Exception:
                pass

        if cancel_after_route:
            t = threading.Thread(target=fire_cancel, daemon=True)
            t.start()

        for raw in r:
            line = raw.decode("utf-8").rstrip("\n")
            if not line.startswith("data: "):
                continue
            payload = line[6:].strip()
            if payload == "[DONE]":
                break
            ev = json.loads(payload)
            events.append(ev)
            if cancel_after_route and ev.get("type") == "route" and not cancelled["fired"]:
                cancelled["fired"] = True
    return events


if __name__ == "__main__":
    # 1) 取消接口
    r = post("/api/cancel", {"message": "", "session_id": "live-cancel"})
    assert r["status"] == "cancelled", r
    print("CANCEL ENDPOINT OK")

    # 2) 正常对话回归（简单）
    evs = stream_events("你好，你是谁", "live-simple")
    assert any(e["type"] == "route" for e in evs)
    assert any(e["type"] == "token" for e in evs)
    assert any(e["type"] == "done" for e in evs)
    print("SIMPLE CHAT OK (regression)")

    # 3) 中途取消（复杂问题，留出取消窗口）
    evs2 = stream_events("查一下张伟的年假还剩几天，并帮我建个IT工单", "live-complex-cancel", cancel_after_route=True)
    done = [e for e in evs2 if e["type"] == "done"]
    assert done, "未收到 done"
    note = done[0].get("note")
    print(f"COMPLEX CANCEL TEST: done.note = {note!r}")
    print("CANCEL LIVE CHECK DONE (no crash)")
