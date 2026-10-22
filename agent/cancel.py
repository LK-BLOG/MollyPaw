"""MollyPaw — 取消令牌。

用于「停止按钮」：让正在跑的 LLM 请求和子进程能被真正打断，
而不是等到整轮跑完才发现用户早就点了停止。

设计要点：
  - 线程安全，可跨线程设置（UI 线程设，工作线程查）。
  - 支持"父子级联"：停止一个会话令牌会连带停掉它派生的子令牌
    （比如 exec_command 内部再起的东西）。
  - 一旦取消，**不可复位**。要重新开始就新建一个令牌 —— 避免
    "取消后又跑起来"这种最难查的竞态。
"""
import os
import signal
import threading


class CancelledError(Exception):
    """本轮被用户取消。调用方应回滚未持久化的历史，不要当成失败重试。"""


# ---------------------------------------------------------------------------
# 当前取消令牌（线程/上下文局部）
# ---------------------------------------------------------------------------
# 工具（比如 exec_command）的 execute(func_name, arguments) 签名是固定的，
# 为了不破坏所有现有工具，用 contextvar 把"当前这轮的取消令牌"传下去，
# 工具内部需要时自己取。
#
# 用 contextvars 而不是 threading.local：contextvar 能跟到 asyncio 任务里，
# 且显式 copy，不会出现"线程复用了旧令牌"的问题。

_context_token = None


def _ensure_contextvar():
    global _context_token
    if _context_token is None:
        import contextvars

        _context_token = contextvars.ContextVar("mollypaw_cancel_token", default=None)
    return _context_token


def set_current_token(token):
    """把令牌设为当前上下文的取消信号。返回可用于恢复的 token。"""
    var = _ensure_contextvar()
    return var.set(token)


def reset_current_token(handle):
    var = _ensure_contextvar()
    try:
        var.reset(handle)
    except Exception:
        pass


def current_token():
    """取出当前上下文的取消令牌（可能是 None）。"""
    return _ensure_contextvar().get()


class use_token:
    """上下文管理器：在这段代码里把 cancel 设为当前令牌。

    用法：
        with use_token(cancel):
            registry.execute(name, args)
    """

    def __init__(self, token):
        self.token = token
        self._handle = None

    def __enter__(self):
        self._handle = set_current_token(self.token)
        return self.token

    def __exit__(self, *exc):
        if self._handle is not None:
            reset_current_token(self._handle)
        self._handle = None
        return False


class CancelToken:
    """可共享的取消信号。"""

    __slots__ = ("_event", "_reason", "_lock", "_children")

    def __init__(self, parent=None):
        self._event = threading.Event()
        self._reason = ""
        self._lock = threading.RLock()
        self._children = []
        if parent is not None:
            parent._register_child(self)

    # -- 父级联 ------------------------------------------------------------

    def _register_child(self, child):
        with self._lock:
            if self._event.is_set():
                # 父已取消，子立即跟上
                child.cancel(self._reason)
                return
            self._children.append(child)

    def child(self):
        """派生一个子令牌，父被取消时子会一起取消。"""
        return CancelToken(parent=self)

    # -- 状态 --------------------------------------------------------------

    def cancel(self, reason="user"):
        with self._lock:
            if self._event.is_set():
                return False
            self._reason = reason
            self._event.set()
            children = list(self._children)
            self._children.clear()
        for child in children:
            child.cancel(reason)
        return True

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def wait(self, timeout=None) -> bool:
        return self._event.wait(timeout)

    def raise_if_cancelled(self):
        if self._event.is_set():
            raise CancelledError(self._reason or "cancelled")

    def reset(self):
        """**故意不实现**。取消是单向的，想重来请新建令牌。"""
        raise NotImplementedError(
            "CancelToken is one-way by design; create a new token instead."
        )


def kill_process_tree(pid, timeout=3.0):
    """强杀进程及其所有子进程。

    Windows 必须用 taskkill /T，否则 powershell 起的孙子进程会残留
    （`subprocess.kill()` 只杀直接子进程）。POSIX 走进程组。

    返回 True 表示成功杀掉了东西。
    """
    if not pid:
        return False

    if os.name == "nt":
        import subprocess

        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return True
        except Exception:
            return False

    # POSIX：先试进程组，再退回单进程
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            return False
    return True
