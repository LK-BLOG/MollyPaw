"""统一的中继连接入口：并发竞速 + 重试，不依赖任何代理。

为什么要竞速：实测到 pages.dev 的直连 TLS 握手是**概率性**的
（三次：0.58s 成功 / 超时 / 7.11s 成功）。一次失败不代表不可达，
短超时 + 多次重试通常就能过。有系统代理时再并发一路代理，谁先通用谁。

绝不能把"用户必须挂代理"当成前提 —— 中国用 VPN 并不完全合法，
普通用户不该被要求装这东西。
"""
import threading
import time

DEFAULT_TIMEOUT = 8.0
DEFAULT_ATTEMPTS = 4

_LOCAL_NAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _host_of(url):
    """从 ws(s)://host:port/path 里抠出 host。"""
    text = (url or "").strip()
    for prefix in ("wss://", "ws://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    for sep in ("/", "?", "#"):
        idx = text.find(sep)
        if idx >= 0:
            text = text[:idx]
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    if text.startswith("[") and "]" in text:      # [::1]:1234
        return text[1:text.index("]")]
    return text.rsplit(":", 1)[0] if ":" in text else text


def _is_local_host(host):
    """本机、私有网段、*.local —— 这些走代理只会更慢或直接失败。"""
    if not host:
        return False
    h = host.lower().strip(".")
    if h in _LOCAL_NAMES:
        return True
    if h.endswith(".local") or h.endswith(".lan"):
        return True
    parts = h.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        a, b = int(parts[0]), int(parts[1])
        # 10/8、172.16/12、192.168/16、169.254/16
        if a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168) \
                or (a == 169 and b == 254):
            return True
    return False


def open_ws(url, timeout=DEFAULT_TIMEOUT, attempts=DEFAULT_ATTEMPTS,
            proxy_mode="auto", logger=None, sslopt=None):
    """开一条 WebSocket，返回 websocket 对象；全失败抛最后一个异常。

    url       ws:// 或 wss:// 完整地址（含 query）
    timeout   单次尝试的超时秒数（短超时才有机会重试）
    attempts  最多尝试几轮
    proxy_mode "auto" / "direct" / "http://host:port"
    """
    import websocket
    from agent.relay.net import proxy_kwargs, resolve_proxy

    def log(msg):
        if logger:
            try:
                logger(msg)
            except Exception:
                pass

    sslopt = sslopt or {}

    # 本地/局域网地址一律不走代理：给本地 dev server 和同 WiFi 直连用
    host = _host_of(url)
    local = _is_local_host(host)

    # 候选路线：有代理就并发「代理 + 直连」，没代理就只有直连
    routes = []
    proxy = None if local else resolve_proxy(proxy_mode)
    if proxy:
        routes.append(("代理 %s:%s" % (proxy["host"], proxy["port"]),
                       proxy_kwargs(proxy_mode)))
    direct_mode = (proxy_mode or "").strip().lower()
    if local or direct_mode not in ("direct", "none", "off", "no"):
        routes.append(("直连", {}))
    if not routes:
        routes.append(("直连", {}))

    last_exc = None
    for attempt in range(1, max(1, attempts) + 1):
        # 单路线就不必并发，省线程
        if len(routes) == 1:
            label, kwargs = routes[0]
            try:
                ws = websocket.create_connection(url, timeout=timeout, sslopt=sslopt, **kwargs)
                log(f"relay {label} 连上（第 {attempt} 次尝试）")
                return ws
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log(f"relay {label} 第 {attempt} 次失败：{type(exc).__name__}: {exc}")
        else:
            result = _race(url, routes, timeout, sslopt, log, attempt)
            if isinstance(result, tuple) and result and result[0] == "ok":
                return result[1]
            last_exc = result[1] if isinstance(result, tuple) else last_exc

        if attempt < attempts:
            # 轻退避：干扰是概率性的，等 0.4/0.8/1.2 秒再来一次就够
            time.sleep(min(0.4 * attempt, 1.2))

    raise last_exc or RuntimeError("relay connect failed")


def _race(url, routes, timeout, sslopt, log, attempt):
    """并发跑所有路线，第一个连上的赢；其余线程的 socket 关掉。"""
    import websocket

    lock = threading.Lock()
    winner = {"ws": None, "errors": []}

    def try_route(label, kwargs):
        try:
            ws = websocket.create_connection(url, timeout=timeout, sslopt=sslopt, **kwargs)
        except Exception as exc:  # noqa: BLE001
            with lock:
                winner["errors"].append((label, exc))
            return
        with lock:
            if winner["ws"] is None:
                winner["ws"] = ws
                log(f"relay {label} 连上（第 {attempt} 次尝试）")
            else:
                # 已经有人赢了，这条多余的连接直接关掉
                try:
                    ws.close()
                except Exception:
                    pass

    threads = []
    for label, kwargs in routes:
        t = threading.Thread(target=try_route, args=(label, kwargs), daemon=True)
        t.start()
        threads.append(t)
    deadline = time.time() + timeout + 1.0
    for t in threads:
        t.join(max(0.05, deadline - time.time()))

    with lock:
        if winner["ws"] is not None:
            return ("ok", winner["ws"])
        errs = list(winner["errors"])
    if errs:
        label, exc = errs[-1]
        log(f"relay 全部路线失败：{label}: {exc}")
        return ("fail", exc)
    return ("fail", RuntimeError("relay connect timeout"))
