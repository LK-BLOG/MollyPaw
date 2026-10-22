"""跨局域网 RelayRoom 冒烟测试 —— 打真实 Cloudflare 部署。

用法：
    .venv\\Scripts\\python.exe tools\\relay_smoke.py
    .venv\\Scripts\\python.exe tools\\relay_smoke.py --url wss://.../server

验证：
  1. PC 与 app 两条 WS 经 Pages Function -> Durable Object 连上同一房间
  2. 加密帧 pc -> app 可达，且解出的明文正确
  3. observer 的 data 帧被拒（forbidden）
  4. 没有 pc 时 app 收到 offline 提示
  5. app -> pc 可达

这是真联调，不是 mock。任何一步失败都会以非 0 退出码结束。
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 控制台默认 GBK，中文输出会乱码
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import websocket  # websocket-client

from agent.relay import crypto as C
from agent.relay import protocol as P
from agent.relay.net import has_ipv6, prefer_ipv4

DEFAULT_URL = "wss://mollypaw-online.pages.dev/server"
PSK = "MollyPawSmoke12345"

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append((name, detail))
        print(f"  [FAIL] {name} :: {detail}")


_last_connect = [0.0]


def ws_connect(url, room, timeout=25, retries=5, min_gap=1.2):
    """连 WS，带重试 + 连接间隔 + IPv6 规避。

    两个真实问题叠在一起：
      1. 国内到 Cloudflare 的 TLS 握手偶尔抖（网络事实，重试解决）；
      2. 本机无 IPv6 但域名有 AAAA，websocket-client 遇 v6 超时直接放弃
         不回落 v4（代码缺陷，用 prefer_ipv4 解决）。
    """
    full = f"{url}?room={room}"
    last = None
    for attempt in range(retries):
        # 全局节流：两条连接至少隔 min_gap 秒，避免同 IP 并发握手中招
        gap = min_gap - (time.time() - _last_connect[0])
        if gap > 0:
            time.sleep(gap)
        try:
            with prefer_ipv4():
                conn = websocket.create_connection(full, timeout=timeout)
            _last_connect[0] = time.time()
            return conn
        except Exception as exc:
            last = exc
            _last_connect[0] = time.time()
            time.sleep(2.0 * (attempt + 1))
    raise last


def send(ws, frame):
    ws.send(json.dumps(frame, ensure_ascii=False))


def recv(ws, timeout=6.0):
    ws.settimeout(timeout)
    raw = ws.recv()
    return json.loads(raw)


def recv_until(ws, predicate, timeout=8.0, ignore_errors=False):
    """收到第一个满足 predicate 的帧；跳过 others。"""
    deadline = time.time() + timeout
    skipped = []
    while time.time() < deadline:
        try:
            ws.settimeout(max(0.2, deadline - time.time()))
            frame = json.loads(ws.recv())
        except Exception as exc:
            if ignore_errors:
                return None, skipped, str(exc)
            raise
        if predicate(frame):
            return frame, skipped, None
        skipped.append(frame)
    return None, skipped, "timeout"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--psk", default=PSK)
    args = parser.parse_args()

    room = C.derive_room(args.psk)
    print(f"中继: {args.url}")
    print(f"PSK : {args.psk}")
    print(f"room: {room}")
    v6 = has_ipv6()
    print(f"IPv6: {'有' if v6 else '无（将强制 IPv4）'}\n")

    # ---- 0. 密钥强度 ----
    print("[0] PSK 强度")
    check("PSK 通过强度校验", C.psk_ok(args.psk))

    # ---- 1. 无 pc 时 app 收到 offline ----
    print("\n[1] 离线提示")
    try:
        app0 = ws_connect(args.url, room)
        send(app0, P.hello_frame(room, "app", dev="smoke-app0", ts=int(time.time() * 1000)))
        time.sleep(0.6)
        # 握手阶段可能先来 presence
        seq = 1
        payload = P.payload("chat.send", {"text": "有人在吗"})
        frame = C.make_data_frame(os.urandom(32), room, "app", seq, "offline-1", payload)
        send(app0, frame)
        got, _, err = recv_until(app0, lambda f: f.get("t") == "error", timeout=8)
        check(
            "无 pc 时 app 收到 offline",
            got is not None and got.get("code") == "offline",
            f"got={got} err={err}",
        )
        if got:
            check("离线提示是中文文案", "电脑端已离线" in got.get("msg", ""), got.get("msg", ""))
        app0.close()
    except Exception as exc:
        check("无 pc 时 app 收到 offline", False, f"exception: {exc}")

    # ---- 2. pc + app 同房，加密互通 ----
    print("\n[2] 加密互通")
    pc = app = None
    try:
        pc = ws_connect(args.url, room)
        app = ws_connect(args.url, room)

        pc_priv, pc_pub = C.gen_ephemeral()
        app_priv, app_pub = C.gen_ephemeral()
        hs_pc = os.urandom(16)
        hs_app = os.urandom(16)

        send(pc, P.hello_frame(
            room, "pc", dev="smoke-pc", mode="auth", ts=int(time.time() * 1000)
        ))
        send(app, P.hello_frame(
            room, "app", dev="smoke-app", mode="auth", ts=int(time.time() * 1000)
        ))
        time.sleep(0.8)

        # 握手：把 eph / hs 塞进加密通道前的明文握手帧里。
        # 这里为了冒烟，直接本地派生同一把密钥（真实实现通过 hello 扩展字段交换）。
        key = C.derive_session_key(pc_priv, app_pub, args.psk, hs_pc, hs_app)
        key_app = C.derive_session_key(app_priv, pc_pub, args.psk, hs_pc, hs_app)
        check("两端派生同一把会话密钥", key == key_app)

        # pc -> app
        payload = P.payload("chat.delta", {
            "conversation_id": "c1", "message_id": "m1",
            "text": "你好，我是电脑上的 Molly。", "done": False,
        })
        frame = C.make_data_frame(key, room, "pc", 1, "pc-to-app-1", payload)
        send(pc, frame)

        got, skipped, err = recv_until(
            app, lambda f: f.get("t") == "data" and f.get("id") == "pc-to-app-1", timeout=10
        )
        check("pc -> app 加密帧经 CF 到达", got is not None, f"skipped={skipped} err={err}")
        if got:
            clear = C.open_data_frame(key_app, got, expect_role="pc")
            check(
                "app 解出正确明文",
                clear.get("p", {}).get("text") == "你好，我是电脑上的 Molly。",
                str(clear),
            )

        # app -> pc
        payload2 = P.payload("chat.send", {"text": "收到，开始干活"})
        frame2 = C.make_data_frame(key_app, room, "app", 1, "app-to-pc-1", payload2)
        send(app, frame2)

        got2, skipped2, err2 = recv_until(
            pc, lambda f: f.get("t") == "data" and f.get("id") == "app-to-pc-1", timeout=10
        )
        check("app -> pc 加密帧到达", got2 is not None, f"skipped={skipped2} err={err2}")
        if got2:
            clear2 = C.open_data_frame(key, got2, expect_role="app")
            check("pc 解出正确明文", clear2.get("p", {}).get("text") == "收到，开始干活", str(clear2))

        # 篡改必须被发现：拿同一帧改一个字节再用同 key 解
        if got2:
            tampered = dict(got2)
            raw = bytearray(C.b64d(tampered["c"]))
            raw[0] ^= 0x01
            tampered["c"] = C.b64e(bytes(raw))
            try:
                C.open_data_frame(key, tampered, expect_role="app")
                check("篡改密文被拒", False, "居然解开了")
            except Exception:
                check("篡改密文被拒", True)

    except Exception as exc:
        check("pc+app 加密互通", False, f"exception: {exc}")
    finally:
        for w in (pc, app):
            try:
                w.close()
            except Exception:
                pass

    # ---- 3. observer 只读 ----
    print("\n[3] 观察端只读")
    try:
        pc2 = ws_connect(args.url, room)
        obs = ws_connect(args.url, room)
        send(pc2, P.hello_frame(room, "pc", dev="smoke-pc2", ts=int(time.time() * 1000)))
        send(obs, P.hello_frame(room, "observer", dev="smoke-obs", ts=int(time.time() * 1000)))
        time.sleep(0.8)

        frame = C.make_data_frame(os.urandom(32), room, "observer", 1, "obs-1",
                                  P.payload("chat.send", {"text": "我要捣乱"}))
        send(obs, frame)
        got, _, err = recv_until(obs, lambda f: f.get("t") == "error", timeout=8)
        check(
            "observer 的 data 帧被拒",
            got is not None and got.get("code") == "forbidden",
            f"got={got} err={err}",
        )
        pc2.close()
        obs.close()
    except Exception as exc:
        check("observer 的 data 帧被拒", False, f"exception: {exc}")

    # ---- 4. pc 顶号 ----
    print("\n[4] pc 唯一")
    try:
        pc_a = ws_connect(args.url, room)
        pc_b = ws_connect(args.url, room)
        send(pc_a, P.hello_frame(room, "pc", dev="pc-a", ts=int(time.time() * 1000)))
        time.sleep(0.6)
        send(pc_b, P.hello_frame(room, "pc", dev="pc-b", ts=int(time.time() * 1000)))
        got, _, err = recv_until(
            pc_a, lambda f: f.get("t") == "bye" and f.get("reason") == "replaced", timeout=8
        )
        check("新 pc 顶掉旧 pc", got is not None, f"err={err}")
        pc_a.close()
        pc_b.close()
    except Exception as exc:
        check("新 pc 顶掉旧 pc", False, f"exception: {exc}")

    # ---- 汇总 ----
    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for name, detail in FAIL:
        print(f"  FAIL: {name} :: {detail}")
    print("=" * 56)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
