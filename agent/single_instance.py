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


def focus_existing_window() -> bool:
    """把已经在跑的那个 MollyPaw 窗口提到前台（Windows）。

    纯粹是体验：用户以为程序没启动，其实窗口在后面。做不到就返回 False，
    绝不能让调用方因为这段崩掉。
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        EnumWindows = user32.EnumWindows
        GetWindowTextW = user32.GetWindowTextW
        IsWindowVisible = user32.IsWindowVisible
        SetForegroundWindow = user32.SetForegroundWindow
        ShowWindow = user32.ShowWindow
        GetWindowThreadProcessId = user32.GetWindowThreadProcessId

        # 锁文件里的 pid 就是那个实例
        try:
            with open(LOCK_PATH, "r", encoding="utf-8", errors="replace") as f:
                target_pid = int(f.read().strip() or "0")
        except (OSError, ValueError):
            target_pid = 0

        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _lparam):
            if not IsWindowVisible(hwnd):
                return True
            length = GetWindowTextW(hwnd, None, 0)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if "MollyPaw" not in title:
                return True
            pid = wintypes.DWORD()
            GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if target_pid and pid.value != target_pid:
                return True
            found.append(hwnd)
            return False

        EnumWindows(_enum, 0)
        if not found:
            return False
        hwnd = found[0]
        SW_RESTORE = 9
        ShowWindow(hwnd, SW_RESTORE)
        SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def check_single_instance(lock_path=None) -> bool:
    """抢锁。True = 我是唯一实例；False = 已经有一个活着的实例。

    环境变量 MOLLYPAW_SKIP_SINGLE_INSTANCE=1 时直接放行：
    测试进程要 import main.py，而用户桌面上的 MollyPaw 很可能正开着，
    真去抢锁会让整轮 pytest 被 SystemExit(0) 打断（19 个测试报错）。
    这是**测试专用**逃生口，正常启动永远不会设它。
    """
    if os.environ.get("MOLLYPAW_SKIP_SINGLE_INSTANCE", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        return True

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
