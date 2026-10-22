"""MollyPaw Relay — PC 端 WebSocket 客户端。

职责：
  - 拨号到中继（或本地 /ws）
  - 与对端交换 eph/hs（靠中继转发 hello，见 PROTOCOL.md §3.1）
  - 派生会话密钥、加解密 data 帧
  - 心跳、断线重连（指数退避 + 抖动）、rekey
  - 把解出的载荷交给 bridge 处理，把 bridge 产生的事件加密发出去

它**不懂业务**：不认 chat / config / fs，那些在 bridge.py。
这样这个文件可以单独测（假的 bridge 塞进去就能跑）。
"""
import json
import os
import random
import threading
import time

from agent.relay import crypto as C
from agent.relay import protocol as P
from agent.relay.net import prefer_ipv4


class RelayLink:
    """与中继的一条连接。"""

    def __init__(self, url, room, role, psk, dev_id=None, hello_extra=None,
                 on_payload=None, on_state=None, logger=None, on_new_peer=None):
        """
        url          中继地址，如 wss://mollypaw-online.pages.dev/server
        room         32 位 hex
        role         "pc" / "app" / "observer"
        psk          预共享密钥（明文）
        on_payload(method, params, msg_id, role, dev)   收到业务载荷
        on_state(state, info)                              连接状态变化回调
        """
        self.url = url
        self.room = room
        self.role = role
        self.psk = psk
        self.dev_id = dev_id
        self.hello_extra = dict(hello_extra or {})
        self.on_payload = on_payload
        self.on_state = on_state
        self.on_new_peer = on_new_peer
        self.logger = logger

        self.ws = None
        self._ws_lock = threading.RLock()

        # 握手材料
        self.eph_priv = None
        self.eph_pub = None
        self.hs = None
        self.peer_eph = None
        self.peer_hs = None
        self.session_key = None
        self._key_ready = threading.Event()
        # 多对端：一个房间可以有控制端 + 只读端多台手机。
        # peer_id -> {"eph", "hs", "role", "key"}
        self._peers = {}
        self._peers_lock = threading.RLock()
        # 请求 id -> 发起该请求的 peer_id（响应要发回给同一台）
        self._pending_peers = {}
        # 配对期间的专用密钥：peer_id -> 用 pair_key 派生的会话密钥。
        # 配对码是一次性的，配对完成后由 clear_pairing_keys() 清掉。
        self._pairing_keys = {}

        # 出站序号（自己方向的）
        self._tx_seq = 0
        self._seq_lock = threading.Lock()

        # rekey：旧密钥保留 3 秒
        self._prev_key = None
        self._prev_key_until = 0.0

        self._stop = threading.Event()
        self._recv_thread = None
        self._hb_thread = None
        # 连接代号：每次 connect() 递增，旧接收线程靠它自然退位
        self._generation = 0
        self._gen_lock = threading.RLock()
        self._connected = False
        self.connected_at = 0.0
        self.reconnect_attempts = 0

    # -- 工具 --------------------------------------------------------------

    def _log(self, msg):
        if self.logger:
            try:
                self.logger(msg)
            except Exception:
                pass

    def _state(self, state, **info):
        """更新连接状态。

        只有明确"断开"类的状态才把 _connected 置 False。
        早先的写法是 `_connected = (state == "connected")`，结果
        握手完成时发出的 "ready" 会把标志打回 False，
        run_forever 里的等待循环立刻以为掉线了，开始疯狂重连 —— 连接永远活不过一秒。
        """
        if state in ("disconnected", "closed", "error"):
            self._connected = False
        elif state in ("connected", "ready"):
            self._connected = True
        # presence / reconnecting / bye 不改变连接存活判定
        if self.on_state:
            try:
                self.on_state(state, info)
            except Exception:
                pass

    def next_seq(self) -> int:
        with self._seq_lock:
            self._tx_seq += 1
            return self._tx_seq

    # -- 连接 --------------------------------------------------------------

    def connect(self, timeout=20):
        """建立一条连接并完成握手。成功返回 True。"""
        import websocket

        full = f"{self.url}?room={self.room}" if "?" not in self.url else \
               f"{self.url}&room={self.room}"

        # 先让上一个接收线程退位。
        # 这里不能用 self._stop：那个事件是"整个客户端停掉"的全局标志，
        # 重连时会被 clear()，于是旧线程也跟着复活，两个线程抢同一个 socket
        # 读帧 —— 帧被瓜分，谁都收不全（表现为重连后所有响应超时）。
        # 用「连接代号」隔离：代号变了旧线程自己退出。
        with self._gen_lock:
            self._generation += 1
            my_gen = self._generation

        # 每次连接都用新的临时密钥对 —— 前向保密
        self.eph_priv, self.eph_pub = C.gen_ephemeral()
        self.hs = os.urandom(C.HS_LEN)
        self.peer_eph = None
        self.peer_hs = None
        self.session_key = None
        with self._peers_lock:
            self._peers = {}
            self._pairing_keys = {}
        self._key_ready.clear()

        base = dict(self.hello_extra)
        frame = P.hello_frame(
            self.room, self.role,
            dev=self.dev_id,
            ts=int(time.time() * 1000),
        )
        frame["eph"] = C.b64e(self.eph_pub)
        frame["hs"] = C.b64e(self.hs)
        frame.update({k: v for k, v in base.items() if k not in frame})

        with prefer_ipv4():
            ws = websocket.create_connection(full, timeout=timeout)
        with self._ws_lock:
            self.ws = ws
        self.connected_at = time.time()
        self.reconnect_attempts = 0

        self._send_raw(frame)
        self._state("connected")

        self._recv_thread = threading.Thread(
            target=self._recv_loop, args=(my_gen,),
            name=f"relay-recv-{self.role}", daemon=True,
        )
        self._recv_thread.start()
        return True

    def _send_raw(self, frame):
        text = json.dumps(frame, ensure_ascii=False)
        with self._ws_lock:
            ws = self.ws
        if ws is None:
            return False
        try:
            ws.send(text)
            return True
        except Exception:
            return False

    def _key_for_peer(self, peer_id):
        """取指定对端的密钥；找不到就退回当前密钥。"""
        if peer_id is not None:
            with self._peers_lock:
                peer = self._peers.get(peer_id)
                if peer and peer.get("key"):
                    return peer["key"]
        return self.session_key

    def send_payload(self, method, params=None, msg_id=None, peer_id=None, key=None):
        """加密发送一个业务载荷。

        key 优先：指定了就用它（响应场景下必须是解开请求的那把）。
        peer_id 次之；都没有则用当前/最近的对端密钥。
        """
        if key is None:
            key = self._key_for_peer(peer_id)
        if key is None:
            raise RuntimeError("session key not ready")
        seq = self.next_seq()
        payload = P.payload(method, params, msg_id)
        frame = C.make_data_frame(
            key, self.room, self.role, seq,
            msg_id or f"{self.role}-{seq}", payload,
        )
        return self._send_raw(frame)

    def send_response(self, method, msg_id, ok=True, result=None, error=None,
                      peer_id=None):
        """回响应。

        peer_id 不传时，自动查「这个请求是用哪把钥匙解开的」并用**同一把**
        加密。多设备 / 配对场景下用错钥匙对方根本解不开，
        表现为「服务端处理成功、客户端却超时」。
        """
        key = None
        if msg_id:
            with self._peers_lock:
                entry = self._pending_peers.pop(msg_id, None)
            if isinstance(entry, tuple):
                saved_peer, saved_key = entry
                key = saved_key
                if peer_id is None:
                    peer_id = saved_peer
            elif entry is not None:
                # 兼容旧格式（只存了 peer_id）
                if peer_id is None:
                    peer_id = entry
        if key is None:
            key = self._key_for_peer(peer_id)
        if key is None:
            return False
        seq = self.next_seq()
        payload = P.payload(method, msg_id=msg_id, is_response=True,
                            ok=ok, error=error, result=result)
        frame = C.make_data_frame(
            key, self.room, self.role, seq,
            msg_id or f"{self.role}-{seq}", payload,
        )
        return self._send_raw(frame)

    def send_event(self, method, params=None, peer_id=None):
        """推送事件（无请求配对）。不传 peer_id 就是广播给所有设备。"""
        if peer_id is not None:
            return self.send_payload(method, params, peer_id=peer_id)
        # 广播：每台设备各发一份（各自用各自密钥）
        sent = False
        with self._peers_lock:
            peers = [(pid, p) for pid, p in self._peers.items() if p.get("key")]
        if not peers:
            return self.send_payload(method, params)
        for pid, _peer in peers:
            try:
                sent = self.send_payload(method, params, peer_id=pid) or sent
            except Exception:
                pass
        return sent

    # -- 接收 --------------------------------------------------------------

    def _recv_loop(self, generation):
        """接收循环。

        generation 是建立这条连接时的代号。代号变了说明上层已经重连，
        本线程必须安静退出 —— 否则会和新的接收线程抢同一个 socket，
        两边各读走一半的帧，谁都不完整（表现为"重连后一直超时"）。
        """
        while not self._stop.is_set() and generation == self._generation:
            with self._ws_lock:
                ws = self.ws
            if ws is None:
                break
            try:
                raw = ws.recv()
            except Exception as exc:
                if not self._stop.is_set() and generation == self._generation:
                    self._log(f"relay recv ended: {exc}")
                break
            if not raw:
                continue
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            try:
                self._handle_frame(frame)
            except Exception as exc:
                self._log(f"relay frame error: {exc}")

        # 只有仍属当前代号时才汇报断线，避免旧线程把新连接标成断开
        if not self._stop.is_set() and generation == self._generation:
            self._state("disconnected")

    def _handle_frame(self, frame):
        ftype = frame.get("t")

        if ftype == "error":
            code = frame.get("code")
            self._log(f"relay error: {code} {frame.get('msg','')}")
            if code in ("offline", "role_taken", "version"):
                self._state("error", code=code, msg=frame.get("msg", ""))
            return

        if ftype == "presence":
            self._state("presence", **{
                k: frame.get(k) for k in ("pc", "app", "observer") if k in frame
            })
            return

        if ftype == "bye":
            self._state("bye", reason=frame.get("reason", ""))
            return

        if ftype == "ping":
            self._send_raw(P.pong_frame(self.room, self.role, int(time.time() * 1000)))
            return

        if ftype == "pong":
            return

        if ftype == "hello":
            # 对端的握手材料（中继转发过来的）。
            #
            # 一个房间可以有多台手机同时连（控制端 + 只读端），
            # 所以必须**按设备**保存 eph/hs，不能只留一份 ——
            # 早先只存 self.peer_eph，第二台手机一连就把第一台的密钥挤掉，
            # 先连的那台之后所有帧都解不开（表现为收不到任何回复）。
            if frame.get("f") == self.role and frame.get("dev") == self.dev_id:
                return  # 自己的 hello 被回放回来了
            peer_id = frame.get("dev") or frame.get("f")
            if not frame.get("eph") or not frame.get("hs"):
                return
            new_eph = C.b64d(frame["eph"])
            new_hs = C.b64d(frame["hs"])
            existing = self._peers.get(peer_id)
            if existing and existing.get("eph") == new_eph and existing.get("hs") == new_hs:
                return  # 同一对端、同一临时密钥 —— 是回放，不重算
            # 设备重连时会换新的临时密钥对（eph/hs 都变），必须**重新派生**。
            #
            # 这里判断的依据是 eph/hs 是否变化，而不是"dev_id 是否见过"：
            # 手机重连后 dev_id 不变、eph 变了，用 dev_id 判重会把新 hello
            # 当成重复回放丢掉，PC 于是继续拿旧密钥解新帧 ——
            # 现象就是"配对成功、重连也成功，但所有业务请求超时"。
            # 实测量到过：PC 端 _peers 里那台设备的 key 一直是旧的。
            self._peers[peer_id] = {
                "eph": new_eph,
                "hs": new_hs,
                "role": frame.get("f"),
                "key": None,
            }
            self._derive_peer_key(peer_id)
            # 通知上层「有个新对端来了」。
            # 配对场景下上层会拿配对码里的 pair_key 再派生一把钥匙 ——
            # 手机配对时用的是 pair_key 而不是主 PSK，不派这把就解不开它。
            if self.on_new_peer:
                try:
                    self.on_new_peer(peer_id)
                except Exception as exc:
                    self._log(f"on_new_peer failed: {exc}")
            return

        if ftype == "data":
            self._handle_data(frame)
            return

    def _derive_peer_key(self, peer_id):
        """为某个对端派生会话密钥。"""
        peer = self._peers.get(peer_id)
        if not peer or not peer.get("eph") or not peer.get("hs"):
            return None
        # salt 顺序固定 hs_pc ‖ hs_app
        if self.role == "pc":
            hs_pc, hs_app = self.hs, peer["hs"]
        else:
            hs_pc, hs_app = peer["hs"], self.hs

        key = C.derive_session_key(
            self.eph_priv, peer["eph"], self.psk, hs_pc, hs_app
        )
        peer["key"] = key

        # 兼容旧路径：把「最近一个对端」的密钥也放到 self.session_key，
        # 单设备场景下 _key_ready / send_payload 仍然照旧工作。
        self.session_key = key
        self.peer_eph = peer["eph"]
        self.peer_hs = peer["hs"]
        if not self._key_ready.is_set():
            self._key_ready.set()
            self._state("ready")
            self._log(f"session key established with {peer_id}")
        return key

    def _keys_for(self, frame):
        """按发送方挑出可能能解开这帧的密钥。返回 [(peer_id, key), ...]。

        注意：data 帧里**没有 dev 字段**（只有 hello 才有），所以不能按
        明文设备号挑密钥。这里按角色粗筛，最后由 AAD 校验决定成败 ——
        AAD 绑定了发送方角色，冒充角色的帧任何密钥都解不开。
        """
        sender = frame.get("f")
        pairs = []
        with self._peers_lock:
            for peer_id, peer in self._peers.items():
                if peer.get("key") and peer.get("role") == sender:
                    pairs.append((peer_id, peer["key"]))
            # 配对期间的专用密钥也要参与尝试（手机此时用的是 pair_key）
            for peer_id, key in self._pairing_keys.items():
                if not any(k == key for _, k in pairs):
                    pairs.append((peer_id, key))
        # 兜上当前密钥与上一轮密钥（rekey 宽限），找不到 peer 时也算
        if self.session_key is not None:
            if not any(k == self.session_key for _, k in pairs):
                pairs.append((self._current_peer_id(), self.session_key))
        if self._prev_key is not None and time.time() < self._prev_key_until:
            if not any(k == self._prev_key for _, k in pairs):
                pairs.append((None, self._prev_key))
        return pairs

    def _current_peer_id(self):
        """最近一次派生密钥的对端（单设备场景就是它）。"""
        with self._peers_lock:
            for peer_id, peer in self._peers.items():
                if peer.get("key") == self.session_key:
                    return peer_id
        return None

    def _handle_data(self, frame):
        """解密 data 帧。多对端时逐个尝试，**记录是哪台设备的密钥解开的**。

        这一点很关键：PC 要给「发请求的那台手机」回响应，
        用别的手机的密钥加密，对方根本解不开（也就表现为超时）。
        """
        pairs = self._keys_for(frame)

        payload = None
        last_error = None
        matched_peer = None
        matched_key = None
        for peer_id, key in pairs:
            try:
                payload = C.open_data_frame(key, frame)
                matched_peer = peer_id
                matched_key = key
                break
            except Exception as exc:
                last_error = exc

        if payload is None:
            self._log(f"cannot decrypt frame (seq={frame.get('seq')}): {last_error}")
            return

        method = payload.get("m", "")
        params = payload.get("p")
        msg_id = payload.get("id")

        # 记住「这个请求是用哪把钥匙解开的」，响应必须用同一把加密。
        # 只记 peer_id 是不够的：配对场景下解开请求的是 pair_key 派生的
        # 那把，而 _peers[peer_id].key 是主 PSK 派生的 —— 用错了对方解不开，
        # 表现为「服务端明明处理成功、客户端却一直超时」。
        if msg_id:
            with self._peers_lock:
                self._pending_peers[msg_id] = (matched_peer, matched_key)

        # rekey 由 pc 发起
        if method == "rekey.offer" and self.role != "pc":
            self._handle_rekey_offer(payload)
            return
        if method == "rekey.accept" and self.role == "pc":
            self._handle_rekey_accept(payload)
            return

        if payload.get("ok") is not None:
            if self.on_payload:
                self.on_payload("__response__", payload, msg_id,
                                frame.get("f"), matched_peer)
            return

        if self.on_payload:
            self.on_payload(method, params, msg_id, frame.get("f"), matched_peer)

    # -- 配对期间的额外密钥 -------------------------------------------------

    def derive_for_pairing(self, peer_id, pair_key_b64):
        """用配对码里的 pair_key 给某个对端派生一把会话密钥。

        为什么需要：配对时手机用 **pair_key**（配对码里的那段随机数）
        当 PSK 来派生会话密钥，而不是用主 PSK。
        所以 PC 端也要按同一段材料派生一次，否则解不开手机的 pair.req。

        配对成功后这段密钥就该作废（配对码是一次性的），
        由 clear_pairing_keys() 清掉。
        """
        with self._peers_lock:
            peer = self._peers.get(peer_id)
        if not peer:
            return False
        eph = peer.get("eph")
        hs = peer.get("hs")
        if not eph or not hs:
            return False

        if self.role == "pc":
            hs_pc, hs_app = self.hs, hs
        else:
            hs_pc, hs_app = hs, self.hs
        try:
            key = C.derive_session_key(self.eph_priv, eph, pair_key_b64, hs_pc, hs_app)
        except Exception:
            return False
        with self._peers_lock:
            self._pairing_keys[peer_id] = key
        return True

    def clear_pairing_keys(self):
        with self._peers_lock:
            self._pairing_keys.clear()


