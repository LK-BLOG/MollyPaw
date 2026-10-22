"""诊断：connect() 到底卡在哪一步。

卡在 starting 说明线程进了 run_forever 但 connect() 没返回。
逐步计时，定位是 IPv6 探测、DNS 还是 TLS 握手。
"""
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

URL_HOST = "mollypaw-online.pages.dev"
URL_PORT = 443

print("=== 1. 有没有可用 IPv6 ===")
t0 = time.time()
try:
    from agent.relay.net import has_ipv6
    print(f"has_ipv6() = {has_ipv6()}   耗时 {time.time()-t0:.1f}s")
except Exception as exc:
    print(f"探测失败: {exc}  耗时 {time.time()-t0:.1f}s")

print("\n=== 2. DNS 解析 ===")
t0 = time.time()
try:
    infos = socket.getaddrinfo(URL_HOST, URL_PORT, 0, socket.SOCK_STREAM)
    v4 = [i for i in infos if i[0] == socket.AF_INET]
    v6 = [i for i in infos if i[0] == socket.AF_INET6]
    print(f"总 {len(infos)} 条：IPv4 {len(v4)} 条，IPv6 {len(v6)} 条，"
          f"耗时 {time.time()-t0:.1f}s")
    for i in v4[:3]:
        print(f"   v4 {i[4][0]}")
except Exception as exc:
    print(f"DNS 失败: {exc}")

print("\n=== 3. IPv4 TCP 443 连通性 ===")
t0 = time.time()
try:
    s = socket.create_connection((URL_HOST, URL_PORT), timeout=10)
    print(f"  直连成功，耗时 {time.time()-t0:.1f}s  peer={s.getpeername()}")
    s.close()
except Exception as exc:
    print(f"  直连失败: {exc}  耗时 {time.time()-t0:.1f}s")

print("\n=== 4. websocket 连接（真正的路径）===")
t0 = time.time()
try:
    import websocket
    from agent.relay.net import prefer_ipv4
    with prefer_ipv4():
        ws = websocket.create_connection(
            "wss://mollypaw-online.pages.dev/server?room=" + "a" * 32,
            timeout=15,
        )
    print(f"  WS 连上，耗时 {time.time()-t0:.1f}s")
    ws.close()
except Exception as exc:
    print(f"  WS 失败: {type(exc).__name__}: {exc}  耗时 {time.time()-t0:.1f}s")
