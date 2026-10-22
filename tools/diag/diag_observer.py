"""诊断：observer 的请求为什么超时。

现象：observer 配对成功，但后续 config.save 拿不到响应（超时）。
而 app 角色的同类请求正常。

怀疑点：PC 端按「角色」挑密钥，observer 的 hello 与后续帧
在 _peers 里的记录是否对得上。
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

PSK = "MollyPawObsDiag12"
PORT = 18998


def main():
    relay = DevRelay("127.0.0.1", PORT)
    relay.start_background()

    tmp = tempfile.mkdtemp(prefix="diag-obs-")
    service = MollyPawService()
    mgr = RelayManager(service, config={"url": f"ws://127.0.0.1:{PORT}/server", "psk": PSK})
    mgr.devices = DeviceStore(path=os.path.join(tmp, "devices.json"))
    mgr.bridge.devices = mgr.devices

    orig = mgr._on_payload
    def traced(method, params, msg_id, sender_role, sender_peer=None):
        print(f"[PC <- ] {method!r} role={sender_role!r} peer={sender_peer!r}")
        return orig(method, params, msg_id, sender_role, sender_peer)
    mgr._on_payload = traced

    mgr.start()
    for _ in range(100):
        if mgr.status()["connected"]:
            break
        time.sleep(0.05)

    session = mgr.new_pairing("observer")
    phone = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="只读端")
    ok, res = phone.pair(session["code"])
    print(f"配对: ok={ok} role={res.get('role') if ok else res}")
    time.sleep(0.6)

    print(f"\n[PC] _peers = {list(mgr.link._peers.keys())}")
    for pid, p in mgr.link._peers.items():
        print(f"    {pid}: role={p.get('role')} key={'有' if p.get('key') else '无'}")

    print(f"\n[PC] 已登记会话 = {list(mgr.bridge._sessions.keys())}")
    for sid, s in mgr.bridge._sessions.items():
        print(f"    {sid}: role={s.get('role')}")

    print("\n--- 发 config.save（observer 应被拒 forbidden）---")
    ok, err = phone.call("config.save", {"max_tokens": 999}, timeout=8)
    print(f"结果: ok={ok} err={err}")
    print(f"phone 收到: {phone.drain()}")
    print(f"phone 错误: {phone.errors}")

    print("\n--- 发 conv.list（observer 允许）---")
    ok, res2 = phone.call("conv.list", timeout=8)
    print(f"结果: ok={ok} res={str(res2)[:100]}")

    phone.close()
    mgr.stop()
    relay.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
