"""验证一个关键问题：光有配对码，手机能连上吗？

设计意图（用户明确要求）：配对码应该"只用它就能连接"，
不需要手机上再手动输入那串 16 位 PSK。

但生成的配对码是 MP1.<b64(reg_token)>.<room>，
而 pair.req 是用 **PSK 派生的会话密钥**加密的 ——
如果手机没有 PSK，连会话密钥都派生不出来。

这个脚本用代码证明到底行不行。
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

PSK = "MollyPawSecTest99"
PORT = 18999


def main():
    relay = DevRelay("127.0.0.1", PORT)
    relay.start_background()

    tmp = tempfile.mkdtemp(prefix="diag-sec-")
    service = MollyPawService()
    mgr = RelayManager(service, config={"url": f"ws://127.0.0.1:{PORT}/server", "psk": PSK})
    mgr.devices = DeviceStore(path=os.path.join(tmp, "devices.json"))
    mgr.bridge.devices = mgr.devices
    mgr.start()
    for _ in range(100):
        if mgr.status()["connected"]:
            break
        time.sleep(0.05)

    session = mgr.new_pairing("app")
    code = session["code"]
    print(f"配对码: {code[:44]}...")
    print(f"配对码里有没有主 PSK？ {PSK in code}")
    print(f"配对码里有没有 room？ {C.derive_room(PSK) in code}")
    pair_seed, room = C.parse_pairing_code(code)
    pair_key = C.derive_pair_key(pair_seed)
    reg_token = C.derive_reg_token(pair_seed)
    print(f"配对码两段: pair_seed={len(pair_seed)}B  room={room[:8]}…")
    print(f"  从种子派生出: pair_key={len(pair_key)}B  reg_token={len(reg_token)}B")
    print(f"  配对码总长 {len(code)} 字符")

    # --- 情形 1：手机**只有配对码**，完全不知道 PSK ---
    print("\n" + "=" * 58)
    print("情形 1：手机只有配对码（不知道主 PSK）—— 这次应该能连上")
    print("=" * 58)
    p1 = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="扫码手机")
    ok, res = p1.pair(code, timeout=15)
    print(f"结果: ok={ok} {'成功，拿到 token' if ok else res}")
    if ok:
        print(f"  授予角色: {res.get('role')}")
    p1.close()
    time.sleep(0.8)

    # --- 情形 2：伪造的配对码（自己编一段 pair_key）---
    print("\n" + "=" * 58)
    print("情形 2：伪造配对码（pair_key 是自己编的）—— 应该失败")
    print("=" * 58)
    fake = C.make_pairing_code(os.urandom(C.PAIR_SEED_LEN), room)
    p2 = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="伪造码")
    ok2, res2 = p2.pair(fake, timeout=10)
    print(f"结果: ok={ok2} {'❌ 竟然成功了' if ok2 else '✅ 被拒绝: ' + str(res2)}")
    p2.close()

    # --- 情形 3：配对码重复使用 ---
    print("\n" + "=" * 58)
    print("情形 3：同一个配对码再用一次 —— 应该失败（一次性）")
    print("=" * 58)
    p3 = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="重复用")
    ok3, res3 = p3.pair(code, timeout=10)
    print(f"结果: ok={ok3} {'❌ 竟然还能用' if ok3 else '✅ 已失效: ' + str(res3)}")
    p3.close()

    print("\n" + "=" * 58)
    print("结论")
    print("=" * 58)
    if ok:
        print("✅ 配对码可以单独使用 —— 手机扫码即可，不用手输 PSK")
    else:
        print("❌ 配对码仍然不能单独使用")
    if not ok2:
        print("✅ 伪造的 pair_key 被拒绝（中继/PC 侧解不开）")
    else:
        print("⚠️ 伪造 pair_key 竟然成功，需要排查")
    if not ok3:
        print("✅ 配对码一次性")
    else:
        print("⚠️ 配对码可重复使用")

    mgr.stop()
    relay.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
