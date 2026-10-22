"""诊断：CLI 配对成功后，业务请求为什么超时。

配对成功（test_pairing_succeeds_with_code_only 通过），
但紧接着的 status.get 超时。对比"配对那一次"和"后续请求"的差异。
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
from agent.relay.devices import DeviceStore
from agent.relay.manager import RelayManager
from agent.service import MollyPawService
from tools.mp_phone import PhoneClient

PSK = "MollyPawCliDiag99"
PORT = 19003


def main():
    relay = DevRelay("127.0.0.1", PORT)
    relay.start_background()

    tmp = tempfile.mkdtemp(prefix="diag-cli-")
    service = MollyPawService()
    mgr = RelayManager(service, config={"url": f"ws://127.0.0.1:{PORT}/server", "psk": PSK},
                       logger=lambda m: print(f"[relay] {m}"))
    mgr.devices = DeviceStore(path=os.path.join(tmp, "devices.json"))
    mgr.bridge.devices = mgr.devices

    orig = mgr._on_payload
    def traced(method, params, msg_id, sender_role, sender_peer=None):
        print(f"[PC <-] {method!r} role={sender_role!r} peer={sender_peer!r}")
        return orig(method, params, msg_id, sender_role, sender_peer)
    mgr._on_payload = traced

    mgr.start()
    for _ in range(100):
        if mgr.status()["connected"]:
            break
        time.sleep(0.05)
    print(f"PC 已连接: {mgr.status()['state']}\n")

    session = mgr.new_pairing("app")
    phone = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="诊断手机")
    # 必须用 pair_and_reconnect：配对成功后服务端作废配对密钥，
    # 要用下发的主 PSK 重连，后续请求才解得开。
    ok, res = phone.pair_and_reconnect(session["code"])
    print(f"配对: ok={ok} role={res.get('role') if ok else res}")
    print(f"  服务端下发主 PSK 了吗: {'是' if res.get('psk') else '否'}")
    time.sleep(0.5)

    print(f"\n[PC] bridge 会话表:")
    for sid, s in mgr.bridge._sessions.items():
        print(f"    {sid}: role={s.get('role')} dev={s.get('dev_id')}")
    print(f"[PC] peer 列表:")
    with mgr.link._peers_lock:
        for pid, p in mgr.link._peers.items():
            print(f"    {pid}: role={p.get('role')} key={'有' if p.get('key') else '无'}")

    print("\n--- 发 status.get ---")
    ok2, res2 = phone.call("status.get", timeout=10)
    print(f"结果: ok={ok2} res={str(res2)[:120]}")
    print(f"收到的事件: {[n for n, _ in phone.drain()]}")

    print("\n--- 检查手机端所声称的角色 ---")
    print(f"phone.role (连接声明) = {phone.role}")
    print(f"phone.granted_role    = {phone.granted_role}")

    phone.close()
    mgr.stop()
    relay.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
