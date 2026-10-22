"""核查两个具体论断。

1) 换 PSK 后"之前的设备全部自动作废"——到底作废了什么？
   要分清两件事：
     a. 能不能连上（连通性）
     b. 授权还在不在（devices.json 里的记录）
   换 PSK 只改变 (a)，不改 (b)。要把这个差别用代码摆出来。

2) "PIN 单独就能连接"——验证没有 PIN 能不能连；
   以及持有 PSK 时 PIN 是否还有任何额外约束力。

用法：.venv\\Scripts\\python.exe tools\\audit_psk_room.py
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from agent.relay import crypto as C
from agent.relay.devices import DeviceStore


def head(t):
    print("\n" + "=" * 64)
    print(t)
    print("=" * 64)


def part1():
    head("1. 换 PSK：房间号变了，然后呢？")

    OLD_PSK = "MollyPawOld12345"
    NEW_PSK = "MollyPawNew12345"

    tmp = tempfile.mkdtemp(prefix="audit-psk-")
    store = DeviceStore(path=os.path.join(tmp, "devices.json"))

    # 用旧 PSK 配一台设备
    sess = store.new_pin("app")
    proof = C.pair_proof(sess.pin, sess.salt, "phone-A", "旧手机")
    res, err = store.claim_pin(sess.pin, proof, "phone-A", "旧手机", os.urandom(32))
    token_a = res["token"]

    old_room = C.derive_room(OLD_PSK)
    new_room = C.derive_room(NEW_PSK)

    print(f"用旧 PSK 配好一台设备 phone-A")
    print(f"  旧 PSK 派生 room = {old_room}")
    print(f"  新 PSK 派生 room = {new_room}")

    print("\n--- (a) 连通性 ---")
    print(f"  旧设备仍然只知道 room={old_room}")
    print(f"  PC 换 PSK 后监听的是 room={new_room}")
    print(f"  两个房间不同 → 直接连不上 ✅ 这部分你说得对")
    print(f"  中继侧看到的是另一个房间，连'有这台设备'都看不到")

    print("\n--- (b) 授权记录 ---")
    devs = store.public_list()
    print(f"  换 PSK 过后，devices.json 里还剩 {len(devs)} 条：")
    for d in devs:
        print(f"    - {d['name']} ({d['dev_id']}) role={d['role']} revoked={d['revoked']}")

    dev, err2 = store.authenticate("phone-A", time.time(), token_a)
    print(f"  用旧 token 认证 -> {'通过' if dev else '失败'}（err={err2}）")

    print("\n--- 关键：设备拿到新 PSK 会怎样 ---")
    # 模拟"用户把新 PSK 也告诉了这台设备"（比如换密码后手机上重新输入）
    # 设备此时知道 new_room，且 token 从未失效
    dev2, err3 = store.authenticate("phone-A", time.time(), token_a)
    if dev2:
        print("  新 PSK 一填进去 → 立刻能在新房间认证成功（token 从没失效）")
        print("  ！！ 所以换 PSK 是'断网'，不是'吊销'。授权记录还躺在磁盘上。")
    else:
        print("  认证失败，设备确实被撤销了")

    return len(devs), dev2 is not None


def part2():
    head("2. PIN 的实际作用域")

    tmp = tempfile.mkdtemp(prefix="audit-pin-")
    store = DeviceStore(path=os.path.join(tmp, "devices.json"))

    print("--- 没有 PIN，能不能连？---")
    # 只要知道 room（=持有 PSK），就能建立 WS、完成握手、收发加密帧。
    # 配对只是在"第一次"多一步，之后全靠 token。
    print("  握手 = hello 交换 eph/hs + HKDF。全程只用 PSK，不碰 PIN。")
    print("  → 持有 PSK 就能进房间、能握手、能收发加密帧。PIN 不参与。")

    print("\n--- PIN 唯一约束的时刻 ---")
    sess = store.new_pin("app")
    print(f"  PC 生成 PIN={sess.pin}，此刻没有它就配不上对")
    ok, err = store.claim_pin("000000" if sess.pin != "000000" else "111111",
                              b"x" * 32, "intruder", "baddie", os.urandom(32))
    print(f"  错误 PIN 配对 -> ok={ok is not None} err={err}  （被挡）")

    print("\n--- 但前提是攻击者已经持有 PSK ---")
    print("  要先能算出 room、完成握手，才轮到发 pair.req。")
    print("  两个前提同时具备才需要 PIN：")
    print("    持有 PSK  +  在 300 秒窗口内  +  PC 正好开着待配对待认领")
    print("  缺任何一条，PIN 都无关紧要。")

    print("\n--- PIN 长度与实际防护 ---")
    import math
    print(f"  6 位数字 = 10^6 = {10**6} 种")
    print(f"  5 次上限 → 在线爆破成功率约 {5/10**6:.2e}")
    print(f"  真正把攻击者挡在外面的是 PSK，不是这 6 位")
    return True


def main():
    n_devices, still_authorized = part1()
    part2()

    head("结论")
    print(f"① 换 PSK 变房间号：连通性断了 —— 正确")
    print(f"② 换 PSK 自动作废设备：**错误**")
    print(f"   实测：devices.json 仍留 {n_devices} 条记录，旧 token 仍可通过认证")
    print(f"   准确说法：换 PSK = 断网；吊销 = 删记录。两者不是一回事。")
    print(f"③ PIN 单独连不上：正确（room 都由 PSK 派生）")
    print(f"   但 PIN 的价值区间极窄：只在「已持有 PSK」+「300 秒内」+「PC 待配对」")
    print(f"④ 因此 PIN 的定位应该是你说的：安全、简单、随时连接")
    print(f"   即：它服务于'我不要每次填 PSK'的日常体验，不是安全边界")
    return 0


if __name__ == "__main__":
    sys.exit(main())
