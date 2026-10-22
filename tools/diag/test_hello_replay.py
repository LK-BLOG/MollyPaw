"""最小实验：验证中继是否把 PC 的 hello 回放给后加入的手机。

不掺业务逻辑，只连两条裸 WS，看第二个连上时能不能收到第一个的 hello。
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

PORT = 18997
ROOM = "a" * 32


def main():
    relay = DevRelay("127.0.0.1", PORT)
    relay.start_background()

    url = f"ws://127.0.0.1:{PORT}/server?room={ROOM}"

    pc = websocket.create_connection(url, timeout=5)
    pc.send(json.dumps({
        "v": 1, "t": "hello", "r": ROOM, "f": "pc", "dev": "pc-1",
        "eph": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        "hs": "AAAAAAAAAAAAAAAAAAAAAA==",
    }))
    time.sleep(0.8)
    print("PC 已发 hello")

    phone = websocket.create_connection(url, timeout=5)
    phone.send(json.dumps({
        "v": 1, "t": "hello", "r": ROOM, "f": "app", "dev": "phone-1",
        "eph": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=",
        "hs": "BBBBBBBBBBBBBBBBBBBBBB==",
    }))
    time.sleep(0.8)

    print("\n--- 手机收到了什么 ---")
    phone.settimeout(1.5)
    got_hello = False
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            raw = phone.recv()
        except Exception:
            break
        try:
            frame = json.loads(raw)
        except Exception:
            continue
        t = frame.get("t")
        print(f"  t={t} f={frame.get('f')} dev={frame.get('dev')} "
              f"eph={'有' if frame.get('eph') else '无'}")
        if t == "hello" and frame.get("f") == "pc":
            got_hello = True

    print("\n--- PC 收到了什么 ---")
    pc.settimeout(1.5)
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            raw = pc.recv()
        except Exception:
            break
        try:
            frame = json.loads(raw)
        except Exception:
            continue
        print(f"  t={frame.get('t')} f={frame.get('f')} dev={frame.get('dev')}")

    print(f"\n结论：手机收到 PC 的 hello = {got_hello}")
    pc.close()
    phone.close()
    relay.shutdown()
    return 0 if got_hello else 1


if __name__ == "__main__":
    sys.exit(main())
