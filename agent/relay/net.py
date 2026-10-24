"""MollyPaw Relay — 网络工具（IPv4 优先 + 代理探测）。

两个真实踩到的坑，都在这个文件里兜：

1. **IPv6 黑洞**
   国内很多宽带没有 IPv6，但 Cloudflare 的域名同时返回 AAAA 记录。
   `websocket-client` 的 `_open_socket` 在 connect 出错时，只要 errno 不是
   ECONNREFUSED / ENETUNREACH 就直接 raise，不再试下一个地址
   （见 websocket/_http.py）。IPv6 不可达时是 ETIMEDOUT，于是整条连接直接
   失败，明明 IPv4 是通的。 → 没有 v6 出口时把 getaddrinfo 过滤成只返回 v4。

2. **TLS 握手被干扰 / 系统代理不生效**
   实测（2026-10，本机）：到 `mollypaw-online.pages.dev:443` 的
   TCP 直连 0.3s 稳定，但 **TLS 直连三次里一次 7.1s、一次直接超时**；
   走本地 HTTP 代理则稳定 0.65s。
   而 `websocket-client` 只认 `http_proxy` / `https_proxy` **环境变量**，
   **完全不读 Windows 系统代理**（注册表里的 ProxyEnable/ProxyServer）。
   桌面端是 GUI 起的进程，环境变量里什么都没有 —— 于是一路裸连，
   TLS 超时，`connect(timeout=20)` 判失败，无限重连：
   手机端看到的现象就是「电脑没在线 / 一直没收到响应」。
   → 这里主动探测系统代理，并把参数显式传给 websocket-client。
"""
import os
import socket
import sys
import threading

# --------------------------------------------------------------------------
# IPv6 探测
# --------------------------------------------------------------------------

_state = {"ipv6": None, "force": None}
_lock = threading.Lock()

# 探测目标：Cloudflare / Google 的知名 IPv6（避免依赖外部 HTTP 服务）
_PROBE_TARGETS = [
    ("2606:4700:4700::1111", 443),
    ("2001:4860:4860::8888", 443),
]


def has_ipv6(timeout=1.0):
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
                s = None
                try:
                    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                    s.settimeout(timeout)
                    s.connect(info[4])
                    ok = True
                except Exception:
                    ok = False
                finally:
                    if s is not None:
                        try:
                            s.close()
                        except Exception:
                            pass
                if ok:
                    break
            if ok:
                break
        _state["ipv6"] = ok
        return ok


def reset_cache():
    with _lock:
        _state["ipv6"] = None
        _state["force"] = None


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


# --------------------------------------------------------------------------
# 代理探测
# --------------------------------------------------------------------------

# 环境变量优先级：https 优先（wss 走 CONNECT 隧道，多数本地代理两者同一端口）
_ENV_KEYS = (
    "https_proxy", "HTTPS_PROXY",
    "http_proxy", "HTTP_PROXY",
    "all_proxy", "ALL_PROXY",
)

_DEFAULT_PORTS = {"http": 8080, "https": 8443, "socks5": 1080, "socks5h": 1080,
                  "socks4": 1080}


def _strip_scheme(value):
    """`http://127.0.0.1:7897` -> (`http`, `127.0.0.1:7897`)。"""
    kind = "http"
    text = (value or "").strip()
    if "://" in text:
        kind, text = text.split("://", 1)
        kind = kind.lower()
    # 去掉 user:pass@
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    return kind, text.rstrip("/")


def parse_proxy(value):
    """把各种写法的代理配置解析成 dict；无效返回 None。

    支持：
        http://127.0.0.1:7897
        socks5://127.0.0.1:1080
        127.0.0.1:7897
    """
    if not value:
        return None
    kind, text = _strip_scheme(value)
    if not text:
        return None
    # `host:port`（IPv6 要带方括号，这里不强求）
    if ":" in text:
        host, port_text = text.rsplit(":", 1)
        try:
            port = int(port_text)
        except ValueError:
            return None
    else:
        host = text
        port = _DEFAULT_PORTS.get(kind)
        if not port:
            return None
    host = host.strip("[]")
    if not host:
        return None
    return {"type": kind, "host": host, "port": port}


def parse_windows_proxy_server(server):
    """解析注册表里的 ProxyServer。

    Windows 有两种写法：
        `127.0.0.1:7897`
        `http=127.0.0.1:7897;https=127.0.0.1:7897;ftp=...`
    """
    if not server:
        return None
    text = server.strip()
    if "=" not in text:
        return parse_proxy(text)
    mapping = {}
    for part in text.split(";"):
        if not part or "=" not in part:
            continue
        key, val = part.split("=", 1)
        mapping[key.strip().lower()] = val.strip()
    for key in ("https", "http", "all", "socks"):
        if mapping.get(key):
            parsed = parse_proxy(mapping[key])
            if parsed:
                return parsed
    return None


def detect_system_proxy():
    """探测系统代理。

    顺序：环境变量 -> Windows 注册表 -> 无。
    macOS / Linux 只认环境变量（绝大多数发行版也是这么用的）。
    """
    for key in _ENV_KEYS:
        parsed = parse_proxy(os.environ.get(key))
        if parsed:
            return parsed

    if sys.platform == "win32":
        try:
            import winreg

            key_path = (
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            )
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                if not enabled:
                    return None
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
            return parse_windows_proxy_server(server)
        except Exception:
            return None
    return None


def resolve_proxy(mode=None):
    """按配置决定用哪个代理。

    mode 取值：
        None / "" / "auto"  -> 自动探测系统代理（默认）
        "direct" / "none"   -> 强制直连
        "http://h:p" 等     -> 显式指定
    返回 dict 或 None（直连）。
    """
    text = (mode or "").strip()
    if text.lower() in ("direct", "none", "off", "no"):
        return None
    if text and text.lower() != "auto":
        return parse_proxy(text)
    return detect_system_proxy()


def proxy_kwargs(mode=None):
    """给 `websocket.create_connection` 用的代理参数。

    不走代理时返回 {}，调用方直接 ** 展开即可。
    Socks 代理需要 PySocks（requirements 里没有），解析到 socks 就退回直连，
    免得为了一个可选功能让整个远程互联 import 失败。
    """
    proxy = resolve_proxy(mode)
    if not proxy:
        return {}
    if proxy["type"] in ("socks5", "socks5h", "socks4"):
        try:
            import socks  # noqa: F401
        except Exception:
            return {}
        kind = "socks5" if proxy["type"].startswith("socks5") else "socks4"
        return {
            "http_proxy_host": proxy["host"],
            "http_proxy_port": proxy["port"],
            "proxy_type": kind,
        }
    return {
        "http_proxy_host": proxy["host"],
        "http_proxy_port": proxy["port"],
        "proxy_type": "http",
    }
