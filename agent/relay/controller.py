"""MollyPaw Relay — 会话控制 + 事件广播。

职责：
  - **全局单飞**：任何时刻只有一轮 agent 在跑，PC 本地 UI 和手机共用这条锁
  - **停止**：CancelToken，1 秒内真正中断
  - **事件广播**：把 tool_call / delta / approval 推给所有已连接的手机
  - **待决审批表**：连接断了请求也在，重连后能 approval.list 拉到

它不碰网络（那是 client.py），也不碰业务语义（那是 bridge.py）。
"""
import threading
import time
import uuid

from agent.cancel import CancelToken, CancelledError


class PendingApproval:
    __slots__ = ("request_id", "name", "args", "danger", "created_at",
                 "event", "approved", "conversation_id")

    def __init__(self, request_id, name, args, danger, conversation_id=None):
        self.request_id = request_id
        self.name = name
        self.args = args
        self.danger = danger
        self.created_at = time.time()
        self.event = threading.Event()
        self.approved = False
        self.conversation_id = conversation_id

    def to_public(self):
        return {
            "request_id": self.request_id,
            "name": self.name,
            "args": self.args,
            "danger_level": self.danger,
            "created_at": self.created_at,
            "conversation_id": self.conversation_id,
        }


class RelayController:
    """单飞锁 + 取消 + 广播 + 审批表。

    broadcast(event, params)  由外部注入：把事件发给所有手机
    """

    def __init__(self, broadcast=None, logger=None):
        self._lock = threading.RLock()
        self._busy = False
        self._owner = None              # "local" / "app:<dev_id>" / None
        self._token = None
        self._pending = {}
        self._broadcast = broadcast
        self.logger = logger

    def _log(self, msg):
        if self.logger:
            try:
                self.logger(msg)
            except Exception:
                pass

    # -- 单飞 --------------------------------------------------------------

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    @property
    def owner(self):
        with self._lock:
            return self._owner

    def acquire(self, owner):
        """尝试开始一轮。成功返回 CancelToken；已在跑返回 None。"""
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
        """请求中断当前轮。返回是否真的发起了停止。"""
        with self._lock:
            token = self._token
            busy = self._busy
            owner = self._owner
        if not busy or token is None:
            return False
        token.cancel(f"stopped by {by}")
        self._log(f"stop requested by {by} (owner was {owner})")

        # 注意：这里**故意不再杀子进程**。
        # 停止的语义是「把正在跑的命令转入后台」（见 agent/process_manager.py），
        # exec_command 自己的循环会检测到 cancel 并把进程交给 ProcessManager，
        # 然后由模型用 process_kill 决定杀不杀。
        # 以前在这里 kill_all() 是硬杀，导致：状态全丢 + UI 卡在"正在停" +
        # 模型不知道机器上残留了什么。

        if self._broadcast:
            try:
                self._broadcast("chat.stopped", {"by": by})
            except Exception:
                pass
        return True

    def current_token(self):
        with self._lock:
            return self._token

    # -- 审批 --------------------------------------------------------------

    def add_approval(self, name, args, danger, conversation_id=None):
        """登记一个待决审批并广播，阻塞等待用户决定（**不超时**）。

        PROTOCOL.md §6.2：不设超时。手机锁屏 10 分钟后回来还能点。
        """
        request_id = str(uuid.uuid4())
        pending = PendingApproval(request_id, name, args, danger, conversation_id)
        with self._lock:
            self._pending[request_id] = pending

        if self._broadcast:
            self._broadcast("approval.request", pending.to_public())

        # 无限等 —— 只有用户点同意/拒绝，或者这轮被停止，才会返回
        while True:
            if pending.event.wait(timeout=1.0):
                break
            token = self.current_token()
            if token is not None and token.cancelled:
                # 本轮被停了，审批自动作废
                with self._lock:
                    self._pending.pop(request_id, None)
                raise CancelledError("cancelled while awaiting approval")

        with self._lock:
            self._pending.pop(request_id, None)

        if self._broadcast:
            self._broadcast("approval.resolved", {
                "request_id": request_id,
                "approved": bool(pending.approved),
            })
        return bool(pending.approved)

    def resolve_approval(self, request_id, approved):
        with self._lock:
            pending = self._pending.get(request_id)
        if pending is None:
            return False
        pending.approved = bool(approved)
        pending.event.set()
        return True

    def list_approvals(self):
        with self._lock:
            return [p.to_public() for p in self._pending.values()]

    def cancel_all_approvals(self):
        """连接全断 / 轮次结束时把所有待决审批放掉（当拒绝处理）。"""
        with self._lock:
            pendings = list(self._pending.values())
        for p in pendings:
            p.approved = False
            p.event.set()
