"""诊断：配对密钥派生链为什么断了。

配对码改用 pair_key 之后，情形 1 仍超时。逐环节查：
  1. PC 端有没有收到手机的 hello（拿到 eph/hs）
  2. _on_new_peer 有没有被调用
  3. derive_for_pairing 有没有真的派生出密钥
  4. 手机发来的 pair.req 能不能被解开
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

PSK = "MollyPawChain1234"
PORT = 19001


def main():
    relay = DevRelay("127.0.0.1", PORT)
    relay.start_background()

    tmp = tempfile.mkdtemp(prefix="diag-chain-")
    service = MollyPawService()
    mgr = RelayManager(service, config={"url": f"ws://127.0.0.1:{PORT}/server", "psk": PSK},
                       logger=lambda m: print(f"[relay] {m}"))
    mgr.devices = DeviceStore(path=os.path.join(tmp, "devices.json"))
    mgr.bridge.devices = mgr.devices

    # 包一层看关键事件
    orig_new_peer = mgr._on_new_peer
    def traced_new_peer(peer_id):
        print(f"[PC] _on_new_peer peer={peer_id}")
        session = mgr.devices.current_pairing()
        print(f"[PC]   当前待认领配对码: {'有' if session else '无'}")
        r = orig_new_peer(peer_id)
        link = mgr.link
        if link:
            with link._peers_lock:
                print(f"[PC]   _peers={list(link._peers.keys())} "
                      f"_pairing_keys={list(link._pairing_keys.keys())}")
        return r
    mgr._on_new_peer = traced_new_peer

    mgr.start()
    for _ in range(100):
        if mgr.status()["connected"]:
            break
        time.sleep(0.05)
    print(f"PC 连接 OK, room={mgr.room()}\n")

    session = mgr.new_pairing("app")
    code = session["code"]
    pair_seed, room = C.parse_pairing_code(code)
    print(f"配对码已生成；pair_key={C.b64e(pair_key)[:16]}…")
    # manager.new_pairing 返回的是给 UI 用的 dict，内部对象要从 devices 取
    inner = mgr.devices.current_pairing()
    print(f"内部 session 存在？ {inner is not None}")
    if inner:
        print(f"session.pair_key 与码里一致？ {C.b64e(inner.pair_key) == C.b64e(pair_key)}\n")

    print("--- 手机开始配对 ---")
    phone = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="扫码手机")
    ok, res = phone.pair(code, timeout=12)
    print(f"\n配对结果: ok={ok} res={res}")

    link = mgr.link
    if link:
        print(f"\n[PC] 最终 _peers:")
        with link._peers_lock:
            for pid, p in link._peers.items():
                print(f"    {pid}: role={p.get('role')} key={'有' if p.get('key') else '无'}")
            print(f"[PC] _pairing_keys = {list(link._pairing_keys.keys())}")
        print(f"[PC] session_key = {'有' if link.session_key else '无'}")

    if not ok:
        print("\n--- 手机会话密钥是否与 PC 一致 ---")
        print(f"手机 key = {C.b64e(phone.key)[:20] if phone.key else '无'}…")
        if phone.key and link:
            with link._peers_lock:
                keys = [p.get("key") for p in link._peers.values()] + list(link._pairing_keys.values())
            match = any(k == phone.key for k in keys if k)
            print(f"手机密钥是否在 PC 候选里: {match}")

    phone.close()
    mgr.stop()
    relay.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
