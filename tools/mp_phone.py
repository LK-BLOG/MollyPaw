"""MollyPaw — 模拟手机客户端（命令行）。

用途：
  1. **无真机联调**：不用等 Android 工程编译完，就能验证整条链路。
  2. **协议参考实现**：Android 端按这个文件对齐行为（加密、帧、方法调用）。
  3. **CI 夹具**：tests/ 里直接 import 它跑端到端。

支持：
    配对（一键导入配对码） / 加密连接 / 聊天（含流式） / 审批 / 停止
    会话管理 / 配置读写 / 文件浏览下载 / 设备管理 / 二维码生成

用法示例：
    # 生成二维码（PC 端配对用）
    python tools/mp_phone.py qr --code "MP1.xxx.yyy" --out pair.png

    # 连接中继并配对
    python tools/mp_phone.py pair --url ws://127.0.0.1:18767/server --code "MP1.xxx.yyy" \
        --name "小戡的手机"

    # 用已保存的凭据聊天
    python tools/mp_phone.py chat --text "你好" --stream

    # 查看设备/会话/文件
    python tools/mp_phone.py devices
    python tools/mp_phone.py convs
    python tools/mp_phone.py ls "D:\\"

凭据保存在 %APPDATA%\\MollyPaw\\phone.json（或 MOLLYPAW_PHONE_STATE 指定）。
"""
import argparse
import json
import os
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from agent.relay import crypto as C
from agent.relay import protocol as P
from agent.relay.net import prefer_ipv4, proxy_kwargs


def state_path():
    override = os.environ.get("MOLLYPAW_PHONE_STATE")
    if override:
        return override
    base = os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), "MollyPaw"
    )
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "phone.json")


def load_state():
    path = state_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state):
    path = state_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# 手机端实现
# ---------------------------------------------------------------------------


