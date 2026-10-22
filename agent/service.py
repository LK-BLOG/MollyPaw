"""MollyPaw — 业务服务层。

把"聊天 / 配置 / 会话 / 审批"这些业务动作从 HTTP 处理器里抽出来，
让 **本地 UI（HTTP）** 和 **远程设备（中继）** 共用同一份实现。

这样做的理由很实在：
  - 单飞锁、取消、审批表只有一份，不会出现"手机停了电脑还在跑"；
  - 远程通道不需要复制一份配置读写逻辑（也就不会漏掉 api_key 剥离）；
  - 可测试：不用起 HTTP 服务器就能测业务。

main.py 的 MollyPawAPI 保留为薄壳，转发到这里。
"""
import json
import threading
import time

from agent.core import AgentCore
from agent.providers.catalog import get_provider, public_providers
from agent.sleep import SleepCycle


class _FallbackController:
    """没有 agent.relay 时用的最小控制器。

    它只提供本地 UI 真正需要的东西：单飞锁 + 取消 + 审批表。
    行为跟真正的 RelayController 一致（同一套语义），
    只是不带远程广播 —— 因为压根没有远程。

    存在的意义：本地聊天不该因为"加密库没装"而挂掉。
    """

    def __init__(self):
        from agent.cancel import CancelToken

        self._lock = threading.RLock()
        self._busy = False
        self._owner = None
        self._token = None
        self._pending = {}

    @property
    def busy(self):
        with self._lock:
            return self._busy

    @property
    def owner(self):
        with self._lock:
            return self._owner

    def acquire(self, owner):
        from agent.cancel import CancelToken

        with self._lock:
            if self._busy:
                return None
            self._busy = True
            self._owner = owner
            self._token = CancelToken()
            return self._token

    def release(self):
        with self._lock:
            self._busy = False
            self._owner = None
            self._token = None

    def stop(self, by="local"):
        from agent.tools.exec_tool import ExecTool

        with self._lock:
            token = self._token
            if not self._busy or token is None:
                return False
        token.cancel(f"stopped by {by}")
        try:
            ExecTool.kill_all()
        except Exception:
            pass
        return True

    def current_token(self):
        with self._lock:
            return self._token

    def add_approval(self, name, args, danger, conversation_id=None):
        """阻塞等待用户决定（不超时），语义同 RelayController。"""
        import uuid as _uuid
        from agent.cancel import CancelledError

        request_id = str(_uuid.uuid4())
        event = threading.Event()
        box = {"approved": False}
        with self._lock:
            self._pending[request_id] = {"event": event, "box": box}

        # 本地没有远程通道，所以只能靠事件轮询让前端弹窗
        self._emit_local("_onApprovalRequest", {
            "name": name, "args": args, "danger_level": danger,
            "request_id": request_id,
        })
        while True:
            if event.wait(timeout=1.0):
                break
            token = self.current_token()
            if token is not None and token.cancelled:
                with self._lock:
                    self._pending.pop(request_id, None)
                raise CancelledError("cancelled while awaiting approval")

        with self._lock:
            self._pending.pop(request_id, None)
            entry = self._pending.get(request_id)
        return bool(box["approved"])

    # 事件出口由 service 注入
    _emit_local = staticmethod(lambda *a, **kw: None)

    def resolve_approval(self, request_id, approved):
        with self._lock:
            entry = self._pending.get(request_id)
        if entry is None:
            return False
        entry["box"]["approved"] = bool(approved)
        entry["event"].set()
        return True

    def list_approvals(self):
        with self._lock:
            return [{"request_id": rid} for rid in self._pending]

    def cancel_all_approvals(self):
        with self._lock:
            entries = list(self._pending.values())
        for entry in entries:
            entry["box"]["approved"] = False
            entry["event"].set()


