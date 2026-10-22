"""诊断：第二条连接（auth.req）为什么超时。

对比两条路径：
  A. 首次配对（pair.req）—— 能成功
  B. 用 token 认证（auth.req）—— 超时

重点看：PC 端到底有没有收到 auth.req、有没有回响应。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "MollyPaw-Relay"))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from relay.dev_server import DevRelay
from agent.relay import crypto as C
from agent.relay.devices import DeviceStore
from agent.relay.manager import RelayManager
from agent.service import MollyPawService
from tools.mp_phone import PhoneClient

PSK = "MollyPawDiag1234"
PORT = 18995


def main():
    relay = DevRelay("127.0.0.1", PORT)
    relay.start_background()

    tmp = tempfile.mkdtemp(prefix="diag-auth-")
    service = MollyPawService()
    mgr = RelayManager(service, config={"url": f"ws://127.0.0.1:{PORT}/server", "psk": PSK},
                       logger=lambda m: print(f"[relay] {m}"))
    mgr.devices = DeviceStore(path=os.path.join(tmp, "devices.json"))
    mgr.bridge.devices = mgr.devices
    mgr.bridge.logger = lambda m: print(f"[bridge] {m}")

    # 包一层，看 PC 端收到什么
    orig = mgr._on_payload
    def traced(method, params, msg_id, sender_role, sender_dev=None):
        print(f"[PC <- ] method={method!r} role={sender_role!r} dev={sender_dev!r} id={str(msg_id)[:12]}")
        return orig(method, params, msg_id, sender_role, sender_dev)
    mgr._on_payload = traced

    mgr.start()
    for _ in range(100):
        if mgr.status()["connected"]:
            break
        time.sleep(0.05)
    print(f"PC 已连接 room={mgr.room()}\n")

    # --- A. 配对 ---
    print("=" * 50)
    print("A. 首次配对")
    print("=" * 50)
    session = mgr.new_pairing("app")
    phone1 = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="测试机")
    ok, res = phone1.pair(session["code"])
    print(f"配对结果: ok={ok} res={res}")
    token = res.get("token") if ok else None
    dev_id = phone1.dev_id
    phone1.close()
    time.sleep(1)

    # --- B. auth ---
    print("\n" + "=" * 50)
    print("B. 用 token 认证（新连接）")
    print("=" * 50)
    room = C.derive_room(PSK)
    phone2 = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_id=dev_id, dev_name="测试机")
    phone2.connect(room)
    print(f"phone2 握手完成: key={'有' if phone2.key else '无'}  peer_eph={'有' if phone2.peer_eph else '无'}")
    ok, res2 = phone2.auth(token, timeout=8)
    print(f"认证结果: ok={ok} res={res2}")
    print(f"phone2 收到的事件: {phone2.drain()}")
    print(f"phone2 错误: {phone2.errors}")

    # PC 端侧：看会话登记
    print(f"\n[PC] 已登记会话: {list(mgr.bridge._sessions.keys())}")
    phone2.close()
    mgr.stop()
    relay.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
