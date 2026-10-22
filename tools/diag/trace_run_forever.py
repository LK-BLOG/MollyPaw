"""把 RelayLink.run_forever 的每一步打出来，定位卡在哪。

不猜了：直接在真实路径上插桩。
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from agent.relay import crypto as C
from agent.relay.client import RelayLink

PSK = "MollyPawTrace12345"
URL = "wss://mollypaw-online.pages.dev/server"
room = C.derive_room(PSK)
print(f"room = {room}")

stop = threading.Event()

link = RelayLink(
    url=URL, room=room, role="pc", psk=PSK, dev_id="pc",
    on_payload=lambda *a: print(f"  [payload] {a[0]}"),
    on_state=lambda s, i: print(f"  [state] {s} {i or ''}"),
    logger=lambda m: print(f"  [log] {m}"),
)

# 插桩 connect
orig_connect = link.connect
def traced_connect(*a, **kw):
    print("  >>> connect() 开始")
    t0 = time.time()
    try:
        r = orig_connect(*a, **kw)
        print(f"  >>> connect() 返回 {r}，耗时 {time.time()-t0:.1f}s")
        return r
    except Exception as exc:
        print(f"  >>> connect() 抛错 {type(exc).__name__}: {exc}，耗时 {time.time()-t0:.1f}s")
        raise
link.connect = traced_connect

orig_should = stop.is_set
calls = {"n": 0}
def traced_should():
    calls["n"] += 1
    if calls["n"] <= 6 or calls["n"] % 20 == 0:
        print(f"  >>> should_stop() 第 {calls['n']} 次 -> {orig_should()}")
    return orig_should()

t = threading.Thread(target=link.run_forever, args=(traced_should,), daemon=True)
t.start()

for i in range(20):
    time.sleep(1)
    if link.session_key is not None:
        print(f"t={i+1}s 会话密钥已建立，连着 = {link._connected}")
        break
    print(f"t={i+1}s connected={link._connected} key={'有' if link.session_key else '无'}")
else:
    print("20 秒仍未建立会话密钥")

stop.set()
link.close("trace done")
time.sleep(1)
print("线程还活着？", t.is_alive())
