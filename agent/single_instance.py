"""MollyPaw — 单实例锁。

单独成模块的原因有两个：
  1. 这段判断必须在 `import webview` **之前**跑完，否则会先起 GUI 再退出。
     所以它只依赖标准库，main.py 在顶部 import 它即可。
  2. 以前这段逻辑在测试里是**手抄一份**的 —— 抄的东西会漂，生产代码改了
     测试还在验旧逻辑。现在测试直接 import 真模块。

**Windows 的坑（实测踩到，会真杀进程）**
    拿 `os.kill(pid, 0)` 判断进程存活在 Windows 上是错的：
    `signal.CTRL_C_EVENT == 0`，CPython 的 os.kill 在 Windows 上对
    sig==0 走的是 `GenerateConsoleCtrlEvent(CTRL_C_EVENT, pid)` ——
    这是往控制台**广播 Ctrl+C**，不是探活。

    后果非常毒：
      * 用户双击第二次图标 → 第一个 MollyPaw 收到 Ctrl+C 被干掉；
      * 同一个控制台里的 shell / pytest 也跟着 KeyboardInterrupt
        （测试时表现为整轮 pytest 无声无息死在 75%，查了半天）。

    所以 Windows 走 OpenProcess + GetExitCodeProcess(STILL_ACTIVE)。
"""
import os
import tempfile

LOCK_PATH = os.path.join(tempfile.gettempdir(), "MollyPaw.lock")

_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def pid_alive(pid) -> bool:
    """进程是否还活着（**不会**给目标发任何信号）。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pid_alive_windows(pid) -> bool:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def check_single_instance(lock_path=None) -> bool:
    """抢锁。True = 我是唯一实例；False = 已经有一个活着的实例。"""
    path = lock_path or LOCK_PATH

    # 有限次重试：万一别的实例刚好在同一个瞬间清锁，别无限递归。
    for _ in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            old_pid = 0
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    old_pid = int(f.read().strip() or "0")
            except (OSError, ValueError):
                old_pid = 0

            if pid_alive(old_pid):
                return False

            # 锁是死进程留下的 —— 清掉重抢
            try:
                os.remove(path)
            except OSError:
                pass
            continue

        try:
            os.write(fd, str(os.getpid()).encode())
        finally:
            os.close(fd)
        return True

    return False