class PhoneClient:
    """一台模拟手机。协议行为与 Android 端保持一致。"""

    def __init__(self, url, psk, dev_id=None, dev_name="模拟手机", role="app",
                 logger=print):
        self.url = url
        self.psk = psk
        self.dev_id = dev_id or str(uuid.uuid4())
        self.dev_name = dev_name
        # role 是**连接声明的角色**，整条连接内不变（AAD 绑定了它）。
        # 服务端授予的真实权限放在 granted_role。
        self.role = role
        self.granted_role = role
        self.logger = logger

        self.ws = None
        self.room = None
        self.key = None
        self.eph_priv = None
        self.eph_pub = None
        self.hs = None
        self.peer_eph = None
        self.peer_hs = None
        self._tx_seq = 0

        # auto=探测系统代理（并发竞速），direct=强制直连。
        # 用来验证"没有代理的用户"到底能不能连。
        self.proxy_mode = "auto"

        self.inbox = []
        self.responses = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        # 连接代号：每次 connect() 递增，旧接收线程靠它退位
        self._generation = 0
        self._gen_lock = threading.RLock()
        self.errors = []

    # -- 连接与握手 --------------------------------------------------------

    def connect(self, room, timeout=20):
        """建立 WS 并发送 hello（携带 eph/hs）。

        重连时必须把上一次的握手状态**全部清掉**：
        早先只换了 eph/hs 却没清 peer_eph / peer_hs / key，导致
          1. wait_key() 看到旧的 key 立刻返回 True（其实还没握手）；
          2. 收到 PC 的 hello 时因为 `peer_eph is None` 为假而跳过，
             不会重新派生密钥；
          3. 结果手机拿**旧密钥**发帧，PC 用新密钥解不开 ——
             现象就是"配对成功、重连也成功，但所有请求超时"。
        """
        import websocket

        # 让上一条连接的接收线程退位（用连接代号隔离，理由同 RelayLink）
        with self._gen_lock:
            self._generation += 1
            my_gen = self._generation

        self.room = room
        full = f"{self.url}?room={room}"
        # 手机端同样要重试：直连 pages.dev 的 TLS 握手实测 7s 甚至超时，
        # 但干扰是概率性的，重试通常能过。真机走系统 ProxySelector，
        # 这里是命令行替身，共用同一套连接逻辑。
        from agent.relay.connect import open_ws

        with prefer_ipv4():
            self.ws = open_ws(full, timeout=8.0, attempts=4,
                              proxy_mode=self.proxy_mode)

        # 全新的握手状态 —— 一个都不能漏
        self.eph_priv, self.eph_pub = C.gen_ephemeral()
        self.hs = os.urandom(C.HS_LEN)
        self.peer_eph = None
        self.peer_hs = None
        self.key = None
        self._tx_seq = 0
        with self._lock:
            self.responses.clear()

        hello = P.hello_frame(self.room, self.role, dev=self.dev_id,
                              ts=int(time.time() * 1000))
        hello["eph"] = C.b64e(self.eph_pub)
        hello["hs"] = C.b64e(self.hs)
        self.ws.send(json.dumps(hello, ensure_ascii=False))

        self._thread = threading.Thread(target=self._loop, args=(my_gen,), daemon=True)
        self._thread.start()
        return self

    def wait_key(self, timeout=10):
        """等会话密钥派生完成（需要收到对方的 hello）。"""
        end = time.time() + timeout
        while time.time() < end:
            if self.key is not None:
                return True
            time.sleep(0.05)
        return False

    def _derive(self):
        if self.role == "pc":
            hs_pc, hs_app = self.hs, self.peer_hs
        else:
            hs_pc, hs_app = self.peer_hs, self.hs
        self.key = C.derive_session_key(
            self.eph_priv, self.peer_eph, self.psk, hs_pc, hs_app
        )

    def _loop(self, generation):
        """接收循环。generation 变了说明已重连，本线程安静退出。

        不加这个判断的话，重连后会有两条线程抢同一个 socket 读帧，
        两边各拿走一半，谁都收不全（现象是"部分响应永远收不到"）。
        """
        while not self._stop.is_set() and generation == self._generation:
            try:
                self.ws.settimeout(0.5)
                raw = self.ws.recv()
            except Exception:
                if self._stop.is_set() or generation != self._generation:
                    break
                continue
            if not raw:
                continue
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            try:
                self._handle(frame)
            except Exception as exc:
                self.errors.append(str(exc))

    def _handle(self, frame):
        t = frame.get("t")
        if t == "error":
            with self._lock:
                self.inbox.append(("__error__", frame))
            return
        if t == "hello":
            if frame.get("f") == self.role:
                return
            if self.peer_eph is None and frame.get("eph"):
                self.peer_eph = C.b64d(frame["eph"])
                self.peer_hs = C.b64d(frame["hs"]) if frame.get("hs") else b""
                self._derive()
            return
        if t == "data":
            if self.key is None:
                return
            payload = C.open_data_frame(self.key, frame)
            if payload.get("ok") is not None:
                with self._lock:
                    self.responses[payload.get("id")] = payload
                return
            with self._lock:
                self.inbox.append((payload.get("m"), payload.get("p")))
            return
        if t in ("presence", "bye", "pong"):
            with self._lock:
                self.inbox.append((t, frame))
            return

    # -- 收发 --------------------------------------------------------------

    def next_seq(self):
        self._tx_seq += 1
        return self._tx_seq

    def call(self, method, params=None, timeout=60):
        """发请求并等响应。返回 (ok, result_or_error)。"""
        if self.key is None:
            return False, "not_ready"
        msg_id = f"{self.dev_id[:8]}-{method}-{uuid.uuid4().hex[:8]}"
        payload = P.payload(method, params, msg_id)
        frame = C.make_data_frame(self.key, self.room, self.role,
                                  self.next_seq(), msg_id, payload)
        self.ws.send(json.dumps(frame, ensure_ascii=False))

        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                if msg_id in self.responses:
                    resp = self.responses.pop(msg_id)
                    return (True, resp.get("r")) if resp.get("ok") else (False, resp.get("e"))
            time.sleep(0.03)
        return False, "timeout"

    def send_event(self, method, params=None):
        """发不需要响应的帧。"""
        if self.key is None:
            return False
        msg_id = uuid.uuid4().hex[:8]
        payload = P.payload(method, params, msg_id)
        frame = C.make_data_frame(self.key, self.room, self.role,
                                  self.next_seq(), msg_id, payload)
        self.ws.send(json.dumps(frame, ensure_ascii=False))
        return True

    def wait_event(self, name, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                for i, (n, p) in enumerate(self.inbox):
                    if n == name:
                        return self.inbox.pop(i)[1]
            time.sleep(0.05)
        return None

    def drain(self):
        with self._lock:
            out = list(self.inbox)
            self.inbox.clear()
            return out

    def close(self):
        self._stop.set()
        try:
            self.ws.close()
        except Exception:
            pass

    # -- 组合动作 ----------------------------------------------------------

    def pair(self, pairing_code, timeout=30):
        """用配对码完成配对，返回设备 token。

        配对码 = MP1.<b64(pair_seed)>.<room>

        手机**不需要事先知道主 PSK**：
          - room、pair_key、reg_token 全部从配对码里拿到
          - 用 pair_key 派生会话密钥 → 能连上、能发 pair.req
          - 服务端在配对响应里把主 PSK 下发回来

        配对成功后必须**换主 PSK 重连**：
        服务端在配对成功的一瞬间就作废了配对密钥（一次性），
        手机要是继续用 pair_key 发请求，服务端解不开 ——
        表现为"配对成功、紧接着所有请求全超时"（实测踩过）。

        另：**不修改 self.role** —— 连接声明什么角色整条连接就是什么角色。
        """
        pair_seed, room = C.parse_pairing_code(pairing_code)
        pair_key = C.derive_pair_key(pair_seed)
        reg_token = C.derive_reg_token(pair_seed)

        # 这次配对会话用 pair_key 当 PSK 使
        original_psk = self.psk
        self.psk = C.b64e(pair_key)
        try:
            self.connect(room)
            if not self.wait_key(timeout=10):
                return False, "handshake_failed"

            dev_pub = os.urandom(32)
            ok, res = self.call("pair.req", {
                "dev_id": self.dev_id,
                "dev_name": self.dev_name,
                "dev_pub": C.b64e(dev_pub),
                "reg_token": C.b64e(reg_token),
            }, timeout=timeout)
            if not ok:
                return False, res

            self.granted_role = res.get("role", "app")
            self.token = res.get("token", "")
            # 服务端把主 PSK 下发了（真一键）；先收下
            new_psk = res.get("psk") or ""
            if new_psk:
                self.main_psk = new_psk
            else:
                # 服务端没给（旧版本），退回调用方传入的 PSK
                self.main_psk = original_psk
            return True, res
        finally:
            # 配对完成后所有通信都用主 PSK
            self.psk = getattr(self, "main_psk", None) or original_psk
        # 注意：重连动作放在调用方（pair_and_reconnect），
        # 因为要在 psk 恢复之后再建新连接。

    def pair_and_reconnect(self, pairing_code, timeout=30):
        """配对 + 自动用主 PSK 重连。返回 (ok, 配对响应)。

        为什么配对完要重连：服务端在配对成功瞬间作废配对密钥，
        继续用旧连接发请求会全部超时（服务端解不开）。
        新连接用主 PSK 派生会话密钥，之后一切正常。
        """
        ok, res = self.pair(pairing_code, timeout=timeout)
        if not ok:
            return False, res
        room = C.derive_room(self.psk)
        try:
            self.close()
        except Exception:
            pass
        time.sleep(0.3)
        self._stop.clear()
        self.connect(room)
        if not self.wait_key(timeout=10):
            return False, "reconnect_failed"
        return True, res

    def auth(self, token, timeout=30):
        """用已保存的 token 认证。同样不改 self.role。"""
        if not self.wait_key(timeout=10):
            return False, "handshake_failed"
        ok, res = self.call("auth.req", {
            "dev_id": self.dev_id,
            "token": token,
            "ts": int(time.time() * 1000),
        }, timeout=timeout)
        if not ok:
            return False, res
        self.granted_role = res.get("role", self.granted_role)
        return True, res

    def chat(self, text, stream=True, timeout=120, on_delta=None):
        """发消息并收流式回复。返回 (ok, 汇总文本)。"""
        ok, res = self.call("chat.send", {"text": text})
        if not ok:
            return False, res

        collected = []
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                pending = list(self.inbox)
            for name, payload in pending:
                if name == "chat.delta":
                    if payload.get("text"):
                        collected.append(payload["text"])
                        if stream:
                            print(payload["text"], end="", flush=True)
                        if on_delta:
                            on_delta(payload)
                    if payload.get("done"):
                        with self._lock:
                            try:
                                self.inbox.remove((name, payload))
                            except ValueError:
                                pass
                        if stream:
                            print()
                        return True, "".join(collected)
                if name == "chat.tool_call":
                    if stream:
                        print(f"\n  [工具] {payload.get('name')} {payload.get('args')}")
                        if on_delta:
                            on_delta(payload)
                if name == "approval.request":
                    if on_delta:
                        on_delta(payload)
            time.sleep(0.05)
        return False, "timeout"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_qr(args):
    """生成配对码的二维码 PNG。"""
    from agent.relay import qr as qr_mod

    png = qr_mod.make_png(args.code, scale=args.scale)
    out = args.out or "pairing.png"
    with open(out, "wb") as f:
        f.write(png)
    print(f"已生成二维码: {out}（{len(png)} 字节）")
    print(f"内容长度: {len(args.code)} 字符")
    return 0


def cmd_pair(args):
    """配对：只给配对码即可，主 PSK 由服务端在配对响应里下发。"""
    state = load_state()
    client = PhoneClient(args.url, args.psk or "", dev_id=state.get("dev_id"),
                         dev_name=args.name)
    print(f"连接: {args.url}")
    ok, res = client.pair_and_reconnect(args.code)
    if not ok:
        print(f"配对失败: {res}")
        return 1

    # 主 PSK 由服务端下发（真一键）；也允许命令行显式覆盖
    psk = getattr(client, "main_psk", "") or args.psk or ""
    state.update({
        "dev_id": client.dev_id,
        "name": args.name,
        "url": args.url,
        "psk": psk,
        "token": res.get("token", ""),
        "role": res.get("role", "app"),
    })
    if args.psk:
        state["psk"] = args.psk
    save_state(state)
    print(f"配对成功：角色={res.get('role')}")
    print(f"主密钥已{( '由服务端下发' if res.get('psk') else '取自命令行')}，"
          f"凭据已保存到 {state_path()}")
    print("接下来可以直接用 chat / devices / convs 等子命令，无需再填密钥。")
    client.close()
    return 0


def _connect_saved(args):
    """用已保存凭据连上并认证。返回 client 或 None。"""
    state = load_state()
    if not state.get("token"):
        print("还没有配对过，先跑 pair 子命令")
        return None
    url = args.url or state.get("url")
    psk = args.psk or state.get("psk")
    if not url or not psk:
        print("凭据不完整（缺 url 或 psk）")
        return None

    from agent.relay import crypto as _c

    room = _c.derive_room(psk)
    client = PhoneClient(url, psk, dev_id=state["dev_id"],
                         dev_name=state.get("name", "模拟手机"))
    client.connect(room)
    if not client.wait_key(timeout=10):
        print("握手超时（PC 端是否开着远程互联？）")
        client.close()
        return None
    ok, res = client.auth(state["token"])
    if not ok:
        print(f"认证失败: {res}")
        client.close()
        return None
    print(f"已连接（角色 {res.get('role')}）")
    return client


def cmd_chat(args):
    client = _connect_saved(args)
    if not client:
        return 1
    try:
        ok, text = client.chat(args.text, stream=True)
        if not ok:
            print(f"\n失败: {text}")
            return 1
        if not args.stream:
            print(text)
        return 0
    finally:
        client.close()


def cmd_devices(args):
    client = _connect_saved(args)
    if not client:
        return 1
    try:
        ok, res = client.call("device.list")
        if not ok:
            print(f"失败: {res}")
            return 1
        for d in res.get("devices", []):
            role = "控制端" if d.get("role") == "app" else "只读端"
            flag = "（已吊销）" if d.get("revoked") else ""
            print(f"  {d.get('name')}  {role}  {d.get('dev_id')[:8]}  {flag}")
        return 0
    finally:
        client.close()


def cmd_convs(args):
    client = _connect_saved(args)
    if not client:
        return 1
    try:
        ok, res = client.call("conv.list")
        if not ok:
            print(f"失败: {res}")
            return 1
        for c in res.get("conversations", []):
            print(f"  {c.get('id','')[:8]}  {c.get('title') or '(未命名)'}")
        return 0
    finally:
        client.close()


def cmd_ls(args):
    client = _connect_saved(args)
    if not client:
        return 1
    try:
        ok, res = client.call("fs.list", {"path": args.path})
        if not ok:
            print(f"失败: {res}")
            return 1
        print(f"目录: {res.get('path')}")
        for e in res.get("entries", []):
            kind = "DIR " if e.get("is_dir") else "    "
            print(f"  {kind}{e.get('size',0):>10}  {e.get('name')}")
        return 0
    finally:
        client.close()


def cmd_download(args):
    import base64

    client = _connect_saved(args)
    if not client:
        return 1
    try:
        collected = b""
        offset = 0
        while True:
            ok, res = client.call("fs.read", {"path": args.path, "offset": offset})
            if not ok:
                print(f"失败: {res}")
                return 1
            chunk = base64.b64decode(res["data_b64"])
            collected += chunk
            offset += len(chunk)
            if res.get("eof") or not chunk:
                break
        with open(args.out, "wb") as f:
            f.write(collected)
        print(f"已下载 {len(collected)} 字节 -> {args.out}")
        return 0
    finally:
        client.close()


def cmd_approve(args):
    """列出待审批并可选批准/拒绝。"""
    client = _connect_saved(args)
    if not client:
        return 1
    try:
        ok, res = client.call("approval.list")
        if not ok:
            print(f"失败: {res}")
            return 1
        pending = res.get("pending", [])
        if not pending:
            print("没有待审批")
            return 0
        for item in pending:
            print(f"  {item['request_id'][:8]}  {item['name']}  {item.get('args')}")
        if args.approve or args.reject:
            target = pending[0]
            ok, res2 = client.call("approval.reply", {
                "req_id": target["request_id"],
                "approved": bool(args.approve),
            })
            print(f"审批结果: {'已批准' if args.approve else '已拒绝'} ({ok})")
        return 0
    finally:
        client.close()


def cmd_stop(args):
    client = _connect_saved(args)
    if not client:
        return 1
    try:
        ok, res = client.call("chat.stop")
        print(f"停止: {res}")
        return 0
    finally:
        client.close()


def cmd_status(args):
    client = _connect_saved(args)
    if not client:
        return 1
    try:
        ok, res = client.call("status.get")
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description="MollyPaw 模拟手机客户端")
    parser.add_argument("--url", help="中继地址，如 ws://127.0.0.1:18767/server")
    parser.add_argument("--psk", help="预共享密钥")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_qr = sub.add_parser("qr", help="把配对码画成二维码")
    p_qr.add_argument("--code", required=True)
    p_qr.add_argument("--out", default="pairing.png")
    p_qr.add_argument("--scale", type=int, default=8)
    p_qr.set_defaults(func=cmd_qr)

    p_pair = sub.add_parser("pair", help="用配对码配对")
    p_pair.add_argument("--code", required=True)
    p_pair.add_argument("--name", default="模拟手机")
    p_pair.set_defaults(func=cmd_pair)

    p_chat = sub.add_parser("chat", help="发消息")
    p_chat.add_argument("--text", required=True)
    p_chat.add_argument("--stream", action="store_true", default=True)
    p_chat.add_argument("--no-stream", dest="stream", action="store_false")
    p_chat.set_defaults(func=cmd_chat)

    sub.add_parser("devices", help="列出已配对设备").set_defaults(func=cmd_devices)
    sub.add_parser("convs", help="列出会话").set_defaults(func=cmd_convs)
    sub.add_parser("status", help="查看状态").set_defaults(func=cmd_status)

    p_ls = sub.add_parser("ls", help="列目录")
    p_ls.add_argument("path", nargs="?", default=".")
    p_ls.set_defaults(func=cmd_ls)

    p_dl = sub.add_parser("download", help="下载文件")
    p_dl.add_argument("path")
    p_dl.add_argument("out")
    p_dl.set_defaults(func=cmd_download)

    p_ap = sub.add_parser("approve", help="列出/处理待审批")
    p_ap.add_argument("--approve", action="store_true")
    p_ap.add_argument("--reject", action="store_true")
    p_ap.set_defaults(func=cmd_approve)

    sub.add_parser("stop", help="停止当前一轮").set_defaults(func=cmd_stop)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
