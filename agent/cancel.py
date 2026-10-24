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

    **POSIX 下的关键防护**：不能无条件 `os.killpg(os.getpgid(pid), ...)`。
    如果目标进程没有独立成组（没带 `start_new_session=True` / `setsid`），
    `getpgid(pid)` 返回的就是**我们自己的进程组** —— 一发信号，
    父进程（pytest、你的应用）跟着一起死。
    实测就是这个坑：CI 上 pytest 跑到第 18 个测试就整体被杀（exit 143）。
    所以这里必须先比对进程组，不同才 killpg。
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

    # POSIX
    try:
        target_group = os.getpgid(pid)
        own_group = os.getpgid(0)
    except (OSError, ProcessLookupError):
        target_group = None
        own_group = None

    # 先摸清整棵子树。**不能只靠 killpg**：
    # 目标和我们同组时 killpg 会连自己一起杀（已踩），而"同组"恰恰是最常见
    # 的情况（子进程没带 start_new_session=True）。这时唯一的正确做法是
    # 把子孙进程逐个点名杀掉。
    descendants = _posix_descendants(pid)

    killed = False

    if target_group is not None and target_group != own_group:
        try:
            os.killpg(target_group, signal.SIGKILL)
            killed = True
        except OSError:
            pass

    # 补充清理：目标可能被移到了别的进程组、或者 killpg 半路失败。
    # 从最深的开始杀，避免中间进程先死导致子树被 reparent 掉之后漏杀。
    for child in reversed(descendants):
        if _kill_one(child):
            killed = True

    return _kill_one(pid) or killed


def _posix_descendants(pid):
    """用 ps 列出 pid 的全部子孙进程（含曾孙等）。

    POSIX 没有 /proc 的通用保证（macOS 压根没有），ps -e -o pid=,ppid=
    两边都能用。拿不到就返回空列表 —— 调用方仍会尝试杀单个进程。
    """
    import subprocess

    try:
        out = subprocess.run(
            ["ps", "-e", "-o", "pid=", "-o", "ppid="],
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout
    except Exception:
        return []

    children = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            child_pid, parent_pid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        children.setdefault(parent_pid, []).append(child_pid)

    found = []
    stack = [pid]
    while stack:
        current = stack.pop()
        for child_pid in children.get(current, ()):
            found.append(child_pid)
            stack.append(child_pid)
    return found


def _kill_one(pid):
    """杀单个进程。

    用 SIGKILL 而不是 SIGTERM：用户点"停止"是要**立刻**停，
    SIGTERM 只是"请求退出" —— 对方可以忽略它，进程照样跑。
    Windows 那边 taskkill /F 也是强杀，两边语义一致。
    """
    try:
        os.kill(pid, signal.SIGKILL)
        return True
    except OSError:
        return False
