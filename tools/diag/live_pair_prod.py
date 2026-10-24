"""真实生产环境配对链路诊断（打官方中继，不用本地 dev server）。

流程完全对齐真机：
  PC 端 RelayManager -> wss://mollypaw-online.pages.dev/server
  手机端 PhoneClient   -> 同一个 URL
  配对码 = MP1.<b64(pair_seed)>.<room>

用法：
    python tools/diag/live_pair_prod.py                  # 自动探测代理
    python tools/diag/live_pair_prod.py --proxy direct   # 纯直连（验证无代理用户）
"""
import argparse
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

PROD_URL = "wss://mollypaw-online.pages.dev/server"


def wait_until(pred, timeout=15, interval=0.1):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(interval)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=PROD_URL)
    ap.add_argument("--proxy", default="auto", help="auto=探测系统代理 / direct=纯直连")
    ap.add_argument("--keep", action="store_true", help="不删临时目录")
    args = ap.parse_args()

    from agent.relay import crypto as C
    from agent.relay.devices import DeviceStore
    from agent.relay.manager import RelayManager
    import mp_phone

    psk = "MollyPawLiveDiag" + str(int(time.time()))[-6:] + "Xy"
    print(f"[1] url={args.url}  proxy={args.proxy}")
    print(f"    psk={psk} (len={len(psk)})  room={C.derive_room(psk)}")

    class FakeService:
        """够 RelayManager 用的最小替身，不碰 LLM。"""

        def __init__(self):
            self.controller = None

    svc = FakeService()

    tmpdir = tempfile.mkdtemp(prefix="mp-live-")
    mgr = RelayManager(
        svc,
        config={"url": args.url, "psk": psk, "proxy": args.proxy},
        logger=lambda m: print("    [pc]", m),
    )
    mgr.devices = DeviceStore(path=os.path.join(tmpdir, "devices.json"))
    mgr.bridge.devices = mgr.devices

    print("[2] PC 端启动中继…")
    t0 = time.time()
    st = mgr.start()
    print(f"    start() -> state={st.get('state')}")

    ok = wait_until(lambda: mgr.status().get("connected"), timeout=40)
    print(f"[3] connected={ok} ({time.time()-t0:.1f}s) "
          f"proxy_active={mgr.status().get('proxy_active')!r}")
    if not ok:
        print(json.dumps(mgr.status(), ensure_ascii=False, indent=1))
        mgr.stop()
        return 2

    print("[4] 生成配对码（等价于 UI 点「添加设备」）")
    pin = mgr.new_pairing(role="app")
    if not pin.get("ok"):
        print(f"!!! 配对码生成失败：{pin}")
        mgr.stop()
        return 3
    code = pin["code"]
    print(f"    code={code}  (len={len(code)})")

    print("[5] 手机端连接中继")
    room = C.derive_room(psk)
    phone = mp_phone.PhoneClient(
        url=args.url,
        psk="",                      # 手机配对前不知道主 PSK
        dev_id="diag-phone",
        dev_name="诊断手机",
        role="app",
    )
    phone.proxy_mode = args.proxy
    t0 = time.time()
    phone.connect(room, timeout=20)
    print(f"    WS 建立 {time.time()-t0:.1f}s  key_ready={phone.wait_key(timeout=15)}")

    print("[6] 手机发 pair.req")
    t0 = time.time()
    try:
        res = phone.pair_and_reconnect(code, timeout=30)
    except Exception as exc:
        print(f"!!! pair_and_reconnect 抛异常：{type(exc).__name__}: {exc}")
        res = None
    print(f"    pair_and_reconnect -> {json.dumps(res, ensure_ascii=False) if res else None}"
          f"  ({time.time()-t0:.1f}s)")

    if not res:
        print("!!! 配对失败 —— 这就是手机端「没收到响应」的来源")
        print(f"    PC 端 status={json.dumps(mgr.status(), ensure_ascii=False)}")
        mgr.stop()
        phone.close()
        return 4

    print("[7] 配对成功，用主 PSK 通道发 server.ping")
    ok2, r = phone.call("server.ping", {}, timeout=20)
    print(f"    server.ping ok={ok2} r={json.dumps(r, ensure_ascii=False) if r else r}")

    phone.close()
    mgr.stop()
    if not args.keep:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    print("[done] 全链路 OK" if ok2 else "[done] 配对成功但业务调用失败")
    return 0 if ok2 else 5


if __name__ == "__main__":
    sys.exit(main())
