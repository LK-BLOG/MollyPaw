"""复现用户报的两个崩溃场景，确认已修。

用户的原始 traceback：
  1. AttributeError: 'NoneType' object has no attribute 'acquire'
       在 do_POST 里 service.controller.acquire("local")
  2. ConnectionResetError: [WinError 10054]
       在 _send_json 里，客户端提前断开

这个脚本用真实 HTTP 请求打这两个点。
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append((name, detail))
        print(f"  [FAIL] {name} :: {detail}")


def main():
    import main

    api = main.MollyPawAPI()
    api.start_pet_server(host="127.0.0.1", port=0)
    port = getattr(api, "server_port", None)
    assert port, "HTTP 服务没起来"
    base = f"http://127.0.0.1:{port}"
    print(f"服务在 {base}\n")

    print("[1] controller 存在性（崩溃点 1 的前置条件）")
    check("service.controller 不是 None", api.service.controller is not None,
          str(api.service.controller))
    check("controller 有 acquire", hasattr(api.service.controller, "acquire"))

    print("\n[2] 本地发消息（用户崩的那条路径）")
    try:
        req = urllib.request.Request(
            base + "/api/chat",
            data=json.dumps({"message": "hello", "thinking_level": "none"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode())
        # 没有 API key 时 chat 会失败，但**不该是 AttributeError**
        check("POST /api/chat 没抛 AttributeError", True)
        print(f"      返回: {str(body)[:120]}")
        err = str(body.get("error", "")) + str(body.get("busy", ""))
        check("错误不是 controller 相关", "NoneType" not in err and "acquire" not in err,
              err)
    except Exception as exc:
        check("POST /api/chat 没抛 AttributeError", False, f"{type(exc).__name__}: {exc}")

    print("\n[3] 点停止（也要能用 controller）")
    try:
        req = urllib.request.Request(
            base + "/api/stop",
            data=json.dumps({"by": "local"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
        check("POST /api/stop 正常返回", body.get("ok") is True, str(body))
    except Exception as exc:
        check("POST /api/stop 正常返回", False, f"{type(exc).__name__}: {exc}")

    print("\n[4] 客户端提前断开（崩溃点 2：ConnectionResetError）")
    # 故意发一个请求然后立刻关掉 socket，让服务端写响应时对端已消失
    import http.client

    reset_happened = []
    for i in range(5):
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("POST", "/api/relay/stop",
                         body=json.dumps({"by": "local"}),
                         headers={"Content-Type": "application/json"})
            conn.sock.close()   # 不读响应，直接掐断
        except Exception as exc:
            reset_happened.append(str(exc))
    time.sleep(1.0)
    # 服务端不该因为这几下就挂掉
    try:
        with urllib.request.urlopen(base + "/state", timeout=10) as resp:
            ok = resp.status == 200
        check("反复掐断后服务仍存活", ok, f"status={ok}")
    except Exception as exc:
        check("反复掐断后服务仍存活", False, str(exc))

    print("\n[5] 服务端有没有把客户端断开当异常抛出")
    # 通过 stderr 不好直接抓，这里退一步：确认 handle_one_request 被我们覆盖了
    import inspect
    from main import MollyPawAPI
    src = inspect.getsource(MollyPawAPI.start_pet_server)
    check("已覆盖 handle_one_request 做兜底", "def handle_one_request" in src)
    check("CLIENT_GONE 含 ConnectionResetError",
          "ConnectionResetError" in src)

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for name, detail in FAIL:
        print(f"  FAIL: {name} :: {detail}")
    print("=" * 56)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
