"""MollyPaw — 后台进程托管（停止按钮的新语义）。

## 为什么要有这个模块

老做法：用户点「停止」→ 直接 `taskkill /T /F` 把整棵进程树干掉。

问题（用户实测反馈）：
  1. 有些命令是**长任务**（打包 APK、跑测试、下载），一刀砍掉等于前功尽弃，
     而且状态全丢，下次还得从头跑。
  2. 有些命令卡在读写管道上，硬杀之后 UI 还是卡在「正在停…」，
     因为主线程还在等 `proc.wait()`。
  3. 被杀掉的东西**模型完全不知道**。它下一轮看到的是工具报「被用户取消」，
     但机器上到底还残留着什么、该不该杀，它两眼一抹黑。

新做法（用户要的）：
  用户点停止 → 正在跑的命令**转入后台继续跑**（不再阻塞这一轮），
  立刻把控制权还给模型和 UI；
  同时在系统提示里把这些后台进程**摆给模型看**，模型自己决定：
    留着（等它跑完）还是杀掉（用 process_kill）。
  杀的时候：有子进程就杀整棵树，没子进程就杀主进程。

这样「停止」变成了「暂停等待」，而不是「毁灭一切」。

## 生命周期

  - 命令结束时由看门狗线程标记 done，输出保留在环形缓冲里供模型回看。
  - 超过 `max_lifetime` 自动杀掉，避免后台堆僵尸。
  - 最多保留 `max_keep` 条记录，超出丢最老的（进程中已结束的优先）。
  - 程序退出时 atexit 全部清掉。
"""
import os
import subprocess
import threading
import time
from collections import deque

# 后台命令最长活多久（秒）。到期自动杀，防止用户忘了、机器被占死。
DEFAULT_MAX_LIFETIME = 30 * 60

# 输出保留多少行/字符，给模型回看用。
OUTPUT_TAIL_LINES = 200
OUTPUT_TAIL_CHARS = 8000


class BgProcess:
    """一条被托管的后台命令。

    输出由原来的 reader 线程继续往 `stdout_chunks` / `stderr_chunks` 里写，
    这里只在读的时候加锁拷一份 —— 不去抢那些线程的所有权。
    """

    def __init__(self, popen, cmd, stdout_chunks, stderr_chunks, shell="powershell"):
        self.popen = popen
        self.cmd = cmd
        self.shell = shell
        self.pid = popen.pid
        self.started_at = time.time()
        self.detached_at = time.time()
        self._stdout_chunks = stdout_chunks
        self._stderr_chunks = stderr_chunks
        self._lock = threading.Lock()
        self.killed_by = None   # None / "user" / "lifetime" / "cleanup"
        self.exit_code = None
        self.finished_at = None

    # -- 状态 --------------------------------------------------------------

    @property
    def alive(self) -> bool:
        try:
            return self.popen.poll() is None
        except Exception:
            return False

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.started_at)

    def refresh_exit(self):
        if self.finished_at is not None:
            return
        code = None
        try:
            code = self.popen.poll()
        except Exception:
            code = None
        if code is not None:
            self.exit_code = code
            self.finished_at = time.time()

    # -- 输出 --------------------------------------------------------------

    def snapshot(self, max_lines=OUTPUT_TAIL_LINES, max_chars=OUTPUT_TAIL_CHARS):
        """取当前已有输出（不阻塞）。

        返回 (stdout_text, stderr_text, truncated)。
        """
        with self._lock:
            out = list(self._stdout_chunks)
            err = list(self._stderr_chunks)
        out_text, out_trunc, _ = _tail("".join(out), max_lines, max_chars)
        err_text, err_trunc, _ = _tail("".join(err), max_lines, max_chars)
        return out_text, err_text, (out_trunc or err_trunc)

    def summary(self):
        self.refresh_exit()
        out_text, err_text, _ = self.snapshot(max_lines=20, max_chars=1500)
        return {
            "pid": self.pid,
            "cmd": _short(self.cmd, 200),
            "shell": self.shell,
            "alive": self.alive,
            "age_seconds": round(self.age, 1),
            "exit_code": self.exit_code,
            "killed_by": self.killed_by,
            "stdout": out_text,
            "stderr": err_text,
        }

    def describe(self):
        """给模型看的一行摘要。"""
        self.refresh_exit()
        state = "运行中" if self.alive else (
            "已退出(%s)" % self.exit_code if self.exit_code is not None else "已结束"
        )
        killed = f" 被{killed_by_label(self.killed_by)}终止" if self.killed_by else ""
        return "pid=%d %s 已跑 %ds%s\n    $ %s" % (
            self.pid, state, int(self.age), killed, _short(self.cmd, 300))


