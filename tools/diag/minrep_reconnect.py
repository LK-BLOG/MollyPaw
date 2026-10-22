"""最小复现：手机配对后换主 PSK 重连，PC 端能不能跟上。

只做必要的事，把问题缩到最小：
  A. PC 起中继连接
  B. 手机配对（用 pair_key）
  C. 手机换主 PSK 重连
  D. 手机发一个简单请求，看 PC 能不能解开

每一步都打印 PC 端的 _peers 与 session_key，直观看它认的是哪把钥匙。
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

PSK = "MollyPawMinRep123"
PORT = 19005


def dump_pc(mgr, tag):
    link = mgr.link
    if link is None:
        print(f"  [{tag}] PC link = None")
        return
    with link._peers_lock:
        peers = {pid: ("有" if p.get("key") else "无", p.get("role"))
                 for pid, p in link._peers.items()}
        pairing = list(link._pairing_keys.keys())
    print(f"  [{tag}] _peers={peers} pairing_keys={pairing} "
          f"session_key={'有' if link.session_key else '无'} "
          f"gen={link._generation}")


def main():
    relay = DevRelay("127.0.0.1", PORT)
    relay.start_background()

    tmp = tempfile.mkdtemp(prefix="minrep-")
    service = MollyPawService()
    mgr = RelayManager(service, config={"url": f"ws://127.0.0.1:{PORT}/server", "psk": PSK},
                       logger=lambda m: print(f"[relay] {m}"))
    mgr.devices = DeviceStore(path=os.path.join(tmp, "devices.json"))
    mgr.bridge.devices = mgr.devices
    mgr.start()
    for _ in range(100):
        if mgr.status()["connected"]:
            break
        time.sleep(0.05)
    print("A. PC 已连上")
    dump_pc(mgr, "A")

    session = mgr.new_pairing("app")
    phone = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="最简手机")
    ok, res = phone.pair(session["code"])
    print(f"\nB. 配对 ok={ok}")
    dump_pc(mgr, "B")

    main_psk = getattr(phone, "main_psk", "")
    print(f"\nC. 手机拿到主 PSK: {'是' if main_psk else '否'}"
          f"{' 与 PC 一致' if main_psk == PSK else ' 与 PC 不一致（服务端下发的）'}")
    print(f"   服务端下发值 = {main_psk[:14]}...   PC 配置值 = {PSK[:14]}...")

    # 用主 PSK 重连
    phone.close()
    time.sleep(0.5)
    phone._stop.clear()
    room = C.derive_room(phone.psk)
    phone.connect(room)
    ok2 = phone.wait_key(timeout=10)
    print(f"\nD. 重连 ok={ok2}  手机 session_key={'有' if phone.key else '无'}")
    dump_pc(mgr, "D")
    time.sleep(0.8)
    dump_pc(mgr, "D+0.8s")

    print("\nE. 发 status.get")
    ok3, res3 = phone.call("status.get", timeout=10)
    print(f"   结果 ok={ok3} res={str(res3)[:100]}")
    dump_pc(mgr, "E")

    phone.close()
    mgr.stop()
    relay.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
