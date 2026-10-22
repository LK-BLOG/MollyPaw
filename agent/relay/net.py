"""MollyPaw Relay — 网络工具。

真实踩到的坑：国内很多宽带**没有 IPv6**，但 Cloudflare 的域名同时返回
AAAA 记录。`websocket-client` 的 `_open_socket` 在 connect 出错时，
只要 errno 不是 ECONNREFUSED / ENETUNREACH 就**直接 raise，不再试下一个地址**
（见 websocket/_http.py）。IPv6 不可达时是 ETIMEDOUT，于是整条连接直接失败，
明明 IPv4 是通的。

所以这里做两件事：
  1. 探测本机有没有可用的 IPv6 出口；
  2. 没有就把 `socket.getaddrinfo` 过滤成只返回 IPv4。

这样 `websocket-client` 拿到的地址列表里根本没有 v6，也就不会中招。
"""
import socket
import threading

_state = {"ipv6": None}
_lock = threading.Lock()

# 探测目标：Cloudflare 的知名 IPv6（避免依赖外部服务）
_PROBE_TARGETS = [
    ("2606:4700:4700::1111", 443),
    ("2001:4860:4860::8888", 443),
]


def has_ipv6(timeout=2.0):
    """探测本机是否有可用的 IPv6 出口。结果缓存。"""
    with _lock:
        if _state["ipv6"] is not None:
            return _state["ipv6"]
        ok = False
        for host, port in _PROBE_TARGETS:
            try:
                infos = socket.getaddrinfo(
                    host, port, socket.AF_INET6, socket.SOCK_STREAM, socket.SOL_TCP
                )
            except (socket.gaierror, OSError):
                continue
            for info in infos:
                try:
                    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                    s.settimeout(timeout)
                    s.connect(info[4])
                    s.close()
                    ok = True
                    break
                except Exception:
                    try:
                        s.close()
                    except Exception:
                        pass
            if ok:
                break
        _state["ipv6"] = ok
        return ok


def reset_cache():
    with _lock:
        _state["ipv6"] = None


def ipv4_only_enabled():
    """当前是否需要对 WebSocket 连接强制 IPv4。"""
    override = _state.get("force")
    if override is not None:
        return override
    return not has_ipv6()


def set_ipv4_only(value):
    """手动覆盖（配置项 relay.force_ipv4：True / False / None=自动）。"""
    _state["force"] = value


_orig_getaddrinfo = socket.getaddrinfo


def _filtered_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """只解析 IPv4 的 getaddrinfo。"""
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


class prefer_ipv4:
    """上下文管理器：在这段代码里把 DNS 解析限制为 IPv4。

    用法：
        with prefer_ipv4():
            ws.connect(url)

    只在检测到本机没有 IPv6 出口时生效，有 v6 的机器行为不变。
    """

    def __init__(self, force=None):
        self.force = force
        self._patched = False

    def __enter__(self):
        if self.force is None:
            need = not has_ipv6()
        else:
            need = bool(self.force)
        if need and socket.getaddrinfo is not _filtered_getaddrinfo:
            socket.getaddrinfo = _filtered_getaddrinfo
            self._patched = True
        return self

    def __exit__(self, *exc):
        if self._patched and socket.getaddrinfo is _filtered_getaddrinfo:
            socket.getaddrinfo = _orig_getaddrinfo
        self._patched = False
        return False