# -- rekey ------------------------------------------------------------

    def maybe_rekey(self):
        """到达阈值就发起 rekey（只有 pc 调）。"""
        if self.role != "pc" or self.session_key is None:
            return False
        need = (
            self._tx_seq >= C.REKEY_FRAMES
            or (time.time() - self.connected_at) >= C.REKEY_SECONDS
        )
        if not need:
            return False
        new_priv, new_pub = C.gen_ephemeral()
        self._rekey_pending_priv = new_priv
        self._rekey_pending_hs = os.urandom(C.HS_LEN)
        self.send_event("rekey.offer", {
            "eph": C.b64e(new_pub),
            "hs": C.b64e(self._rekey_pending_hs),
        })
        # 重置计数，避免每帧都触发
        with self._seq_lock:
            self._tx_seq = 0
        self.connected_at = time.time()
        return True

    def _handle_rekey_offer(self, payload):
        params = payload.get("p") or {}
        try:
            peer_eph = C.b64d(params["eph"])
            peer_hs = C.b64d(params["hs"])
        except Exception:
            return
        my_priv, my_pub = C.gen_ephemeral()
        my_hs = os.urandom(C.HS_LEN)
        # pc 是发起方，salt 顺序 pc 在前
        new_key = C.derive_session_key(
            my_priv, peer_eph, self.psk, peer_hs, my_hs
        )
        self._apply_rekey(new_key)
        self.send_response("rekey.accept", payload.get("id"), True, {
            "eph": C.b64e(my_pub),
            "hs": C.b64e(my_hs),
        })

    def _handle_rekey_accept(self, payload):
        params = payload.get("p") or {}
        try:
            peer_eph = C.b64d(params["eph"])
            peer_hs = C.b64d(params["hs"])
        except Exception:
            return
        new_key = C.derive_session_key(
            self._rekey_pending_priv, peer_eph, self.psk,
            self._rekey_pending_hs, peer_hs,
        )
        self._apply_rekey(new_key)

    def _apply_rekey(self, new_key):
        """新密钥生效，旧密钥再容忍 3 秒。"""
        self._prev_key = self.session_key
        self._prev_key_until = time.time() + C.REKEY_GRACE_SECONDS
        self.session_key = new_key
        self._log("rekeyed")

    # -- 心跳与关闭 --------------------------------------------------------

    def start_heartbeat(self):
        if self._hb_thread and self._hb_thread.is_alive():
            return
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop, name=f"relay-hb-{self.role}", daemon=True
        )
        self._hb_thread.start()

    def _heartbeat_loop(self):
        while not self._stop.is_set():
            self._stop.wait(C.HEARTBEAT_SECONDS)
            if self._stop.is_set():
                break
            try:
                self._send_raw(P.ping_frame(self.room, self.role, int(time.time() * 1000)))
                self.maybe_rekey()
            except Exception:
                pass

    def close(self, reason="shutdown"):
        self._stop.set()
        with self._ws_lock:
            ws = self.ws
            self.ws = None
        if ws is not None:
            try:
                ws.send(json.dumps(P.bye_frame(self.room, self.role, reason)))
            except Exception:
                pass
            try:
                ws.close()
            except Exception:
                pass
        self._state("closed")

    # -- 重连 --------------------------------------------------------------

    def run_forever(self, should_stop):
        """带指数退避的重连循环，直到 should_stop() 为真。

        退避：1,2,4,8,16,30,30…，带 ±20% 抖动（避免多设备同时重连打爆中继）。
        """
        while not should_stop():
            try:
                self.connect()
                self.start_heartbeat()
                # 等连接断掉
                while not self._stop.is_set() and not should_stop():
                    if not self._connected:
                        break
                    time.sleep(0.5)
                if should_stop():
                    break
            except Exception as exc:
                self._log(f"relay connect failed: {exc}")

            if should_stop():
                break
            delay = min(30, 2 ** min(self.reconnect_attempts, 5))
            delay *= 1 + random.uniform(-0.2, 0.2)
            self.reconnect_attempts += 1
            self._state("reconnecting", delay=round(delay, 1))
            # 用可中断的等待，别让关闭卡住
            end = time.time() + delay
            while time.time() < end and not should_stop():
                time.sleep(0.2)

        self.close("stopped")
