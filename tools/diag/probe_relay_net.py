"""中继连通性测速：直连 vs 系统代理。

结论要能量化：桌面端裸奔直连到底多慢、会不会超时。
"""
import os
import socket
import ssl
import sys
import time

URL = "wss://mollypaw-online.pages.dev/server"
HOST = "mollypaw-online.pages.dev"
PORT = 443


def tcp_direct(host, port, timeout=30):
    t0 = time.time()
    s = socket.create_connection((host, port), timeout=timeout)
    dt = time.time() - t0
    s.close()
    return dt


def tls_direct(host, timeout=30):
    ctx = ssl.create_default_context()
    t0 = time.time()
    raw = socket.create_connection((host, PORT), timeout=timeout)
    ss = ctx.wrap_socket(raw, server_hostname=host)
    dt = time.time() - t0
    ss.close()
    return dt


def via_proxy(proxy_host, proxy_port, host, timeout=30):
    """CONNECT 隧道 + TLS。"""
    t0 = time.time()
    s = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    s.sendall(
        f"CONNECT {host}:{PORT} HTTP/1.1\r\nHost: {host}:{PORT}\r\n\r\n".encode()
    )
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            raise RuntimeError("代理断开")
        buf += chunk
    if b" 200 " not in buf.split(b"\r\n")[0]:
        raise RuntimeError("代理拒绝: " + buf.split(b"\r\n")[0].decode("latin-1"))
    ctx = ssl.create_default_context()
    ss = ctx.wrap_socket(s, server_hostname=host)
    dt = time.time() - t0
    ss.close()
    return dt


def main():
    print(f"target = {URL}\n")
    for i in range(3):
        try:
            d = tcp_direct(HOST, PORT)
            print(f"  直连 TCP  #{i+1}: {d:6.2f}s")
        except Exception as exc:
            print(f"  直连 TCP  #{i+1}: 失败 {type(exc).__name__}: {exc}")
    for i in range(3):
        try:
            d = tls_direct(HOST)
            print(f"  直连 TLS  #{i+1}: {d:6.2f}s")
        except Exception as exc:
            print(f"  直连 TLS  #{i+1}: 失败 {type(exc).__name__}: {exc}")
    for i in range(3):
        try:
            d = via_proxy("127.0.0.1", 7897, HOST)
            print(f"  代理 7897 #{i+1}: {d:6.2f}s")
        except Exception as exc:
            print(f"  代理 7897 #{i+1}: 失败 {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
