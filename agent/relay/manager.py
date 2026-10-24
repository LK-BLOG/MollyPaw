"""MollyPaw Relay — 总装配。

把 client / bridge / controller / devices 拼成一个可启停的整体，
对外只暴露 start() / stop() / status() / 配对管理。

main.py 只需要持有这个对象。
"""
import json
import os
import threading
import time

from agent.relay import crypto as C
from agent.relay import protocol as P
from agent.relay.bridge import RelayBridge
from agent.relay.client import RelayLink
from agent.relay.controller import RelayController
from agent.relay.devices import DeviceStore

DEFAULT_RELAY_URL = "wss://mollypaw-online.pages.dev/server"
LOCAL_RELAY_URL = "ws://127.0.0.1:18766/ws"

CONFIG_KEY = "relay"


class RelayManager:
    """一台电脑的远程互联会话。"""

    def __init__(self, service, config=None, logger=None, config_saver=None):
        self.service = service
        self.logger = logger
        self.config_saver = config_saver
        self.config = dict(config or {})

        self.devices = DeviceStore()
        # 复用 service 已有的控制器，而不是再造一个。
        #
        # 为什么必须复用：单飞锁、取消令牌、待决审批表都挂在 controller 上。
        # 造两个的话，本地 UI 和手机会各持一把锁 ——
        # 手机点停止停不掉电脑上的那一轮，两边还能同时跑两轮 agent。
        # service 现在保证 controller 一定存在（见 MollyPawService.__init__）。
        self.controller = getattr(service, "controller", None) or RelayController(
            broadcast=self._broadcast_controller,
            logger=logger,
        )
        # 控制器要把事件广播出去（远程侧）；本地侧的事件走 service 自己的队列
        if getattr(self.controller, "broadcast", None) is None:
            self.controller.broadcast = self._broadcast_controller
        self.bridge = RelayBridge(
            service, self.controller, devices=self.devices, logger=logger
        )
        self.bridge.bind_senders(self._send_to_all, self._send_to_role)
        # 配对成功后要把主 PSK 下发给手机（否则手机没密钥可用，后续全超时）
        self.bridge.psk_provider = lambda: self.config.get("psk") or ""

        # 事件从 service 流到 bridge（tool_call / approval 等）。
        # service 可能是替身对象（测试里用过），没有 add_event_sink 就跳过 ——
        # 硬调会炸 AttributeError，而中继本身不依赖事件通道也能工作。
        if hasattr(self.service, "add_event_sink"):
            self.service.add_event_sink(self._service_event_sink)

        self.link = None
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._state = "stopped"
        self._state_info = {}
        self._links = {}          # session_id -> RelayLink（本机只开一条 pc 连接）

    # -- 日志 --------------------------------------------------------------

    def _log(self, msg):
        if self.logger:
            try:
                self.logger(f"[relay] {msg}")
            except Exception:
                pass

    # -- 生命周期 ----------------------------------------------------------

    @property
    def running(self):
        """是否处于"已启用"状态。

        判据是 _stop 标志而不是线程存活：
        线程可能因为短暂重连而"活着但没连上"，那是 running=True + state=reconnecting；
        而用户点了关闭之后必须是 False —— 早先只看线程存活，
        stop() 之后线程还有一瞬没退，前端就看到"处理中"卡住了。
        """
        with self._lock:
            if self._stop.is_set():
                return False
            return self._thread is not None and self._thread.is_alive()

    @property
    def state(self):
        with self._lock:
            return self._state

    def start(self):
        """启动（或重启）中继连接。返回状态 dict。"""
        with self._lock:
            if self.running:
                return self.status()

        psk = self.config.get("psk") or ""
        problems = C.psk_problems(psk)
        if problems:
            self._set_state("error", reason="bad_key", detail=problems)
            return self.status()

        url = self.config.get("url") or DEFAULT_RELAY_URL
        room = C.derive_room(psk)

        self._stop.clear()
        link = RelayLink(
            url=url,
            room=room,
            role=P.ROLE_PC,
            psk=psk,
            dev_id=self.config.get("dev_id") or "pc",
            on_payload=self._on_payload,
            on_state=self._on_link_state,
            on_new_peer=self._on_new_peer,
            logger=self._log,
            # auto = 自动探测系统代理（Windows 注册表 / 环境变量）。
            # 不传这个桌面端就裸连，TLS 握手实测 7s 甚至超时，
            # 表现是"一直重连中"、手机永远等不到 PC 的 hello。
            proxy=self.config.get("proxy", "auto"),
        )
        with self._lock:
            self.link = link
            self._links["pc"] = link
        self._set_state("starting")

        self._thread = threading.Thread(
            target=link.run_forever, args=(self._stop.is_set,),
            name="relay-manager", daemon=True,
        )
        self._thread.start()
        return self.status()

    def stop(self):
        """停掉中继连接。

        注意必须把 self._thread 也清掉：running 是看 _thread 是否活的，
        只清 link 不清 thread 的话，stop() 之后 running 仍然为 True ——
        前端会一直停在"处理中..."，表现为按钮卡死。
        """
        self._stop.set()
        with self._lock:
            link = self.link
        if link is not None:
            link.close("user stopped relay")
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        with self._lock:
            self.link = None
            self._thread = None
            self._links.clear()
        self._set_state("stopped")
        # 连接全断，把挂着等审批的一律当拒绝放掉，别让 agent 线程悬着
        self.controller.cancel_all_approvals()
        return self.status()

    def restart(self):
        self.stop()
        time.sleep(0.2)
        return self.start()

    # -- 状态 --------------------------------------------------------------

    def _set_state(self, state, **info):
        with self._lock:
            self._state = state
            self._state_info = info
        self._log(f"state -> {state} {info or ''}")

    def _on_link_state(self, state, info):
        if state == "ready":
            self._set_state("connected", room=self.link.room if self.link else "")
            # 连上就把待决审批补推一次，重连的手机能立刻看到
            for item in self.controller.list_approvals():
                self._send_to_all("approval.request", item)
        elif state == "reconnecting":
            self._set_state("reconnecting", **info)
        elif state == "disconnected":
            self._set_state("disconnected")
        elif state == "connected":
            # WS 建好即视为连上。
            #
            # 重要：**不能**等到 session_key 才认为连接成功 ——
            # PC 单独在线时房间里没有别人，没有 hello 可交换，
            # 自然不会派生会话密钥（密钥只在有设备接进来时才需要）。
            # 早先把「有 session_key」当成连上的判据，结果 PC 永远显示
            # "重连中"，而实际 WS 早就通了（实测量到 connected=True、key=无）。
            self._set_state("connected", room=self.link.room if self.link else "")
        elif state == "error":
            self._set_state("error", **info)
        elif state == "presence":
            with self._lock:
                self._state_info = {**self._state_info, **info}

    def _broadcast_controller(self, method, params):
        self._send_to_all(method, params)

    def _on_new_peer(self, peer_id):
        """有个新对端（手机）接进来了。

        如果此刻正好有一个待认领的配对码，就用码里的 pair_key 派生一把
        解密用密钥 —— 手机配对时用的是 pair_key 而不是主 PSK。
        否则手机发来的 pair.req 我们根本解不开（表现为配对超时）。
        """
        session = self.devices.current_pairing()
        if session is None:
            return
        link = self.link
        if link is None:
            return
        ok = link.derive_for_pairing(peer_id, C.b64e(session.pair_key))
        if ok:
            self._log(f"derived pairing key for {peer_id}")

    def _service_event_sink(self, name, payload):
        """service 的事件 -> 远程事件（翻译命名）。"""
        if name == "_onToolCall":
            self._send_to_all("chat.tool_call", payload)
        elif name == "_onToolResult":
            self._send_to_all("chat.tool_result", payload)
        elif name == "_onApprovalRequest":
            pass  # 审批走 controller.add_approval，不重复发
        """service 的事件 -> 远程事件（翻译命名）。"""
        if name == "_onToolCall":
            self._send_to_all("chat.tool_call", payload)
        elif name == "_onToolResult":
            self._send_to_all("chat.tool_result", payload)
        elif name == "_onApprovalRequest":
            pass  # 审批走 controller.add_approval，不重复发

    # -- 发送 --------------------------------------------------------------

    def _send_to_all(self, method, params):
        with self._lock:
            link = self.link
        if link is None or link.session_key is None:
            return
        try:
            link.send_event(method, params)
        except Exception as exc:
            self._log(f"send {method} failed: {exc}")

    def _send_to_role(self, role, method, params):
        if role == P.ROLE_APP:
            self._send_to_all(method, params)

    # -- 接收 --------------------------------------------------------------

    def _on_payload(self, method, params, msg_id, sender_role, sender_peer=None):
        """bridge 的业务入口。

        sender_peer 是 client.py 解帧后告知的「哪台设备的密钥解开的」，
        比帧里的明文 dev 字段更可靠（data 帧根本不含 dev）。
        """
        if method == "__response__":
            return  # PC 一般不主动请求，忽略响应

        # 设备身份：优先用解帧得到的 peer_id（= hello 里的 dev），
        # 拿不到才退回角色名。
        session_id = sender_peer or sender_role or P.ROLE_APP
        link = self.link
        if link is None:
            return

        # 配对与认证是特殊流程：它们要回响应
        if method == "pair.req":
            ok, result = self.bridge.handle_pair_req(session_id, params or {})
            if ok:
                # 注意顺序：必须**先**把响应发出去，**再**清配对密钥。
                # 反了的话 send_response 找不到那把钥匙，就会退回到主 PSK
                # 派生的密钥加密，而手机此刻用的是 pair_key —— 解不开，
                # 表现为「配对明明成功却一直超时」。
                link.send_response(method, msg_id, True, result, peer_id=sender_peer)
                link.clear_pairing_keys()
                self._log(f"paired {session_id}; pairing keys cleared")
            else:
                err = result[0] if isinstance(result, tuple) else result
                link.send_response(method, msg_id, False, error=err,
                                   peer_id=sender_peer)
            return

        if method == "auth.req":
            ok, result = self.bridge.handle_auth_req(session_id, params or {})
            if ok:
                link.send_response(method, msg_id, True, result, peer_id=sender_peer)
            else:
                link.send_response(method, msg_id, False, error=result,
                                   peer_id=sender_peer)
            return

        ok, result = self.bridge.dispatch(session_id, method, params or {}, msg_id)
        if ok:
            link.send_response(method, msg_id, True, result, peer_id=sender_peer)
        else:
            link.send_response(method, msg_id, False, error=result,
                               peer_id=sender_peer)

    # -- 配对管理（给本地 UI 用）--------------------------------------------

    def new_pairing(self, role="app"):
        """生成一个新的配对码（一键导入）。

        配对码里含 room，所以手机端**只需要扫码/粘贴**，
        不需要先知道 PSK 就能找到房间。
        """
        room = self.room()
        if not room:
            return {"ok": False, "error": "先设置一个够强的连接密钥"}
        session = self.devices.new_pairing(room, role)
        return {
            "ok": True,
            "code": session.code(),
            "role": session.role,
            "ttl": session.ttl_left(),
            "room": room,
        }

    def current_pairing(self):
        session = self.devices.current_pairing()
        if session is None:
            return None
        return {
            "code": session.code(),
            "role": session.role,
            "ttl": session.ttl_left(),
            "room": session.room,
        }

    def pairing_qr_png(self, code, scale=8):
        """把配对码渲染成二维码 PNG（零依赖自写编码器）。"""
        from agent.relay import qr as qr_mod

        return qr_mod.make_png(code, scale=scale)

    def cancel_pairings(self):
        self.devices.cancel_pairings()
        return {"ok": True}

    def list_devices(self):
        return self.devices.public_list()

    def revoke_device(self, dev_id):
        return self.devices.revoke(dev_id)

    def remove_device(self, dev_id):
        return self.devices.remove(dev_id)

    def revoke_all_devices(self):
        """把全部设备标为已吊销（换 PSK 时由用户决定是否调用）。"""
        return self.devices.revoke_all()

    def clear_devices(self):
        return self.devices.clear_all()

    def fs_audit(self, limit=200):
        return self.bridge.fs.read_audit(limit=limit)

    # -- 配置 --------------------------------------------------------------

    def set_config(self, **kwargs):
        """更新中继配置并落盘。psk 改了就断线重连。"""
        old_psk = self.config.get("psk")
        old_url = self.config.get("url")
        old_proxy = self.config.get("proxy", "auto")
        for key in ("url", "psk", "auto_start", "force_ipv4", "proxy", "dev_id"):
            if key in kwargs and kwargs[key] is not None:
                self.config[key] = kwargs[key]

        if self.config_saver:
            try:
                self.config_saver(self.config)
            except Exception as exc:
                self._log(f"config save failed: {exc}")

        changed = (self.config.get("psk") != old_psk
                   or self.config.get("url") != old_url
                   or self.config.get("proxy", "auto") != old_proxy)
        if changed and self.running:
            self.restart()
        return self.status()

    def room(self):
        psk = self.config.get("psk") or ""
        if not C.psk_ok(psk):
            return ""
        return C.derive_room(psk)

    def _proxy_desc(self):
        """当前实际会用的代理（给 UI 显示，排查"为什么连不上"用）。"""
        try:
            from agent.relay.net import resolve_proxy

            proxy = resolve_proxy(self.config.get("proxy", "auto"))
        except Exception:
            return ""
        if not proxy:
            return ""
        return "%s:%s" % (proxy.get("host", ""), proxy.get("port", ""))

    def status(self):
        with self._lock:
            state = self._state
            info = dict(self._state_info)
            link = self.link
        # connected 的判据是「WS 通着」，不是「有没有会话密钥」。
        # PC 单独在线时房间里没别人，没有 hello 可交换，自然没有会话密钥 ——
        # 那不是"没连上"，而是"还没设备来"。
        # 早先用 session_key 判断，PC 界面永远显示"重连中"，
        # 实际 WS 早就通了（实测 connected=True、key=无）。
        connected = bool(link and link._connected and not self._stop.is_set())
        return {
            "running": self.running,
            "state": state,
            "connected": connected,
            "room": self.room(),
            "url": self.config.get("url") or DEFAULT_RELAY_URL,
            "psk_set": bool(self.config.get("psk")),
            "proxy": self.config.get("proxy", "auto"),
            "proxy_active": self._proxy_desc(),
            "busy": self.controller.busy,
            "owner": self.controller.owner,
            "devices": len(self.devices.devices()),
            "pending_approvals": len(self.controller.list_approvals()),
            **info,
        }
