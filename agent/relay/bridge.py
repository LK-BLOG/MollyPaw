"""MollyPaw Relay — RPC 桥接。

把中继收到的 `data` 载荷翻译成对 MollyPawService 的调用，
把服务产生的事件翻译成加密帧发回去。

**权限在这里强制**：PROTOCOL.md §6 的方法表是白名单，
observer 碰任何写操作都回 forbidden，config.save 一律剥掉 api_key。

这个文件是安全边界的守门人 —— 改它之前先想清楚。
"""
import base64
import json
import os
import threading
import time

from agent.relay import protocol as P
from agent.relay.fs_api import FsApi


class RelayBridge:
    """中继 <-> 服务 的翻译层。"""

    def __init__(self, service, controller, devices=None, logger=None):
        """
        service     MollyPawService（agent/service.py）
        controller  RelayController
        devices     DeviceStore；None 则配对/认证不可用（本地模式）
        """
        self.service = service
        self.controller = controller
        self.devices = devices
        self.fs = FsApi(logger=logger)
        self.logger = logger

        # 当前每条连接的设备身份：msg_id 无关，按角色/设备记录
        self._sessions = {}          # session_key -> {"dev_id","role","name"}
        self._sessions_lock = threading.RLock()

        # 事件往哪儿发：由 RelayManager 注入
        self._send_to_all = None
        self._send_to_role = None

        # 取主 PSK 的回调：配对成功时要把 PSK 下发给手机（见 handle_pair_req）
        self.psk_provider = None

        # 配对握手状态
        self._pair_lock = threading.RLock()
        self._pairing_devices = {}   # dev_id -> {"name","pub","ts"}

    def _log(self, msg):
        if self.logger:
            try:
                self.logger(msg)
            except Exception:
                pass

    # -- 事件出口 ----------------------------------------------------------

    def bind_senders(self, send_to_all, send_to_role):
        self._send_to_all = send_to_all
        self._send_to_role = send_to_role

    def broadcast(self, method, params):
        """把事件发给所有已就绪的连接。"""
        if self._send_to_all:
            try:
                self._send_to_all(method, params)
            except Exception as exc:
                self._log(f"broadcast {method} failed: {exc}")

    # -- 会话登记 ----------------------------------------------------------

    def register_session(self, session_id, dev_id, role, name=None):
        """登记会话。role 是**服务端授予的角色**（来自设备注册表），
        不是客户端在 hello 里自称的那个。

        客户端连接时一律自称 app（它还不知道自己被授了什么），
        真实权限只有服务端知道 —— 权限判定必须用这里的 role。
        """
        with self._sessions_lock:
            self._sessions[session_id] = {
                "dev_id": dev_id, "role": role, "name": name,
                "connected_at": time.time(),
            }

    def unregister_session(self, session_id):
        with self._sessions_lock:
            self._sessions.pop(session_id, None)

    def session_role(self, session_id):
        with self._sessions_lock:
            entry = self._sessions.get(session_id)
            return entry["role"] if entry else None

    # -- 配对 --------------------------------------------------------------

    def handle_pair_req(self, session_id, params):
        """PROTOCOL.md §5.1 的 pair.req。

        客户端送的是配对码里的**一次性注册凭据**（reg_token），
        不是 6 位 PIN：
            MP1.<b64(reg_token)>.<room>
        手机端 parse 出 reg_token 和 room 后，用 room 连上、
        用 reg_token 换长期设备 token。

        为什么改成这样（实测结论见 tools/audit_threat_model.py）：
        早先用「6 位 PIN + PBKDF2 proof」，但客户端必须把 pin 明文
        一起送进来，服务端解密后直接读到 pin —— 同一帧里既有 pin
        又有用 pin 算的 proof，等于自己验自己，PBKDF2 一次没用上。
        reg_token 是 32 字节随机数，本身没有爆破空间，
        也就不需要人为拉高单次尝试成本。
        """
        if self.devices is None:
            return False, "pairing_unavailable"

        dev_id = str(params.get("dev_id") or "")
        dev_name = str(params.get("dev_name") or "未命名设备")
        try:
            dev_pub = base64.b64decode(params.get("dev_pub") or "")
        except Exception:
            dev_pub = b""
        try:
            reg_token = base64.b64decode(params.get("reg_token") or "")
        except Exception:
            return False, "bad_code"

        if not dev_id or not reg_token:
            return False, "bad_code"

        result, err = self.devices.claim_pairing(reg_token, dev_id, dev_name, dev_pub)
        if err:
            return False, err

        device = result["device"]
        self.register_session(session_id, dev_id, device["role"], dev_name)
        self._log(f"paired device {dev_name} ({dev_id}) as {device['role']}")

        payload = {
            "role": device["role"],
            "token": result["token"],
            "server_ts": int(time.time() * 1000),
        }

        # 把主 PSK 一并下发，让手机真正"扫码即用"。
        #
        # 为什么必须发：配对码里的 pair_key 只用于**这一次**配对会话，
        # 服务端配对成功后立刻作废它。手机要是拿不到主 PSK，
        # 后续请求就会全部超时（实测过：配对成功、紧接着全超时）。
        #
        # 安全取舍（想清楚再改）：
        #   - 这一帧走的是已经端到端加密的配对通道，中继看不到明文；
        #   - 能拿到配对码的人本来就能配对成设备（等于拿到设备权限），
        #     顺带拿到 PSK 并没有扩大攻击面；
        #   - 配对码 15 分钟有效、一次性，泄露窗口有限；
        #   - 代价：配对码本身也成了敏感信息 —— 界面上已写明"别截图发群里"。
        # 不这么做的话，"扫码就能连"只是半个功能（用户还得手输 16 位密钥）。
        psk = ""
        if self.psk_provider is not None:
            try:
                psk = self.psk_provider() or ""
            except Exception as exc:
                self._log(f"psk_provider failed: {exc}")
        if psk:
            payload["psk"] = psk

        return True, payload

    def handle_auth_req(self, session_id, params):
        """PROTOCOL.md §5.2 的 auth.req。"""
        if self.devices is None:
            return False, "auth_unavailable"

        dev_id = str(params.get("dev_id") or "")
        token = params.get("token") or ""
        try:
            ts = int(params.get("ts") or 0)
        except (TypeError, ValueError):
            return False, "stale_ts"

        # 客户端时间戳可能是毫秒；若是秒，转成毫秒，避免误判过期
        if ts < 10_000_000_000:
            ts *= 1000

        device, err = self.devices.authenticate(dev_id, ts / 1000.0, token)
        if err:
            return False, err

        self.devices.touch(dev_id)
        self.register_session(session_id, dev_id, device["role"], device.get("name"))
        return True, {
            "role": device["role"],
            "server_ts": int(time.time() * 1000),
        }

    # -- 主分发 ------------------------------------------------------------

    def dispatch(self, session_id, method, params, msg_id):
        """处理一个请求。返回 (ok, result_or_error)。

        权限检查在**最前面**：未知方法、越权角色一律拒绝。
        """
        params = params or {}
        role = self.session_role(session_id)

        if role is None:
            return False, "unauthenticated"

        # 白名单校验
        if not P.can_call(role, method):
            return False, "forbidden"

        handler = getattr(self, f"_m_{method.replace('.', '_')}", None)
        if handler is None:
            return False, "not_found"

        try:
            return True, handler(session_id, role, params)
        except PermissionError:
            return False, "forbidden"
        except FileNotFoundError as exc:
            return False, f"not_found: {exc}"
        except Exception as exc:
            self._log(f"{method} failed: {exc}")
            return False, str(exc) or "internal"

    # -- 聊天 --------------------------------------------------------------

    def _m_chat_send(self, session_id, role, params):
        text = str(params.get("text") or "")
        if not text.strip():
            return {"ok": True, "ignored": True}

        device = self._session_dev(session_id)
        token = self.controller.acquire(f"app:{device}")
        if token is None:
            raise RuntimeError("busy")

        conversation_id = params.get("conversation_id")
        message_id = f"msg-{int(time.time() * 1000)}"

        thread = threading.Thread(
            target=self._run_chat,
            args=(text, conversation_id, message_id, token),
            daemon=True,
        )
        thread.start()
        return {"conversation_id": conversation_id, "message_id": message_id}

    def _run_chat(self, text, conversation_id, message_id, token):
        """在工作线程里跑一轮 agent，边跑边推事件。"""
        from agent.cancel import CancelledError

        def on_delta(piece, kind):
            self.broadcast("chat.delta", {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "text": piece if kind == "content" else "",
                "reasoning": piece if kind == "reasoning" else "",
                "done": False,
            })

        def on_round(info):
            self.broadcast("chat.round", {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "round": info.get("round"),
            })

        try:
            def _work(agent):
                if conversation_id and agent.conversation_id != conversation_id:
                    agent.load_conversation(conversation_id)
                return agent.chat(text, on_delta=on_delta, cancel=token, on_round=on_round)

            result = self.service.with_agent(_work)
            self.broadcast("chat.delta", {
                "conversation_id": self.service.current_conversation_id(),
                "message_id": message_id,
                "text": result.get("response", ""),
                "done": True,
                "cancelled": False,
                "usage": result.get("usage", {}),
                "cost": result.get("cost"),
            })
        except CancelledError:
            self.broadcast("chat.delta", {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "text": "",
                "done": True,
                "cancelled": True,
            })
        except Exception as exc:
            self.broadcast("chat.delta", {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "text": "",
                "done": True,
                "cancelled": False,
                "error": str(exc),
            })
        finally:
            self.controller.release()
            self.controller.cancel_all_approvals()

    def _m_chat_stop(self, session_id, role, params):
        stopped = self.controller.stop(by=f"app:{self._session_dev(session_id)}")
        return {"stopped": bool(stopped)}

    def _m_chat_delta(self, session_id, role, params):
        return {"ignored": True}  # 事件方法，不该被主动调用

    # -- 审批 --------------------------------------------------------------

    def _m_approval_list(self, session_id, role, params):
        return {"pending": self.controller.list_approvals()}

    def _m_approval_reply(self, session_id, role, params):
        # 只有控制端能审批；observer 已在 can_call 被拒
        request_id = str(params.get("req_id") or "")
        approved = bool(params.get("approved"))
        ok = self.controller.resolve_approval(request_id, approved)
        if not ok:
            raise RuntimeError("not_found")
        return {"ok": True}

    # -- 会话 --------------------------------------------------------------

    def _m_conv_list(self, session_id, role, params):
        return {"conversations": self.service.list_conversations()}

    def _m_conv_new(self, session_id, role, params):
        return {"id": self.service.new_conversation()}

    def _m_conv_load(self, session_id, role, params):
        conv_id = str(params.get("id") or "")
        conv = self.service.load_conversation(conv_id)
        if not conv:
            raise FileNotFoundError(conv_id)
        return conv

    def _m_conv_delete(self, session_id, role, params):
        conv_id = str(params.get("id") or "")
        self.service.delete_conversation(conv_id)
        return {"ok": True}

    # -- 配置 --------------------------------------------------------------

    def _m_config_get(self, session_id, role, params):
        # 观察端多剥一层连接信息
        return self.service.get_config_public(
            redact_connection=(role == P.ROLE_OBSERVER)
        )

    def _m_config_save(self, session_id, role, params):
        """保存配置。**强制剥掉 api_key** —— 手机永远改不了密钥。"""
        clean = {k: v for k, v in (params or {}).items() if k != "api_key"}
        rejected = [k for k in ("api_key",) if k in (params or {})]
        self.service.save_config(clean)
        return {"ok": True, "ignored_fields": rejected}

    # -- 文件 --------------------------------------------------------------

    def _require_app(self, role):
        if role != P.ROLE_APP:
            raise PermissionError("files require control role")

    def _session_dev(self, session_id):
        with self._sessions_lock:
            entry = self._sessions.get(session_id)
            return entry["dev_id"] if entry else "unknown"

    def _m_fs_roots(self, session_id, role, params):
        self._require_app(role)
        return self.fs.roots(device=self._session_dev(session_id))

    def _m_fs_list(self, session_id, role, params):
        self._require_app(role)
        return self.fs.list_dir(params.get("path", "."), device=self._session_dev(session_id))

    def _m_fs_stat(self, session_id, role, params):
        self._require_app(role)
        return self.fs.stat(params.get("path"), device=self._session_dev(session_id))

    def _m_fs_read(self, session_id, role, params):
        self._require_app(role)
        return self.fs.read(
            params.get("path"),
            offset=params.get("offset", 0),
            length=params.get("len"),
            device=self._session_dev(session_id),
        )

    def _m_fs_write(self, session_id, role, params):
        """写文件必须走审批 —— 这是唯一挡住"手机随手改电脑文件"的闸。"""
        self._require_app(role)
        path = params.get("path")
        data_b64 = params.get("data_b64") or ""
        size = len(data_b64) * 3 // 4
        approved = self.controller.add_approval(
            name="fs.write",
            args={"path": path, "bytes": size},
            danger="dangerous",
        )
        if not approved:
            return {"ok": False, "e": "rejected"}
        return self.fs.write(
            path, data_b64, offset=params.get("offset"),
            device=self._session_dev(session_id),
        )

    def _m_fs_mkdir(self, session_id, role, params):
        self._require_app(role)
        path = params.get("path")
        approved = self.controller.add_approval(
            name="fs.mkdir", args={"path": path}, danger="moderate",
        )
        if not approved:
            return {"ok": False, "e": "rejected"}
        return self.fs.mkdir(path, device=self._session_dev(session_id))

    def _m_fs_delete(self, session_id, role, params):
        self._require_app(role)
        path = params.get("path")
        approved = self.controller.add_approval(
            name="fs.delete", args={"path": path}, danger="dangerous",
        )
        if not approved:
            return {"ok": False, "e": "rejected"}
        return self.fs.delete(path, device=self._session_dev(session_id))

    # -- 状态 / 设备 --------------------------------------------------------

    def _m_status_get(self, session_id, role, params):
        return self.service.status()

    def _m_device_list(self, session_id, role, params):
        self._require_app(role)
        if self.devices is None:
            return {"devices": []}
        return {"devices": self.devices.public_list()}

    def _m_device_revoke(self, session_id, role, params):
        self._require_app(role)
        dev_id = str(params.get("dev_id") or "")
        if self.devices is None:
            raise RuntimeError("unavailable")
        if not self.devices.revoke(dev_id):
            raise FileNotFoundError(dev_id)
        # 被吊销的设备立刻踢下线
        if self._send_to_role:
            try:
                self._send_to_role(P.ROLE_APP, "device.revoked", {"dev_id": dev_id})
            except Exception:
                pass
        return {"ok": True}

    def _m_server_ping(self, session_id, role, params):
        return {"server_ts": int(time.time() * 1000)}