def killed_by_label(value):
    return {
        "user": "用户/模型",
        "lifetime": "超时清理",
        "cleanup": "退出清理",
    }.get(value, value or "")


def _tail(text, max_lines, max_chars):
    truncated = False
    if not text:
        return "", "", False
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
        truncated = True
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[-max_chars:]
        truncated = True
    return text, truncated, truncated


def _short(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# 进程树辅助
# ---------------------------------------------------------------------------

def child_pids(pid):
    """列出 pid 的直接子进程（拿不到就返回空列表）。

    Windows 走 Toolhelp32 快照，纯 ctypes，不起子进程、不依赖 wmic
    （Win11 已经默认不装 wmic 了）。
    """
    if not pid:
        return []
    if os.name == "nt":
        return _windows_child_pids(pid)
    return _posix_child_pids(pid)


def _windows_child_pids(pid):
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == INVALID_HANDLE_VALUE:
            return []
        found = []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                if entry.th32ParentProcessID == pid:
                    found.append(int(entry.th32ProcessID))
                ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        return found
    except Exception:
        return []


def _posix_child_pids(pid):
    try:
        out = subprocess.run(
            ["ps", "-e", "-o", "pid=,ppid="],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except Exception:
        return []
    found = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            child, parent = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if parent == pid:
            found.append(child)
    return found


def has_children(pid):
    return bool(child_pids(pid))


# ---------------------------------------------------------------------------
# 托管器
# ---------------------------------------------------------------------------

class ProcessManager:
    """全局后台进程表。线程安全，单例（manager）。"""

    def __init__(self, max_keep=32, max_lifetime=DEFAULT_MAX_LIFETIME,
                 autostart_watchdog=True):
        self._lock = threading.RLock()
        self._procs = {}          # pid -> BgProcess，按登记顺序
        self._max_keep = max_keep
        self._max_lifetime = max_lifetime
        self._watchdog = None
        self._stop_watchdog = threading.Event()
        if autostart_watchdog:
            self._start_watchdog()

    # -- 登记 --------------------------------------------------------------

    def adopt(self, popen, cmd, stdout_chunks, stderr_chunks, shell="powershell"):
        """把一条正在跑的 Popen 转入后台托管。

        调用方必须保证：**不要关它的 stdout/stderr**，读线程继续跑。
        返回 BgProcess。
        """
        entry = BgProcess(popen, cmd, stdout_chunks, stderr_chunks, shell=shell)
        with self._lock:
            self._procs[entry.pid] = entry
            self._trim_locked()
        return entry

    def _trim_locked(self):
        overflow = len(self._procs) - self._max_keep
        if overflow <= 0:
            return
        # 先丢已经结束的，最老的优先
        dead = [(e.started_at, pid) for pid, e in self._procs.items() if not e.alive]
        dead.sort()
        for _, pid in dead[:overflow]:
            self._procs.pop(pid, None)

    # -- 查询 --------------------------------------------------------------

    def list(self):
        with self._lock:
            entries = list(self._procs.values())
        for entry in entries:
            entry.refresh_exit()
        entries.sort(key=lambda e: e.started_at)
        return entries

    def alive_entries(self):
        return [e for e in self.list() if e.alive]

    def get(self, pid):
        with self._lock:
            return self._procs.get(int(pid))

    def count(self):
        return len(self.alive_entries())

    def prompt_block(self):
        """拼给系统提示用的一段。没有后台进程时返回空串。"""
        entries = self.alive_entries()
        if not entries:
            return ""
        lines = [
            "",
            "## 后台进程（用户按过停止后留下的）",
            "下面是用户按「停止」时被你/系统转入后台继续跑的命令。"
            "**它们还在占着机器**，你要主动处理，别装看不见：",
            "- 还需要结果 → 先 `process_list` 看输出，够了就自己判断；",
            "- 不该继续跑 → `process_kill` 杀掉（有子进程会连整棵树一起杀，"
            "没有子进程就杀主进程）；",
            "- 已经跑完了 → 记录里会标「已退出」，不用管。",
        ]
        for entry in entries:
            lines.append("- " + entry.describe().replace("\n", "\n  "))
        return "\n".join(lines)

    # -- 杀 ----------------------------------------------------------------

    def kill(self, pid, by="user"):
        """杀掉一个后台进程。

        规则（用户定的）：有子进程就杀整棵树，没有子进程就杀主进程。
        `kill_process_tree` 在两边都已经满足这个语义，这里额外把子进程
        数列出来写进结果，好让模型知道到底砍了多少东西。
        """
        from agent.cancel import kill_process_tree

        entry = self.get(pid)
        if entry is None:
            # 不在表里也允许杀 —— 模型可能报了 exec 那次拿到的原始 pid
            target_pid = int(pid)
            children = child_pids(target_pid)
            ok = kill_process_tree(target_pid)
            return {
                "ok": bool(ok),
                "pid": target_pid,
                "children": children,
                "adopted": False,
            }
        children = child_pids(entry.pid)
        was_alive = entry.alive
        ok = kill_process_tree(entry.pid)
        try:
            entry.popen.wait(timeout=3)
        except Exception:
            pass
        entry.refresh_exit()
        if was_alive and not entry.alive:
            entry.killed_by = by
            if entry.finished_at is None:
                entry.finished_at = time.time()
        return {
            "ok": bool(ok),
            "pid": entry.pid,
            "children": children,
            "adopted": True,
        }

    def kill_all(self, by="cleanup"):
        results = []
        for entry in self.list():
            if entry.alive:
                results.append(self.kill(entry.pid, by=by))
        return results

    def forget(self, pid):
        with self._lock:
            self._procs.pop(int(pid), None)
        return True

    def clear(self):
        with self._lock:
            self._procs.clear()

    # -- 看门狗 ------------------------------------------------------------

    def _start_watchdog(self):
        if self._watchdog is not None:
            return
        self._watchdog = threading.Thread(
            target=self._watchdog_loop, name="mollypaw-bgproc", daemon=True)
        self._watchdog.start()

    def _watchdog_loop(self):
        while not self._stop_watchdog.wait(2.0):
            try:
                self._sweep()
            except Exception:
                pass

    def _sweep(self):
        now = time.time()
        for entry in self.list():
            if entry.alive and (now - entry.started_at) > self._max_lifetime:
                self.kill(entry.pid, by="lifetime")
                continue
            entry.refresh_exit()

    def shutdown(self):
        self._stop_watchdog.set()
        try:
            self.kill_all(by="cleanup")
        except Exception:
            pass


class _LazyManager:
    """模块级懒加载单例。

    不在 import 时就起看门狗线程 —— 测试里 import 一堆模块不该带后台线程。
    """

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = ProcessManager()
            return cls._instance

    @classmethod
    def reset(cls):
        with cls._lock:
            if cls._instance is not None:
                cls._instance.shutdown()
            cls._instance = None


def manager():
    return _LazyManager.get()


def import_shutdown_hook():
    import atexit

    atexit.register(lambda: _LazyManager.instance and _LazyManager.instance.shutdown())
