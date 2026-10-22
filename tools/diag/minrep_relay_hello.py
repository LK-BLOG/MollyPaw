"""最小复现：设备重连时，中继有没有把新 hello 转给 PC。

只连两条裸 WS，不用任何业务逻辑：
  1. PC 连上并发 hello
  2. 手机 A 连上发 hello（PC 应收到）
  3. 手机 A **断开**
  4. 手机 A 用**新的 eph** 重连发 hello
  5. PC 应该收到这条新 hello —— 它有新的 eph

如果第 5 步收不到，问题就在中继的 hello 转发逻辑。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "MollyPaw-Relay"))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import websocket
from relay.dev_server import DevRelay

PORT = 19007
ROOM = "b" * 32


def hello(dev, eph_marker, role="app"):
    return {
        "v": 1, "t": "hello", "r": ROOM, "f": role, "dev": dev,
        "eph": eph_marker * 43,
        "hs": "A" * 22 + "==",
    }


def drain(ws, label, seconds=1.5):
    ws.settimeout(seconds)
    got = []
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            raw = ws.recv()
        except Exception:
            break
        try:
            f = json.loads(raw)
        except Exception:
            continue
        got.append(f)
        eph = f.get("eph", "")
        print(f"    {label} <- t={f.get('t')} f={f.get('f')} dev={f.get('dev')} "
              f"eph={eph[:6]}...")
    return got


def main():
    relay = DevRelay("127.0.0.1", PORT)
    relay.start_background()
    url = f"ws://127.0.0.1:{PORT}/server?room={ROOM}"

    pc = websocket.create_connection(url, timeout=5)
    pc.send(json.dumps(hello("pc-1", "P", "pc")))
    time.sleep(0.6)
    drain(pc, "PC(初始)", 0.8)

    print("\n[1] 手机第一次连上")
    p1 = websocket.create_connection(url, timeout=5)
    p1.send(json.dumps(hello("phone-1", "A")))
    time.sleep(0.8)
    got1 = drain(pc, "PC")
    print(f"    PC 收到 hello：{sum(1 for f in got1 if f.get('t') == 'hello')} 条")

    print("\n[2] 手机断开")
    p1.close()
    time.sleep(0.8)
    drain(pc, "PC(断开后)", 1.0)

    print("\n[3] 手机用**新的 eph** 重连")
    p2 = websocket.create_connection(url, timeout=5)
    p2.send(json.dumps(hello("phone-1", "C")))   # C != A，代表换过临时密钥
    time.sleep(1.0)
    got2 = drain(pc, "PC")
    new_hellos = [f for f in got2 if f.get("t") == "hello"]
    print(f"    PC 收到 hello：{len(new_hellos)} 条")
    if new_hellos:
        eph = new_hellos[-1].get("eph", "")
        print(f"    最新 eph 前缀 = {eph[:6]}（期望以 C 开头）")
        ok = eph.startswith("C")
    else:
        ok = False
        print("    ！！ PC 没收到重连后的 hello —— 它无法派生新密钥")

    print("\n结论:", "✅ 重连 hello 正常转发" if ok else "❌ 中继漏转发重连 hello")

    pc.close()
    p2.close()
    relay.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