class MollyPawService:
    """线程安全的业务门面。"""

    def __init__(self, controller=None, logger=None):
        self.agent = None
        self.sleep_cycle = None
        self.pet_state = "idle"
        self._last_activity = time.time()
        self._agent_lock = threading.RLock()
        self.logger = logger

        # 先把事件队列/事件出口建好 —— controller 会用到 self._emit，
        # 顺序反了就会炸 AttributeError（踩过：_sinks_lock 还没定义）。
        self._events = []
        self._events_lock = threading.Lock()
        self._event_sinks = []
        self._sinks_lock = threading.RLock()
        self._approval_mode = "prompt_dangerous"

        # 单飞锁 / 取消 / 审批表 **必须永远存在**。
        #
        # 事故复盘：controller 早先只在 RelayManager 里创建，而 MollyPawService
        # 常常是独立构造的（controller=None）。结果只要没开远程互联，
        # 本地发消息就会在 main.py 的 do_POST 里炸：
        #     AttributeError: 'NoneType' object has no attribute 'acquire'
        # 也就是说"远程互联没开 → 本地聊天挂掉"这个关联非常反直觉。
        #
        # 现在由 service 兜底自建一个；RelayManager 会复用这一个实例，
        # 从而保证本地 UI 和手机共用同一把单飞锁（不会出现"手机停了电脑还在跑"）。
        self.controller = controller if controller is not None else self._make_controller()
        # 降级控制器要把审批请求交给本地事件队列，
        # 否则前端永远等不到弹窗（本地聊天会卡在审批上）。
        if isinstance(self.controller, _FallbackController):
            self.controller._emit_local = self._emit

    def _make_controller(self):
        """自建一个 RelayController。

        import 放在函数里：agent.relay 会拉 cryptography，
        而本地聊天**不依赖**加密库（requirements 里那条是可选功能）。
        缺库时退回一个最小可用的替身，保证本地功能不受影响。
        """
        try:
            from agent.relay.controller import RelayController

            return RelayController(logger=self.logger)
        except Exception as exc:
            if self.logger:
                try:
                    self.logger(f"relay controller unavailable, using fallback: {exc}")
                except Exception:
                    pass
            return _FallbackController()

    def _log(self, msg):
        if self.logger:
            try:
                self.logger(msg)
            except Exception:
                pass

    # -- 事件 --------------------------------------------------------------

    def _queue_event(self, name, payload):
        with self._events_lock:
            self._events.append({"name": name, "payload": payload})

    def _push_result(self, callback, result):
        try:
            payload = json.loads(result) if isinstance(result, str) else result
        except (TypeError, json.JSONDecodeError):
            payload = result
        self._queue_event(callback, payload)

    def get_events(self):
        with self._events_lock:
            events = self._events
            self._events = []
        return {"ok": True, "events": events}

    def add_event_sink(self, sink):
        """注册一个事件接收器（如 relay 桥接）。

        sink(name, payload) 会被每个 tool_call / tool_result / approval 调用。
        本地 UI 走轮询队列，远程走 WS，两边互不影响。
        """
        with self._sinks_lock:
            if sink not in self._event_sinks:
                self._event_sinks.append(sink)

    def remove_event_sink(self, sink):
        with self._sinks_lock:
            if sink in self._event_sinks:
                self._event_sinks.remove(sink)

    def _emit(self, name, payload):
        """同时推给本地队列和所有远程 sink。"""
        self._queue_event(name, payload)
        with self._sinks_lock:
            sinks = list(self._event_sinks)
        for sink in sinks:
            try:
                sink(name, payload)
            except Exception as exc:
                self._log(f"event sink failed: {exc}")

    # -- Agent 生命周期 ----------------------------------------------------

    def with_agent(self, fn):
        """在 AgentCore 上跑一个函数。持锁保证同一时刻只有一个操作动 agent。

        注意：**不持锁跑整轮 chat**，否则本地 UI 就永远拿不到状态了。
        锁只保护 agent 的创建与查询。
        """
        agent = self._ensure_agent()
        return fn(agent)

    def _ensure_agent(self):
        with self._agent_lock:
            if self.agent is None:
                self.agent = AgentCore()
                self.agent.set_tool_call_callback(self._tool_call_callback)
                self.agent.set_tool_result_callback(self._tool_result_callback)
                self.agent.set_approval_callback(self._approval_request_callback)
                self.agent.approval_mode = self._approval_mode
                self.sleep_cycle = SleepCycle(
                    self.agent.provider,
                    self.agent.config,
                    lambda state: setattr(self, "pet_state", state),
                    lambda: self.pet_state == "work",
                )
                self.sleep_cycle.start()
            return self.agent

    # -- 回调 --------------------------------------------------------------

    def _tool_call_callback(self, info):
        self._emit("_onToolCall", info)

    def _tool_result_callback(self, info):
        self._emit("_onToolResult", info)

    def _approval_request_callback(self, info):
        """需要用户审批。阻塞直到决定（**不超时**）。"""
        if self.controller is not None:
            return self.controller.add_approval(
                name=info.get("name", ""),
                args=info.get("args", {}),
                danger=info.get("danger_level", "moderate"),
                conversation_id=self.current_conversation_id(),
            )
        # 没接控制器（纯本地）时退回事件轮询模式
        request_id = info.get("request_id") or f"local-{int(time.time()*1000)}"
        event = threading.Event()
        self._pending_approvals = getattr(self, "_pending_approvals", {})
        self._pending_approvals[request_id] = {"event": event, "approved": False}
        self._emit("_onApprovalRequest", {**info, "request_id": request_id})
        event.wait()
        result = self._pending_approvals.pop(request_id, {"approved": False})
        return bool(result.get("approved"))

    # -- 聊天 --------------------------------------------------------------

    def chat_sync(self, message, on_delta=None, on_round=None, cancel=None):
        """跑一整轮对话（阻塞）。调用方负责单飞锁。"""

        def _work(agent):
            return agent.chat(message, on_delta=on_delta, on_round=on_round,
                              cancel=cancel)

        return self.with_agent(_work)

    def start_chat_async(self, message, on_delta=None, on_round=None,
                         on_done=None, cancel=None, owner="local"):
        """起一个后台线程跑一轮。返回 (token, thread) 或 (None, None)（忙）。"""
        token = None
        if self.controller is not None:
            token = self.controller.acquire(owner)
            if token is None:
                return None, None
        else:
            from agent.cancel import CancelToken

            token = cancel or CancelToken()

        def _run():
            try:
                result = self.chat_sync(
                    message, on_delta=on_delta, on_round=on_round, cancel=token
                )
                if on_done:
                    on_done({"ok": True, **result})
            except Exception as exc:
                from agent.cancel import CancelledError

                cancelled = isinstance(exc, CancelledError)
                if on_done:
                    on_done({"ok": False, "cancelled": cancelled, "error": str(exc)})
            finally:
                if self.controller is not None:
                    self.controller.release()
                    self.controller.cancel_all_approvals()

        thread = threading.Thread(target=_run, daemon=True, name="mollypaw-chat")
        thread.start()
        return token, thread

    def stop_chat(self, by="local"):
        if self.controller is None:
            return False
        return self.controller.stop(by=by)

    @property
    def busy(self):
        if self.controller is None:
            return False
        return self.controller.busy

    # -- 会话 --------------------------------------------------------------

    def current_conversation_id(self):
        agent = self.agent
        return agent.conversation_id if agent else None

    def list_conversations(self):
        return self.with_agent(lambda a: a.list_conversations())

    def new_conversation(self):
        return self.with_agent(lambda a: a.new_conversation())

    def load_conversation(self, conv_id):
        return self.with_agent(lambda a: a.load_conversation(conv_id))

    def delete_conversation(self, conv_id):
        return self.with_agent(lambda a: a.delete_conversation(conv_id))

    def clear_history(self):
        return self.with_agent(lambda a: a.clear_history())

    # -- 配置 --------------------------------------------------------------

    def get_config(self):
        """本地 UI 用：包含完整 api_key。"""
        return self.with_agent(lambda a: a.get_config())

    def get_config_public(self, redact_connection=False):
        """远程用：api_key 打码。"""
        return self.with_agent(
            lambda a: a.get_config_public(redact_connection=redact_connection)
        )

    def save_config(self, new_config):
        agent = self.with_agent(lambda a: a.save_config(new_config))
        if self.sleep_cycle and self.agent:
            self.sleep_cycle.provider = self.agent.provider
            self.sleep_cycle.reload_config()
        return agent

    def set_approval_mode(self, mode):
        if mode not in ("full_access", "prompt_all", "prompt_dangerous"):
            raise ValueError("Invalid mode")
        self._approval_mode = mode
        agent = self._ensure_agent()
        agent.approval_mode = mode
        agent.save_config({"approval_mode": mode})
        return mode

    def get_approval_mode(self):
        return self._approval_mode

    def set_thinking_level(self, level):
        if level not in ("none", "low", "medium", "high", "max"):
            raise ValueError("Invalid thinking level")
        agent = self._ensure_agent()
        agent.save_config({"thinking_level": level})
        if self.sleep_cycle:
            self.sleep_cycle.provider = agent.provider
        return level

    def providers(self):
        return public_providers()

    def models(self, provider_id, api_key="", base_url="", protocol="chat"):
        from agent.providers.openai_provider import OpenAIProvider

        agent = self._ensure_agent()
        preset = get_provider(provider_id)
        if preset:
            base_url = preset["base_url"]
            protocol = preset["protocol"]
            models_path = preset.get("models_path", "/models")
            auth_mode = preset.get("auth_mode", "bearer")
            supports_temperature = preset.get("supports_temperature", True)
        else:
            models_path = "/models"
            auth_mode = "bearer"
            supports_temperature = True
        provider = OpenAIProvider(
            api_key=api_key or agent.config.get("api_key", ""),
            base_url=base_url,
            protocol=protocol,
            models_path=models_path,
            auth_mode=auth_mode,
            supports_temperature=supports_temperature,
        )
        return provider.list_models()

    def balance(self):
        agent = self._ensure_agent()
        preset = get_provider(agent.config.get("provider_id")) or {}
        return agent.provider.get_balance(
            preset.get("balance_path", agent.config.get("balance_path", "")),
            preset.get("balance_parser", ""),
            preset.get("balance_base_url", ""),
        )

    def skills(self):
        return self.with_agent(
            lambda a: a.tool_registry.execute("list_skills", {})
        )

    # -- 宠物状态 ----------------------------------------------------------

    def set_pet_state(self, state):
        if state in ("idle", "work", "cry", "sleep"):
            self.pet_state = state
            if state != "sleep":
                self.mark_activity()
            return True
        return False

    def mark_activity(self):
        self._last_activity = time.time()
        if self.sleep_cycle:
            self.sleep_cycle.mark_activity()

    def status(self):
        info = {
            "pet_state": self.pet_state,
            "busy": self.busy,
            "conversation_id": self.current_conversation_id(),
        }
        if self.sleep_cycle:
            try:
                info["sleep"] = self.sleep_cycle.get_status()
            except Exception:
                pass
        return info

    def approve_tool(self, request_id, approved):
        """本地 UI 的审批入口（HTTP /api/approve_tool）。"""
        if self.controller is not None:
            return self.controller.resolve_approval(request_id, approved)
        pending = getattr(self, "_pending_approvals", {}).get(request_id)
        if pending:
            pending["approved"] = bool(approved)
            pending["event"].set()
            return True
        return False
