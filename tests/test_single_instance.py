"""MollyPaw — 单实例锁测试。

背景：这个锁之前"看起来有"，实际没挡住第二个实例 —— 用户手动开着旧进程，
我又起了一个新的，结果新的没退、旧的还占着 18765 端口，测了半天旧代码。

第二个坑（更毒，2026-10 再次实测）：探活用 `os.kill(pid, 0)` 在 Windows 上
是**广播 Ctrl+C**（signal.CTRL_C_EVENT == 0），不是探活 ——
第二个实例会把第一个实例和整个控制台一起 Ctrl+C 掉。
这里用 `pid_alive` 钉住"探活不许给目标发信号"。

测试**直接 import 真模块**（agent/single_instance.py），
不再手抄一份逻辑 —— 抄的会漂。
"""
import os
import subprocess
import sys
import tempfile
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.single_instance import check_single_instance, pid_alive  # noqa: E402

# 探针：在**独立进程**里抢锁，用来模拟"另一个 MollyPaw 实例"。
PROBE = """
import sys
sys.path.insert(0, {root!r})
from agent.single_instance import check_single_instance

ok = check_single_instance({lock!r})
print("ACQUIRED" if ok else "BLOCKED", flush=True)
{sleep}
"""


@pytest.fixture
def lockpath():
    path = os.path.join(
        tempfile.gettempdir(),
        "MollyPawTest_{}_{}.lock".format(os.getpid(), int(time.time() * 1000)),
    )
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


def write_probe(tmp_path, lockpath, name="probe.py", sleep=0):
    body = PROBE.format(
        root=ROOT,
        lock=lockpath,
        sleep="import time; time.sleep({})".format(sleep) if sleep else "",
    )
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


def run_probe(probe, timeout=30):
    proc = subprocess.run(
        [sys.executable, probe],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.stdout.strip()


def spawn_holder(tmp_path, lockpath, name="holder.py", sleep=4):
    """起一个持锁进程，返回 (Popen, 实际持锁的 pid)。

    **注意**：Windows 商店版 Python 的 python.exe 是个启动器，会再拉起
    真正的解释器，所以 Popen().pid 不等于写进锁文件的 pid。
    这里让 holder 自己把 pid 打出来，避免拿到启动器 pid 后清理不掉。
    """
    body = PROBE.format(
        root=ROOT,
        lock=lockpath,
        sleep=(
            'print("PID", __import__("os").getpid(), flush=True)\n'
            "import time; time.sleep({})".format(sleep)
        ),
    )
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(path)],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout.readline().strip() == "ACQUIRED", "holder 没拿到锁"
    line = proc.stdout.readline().strip()
    real_pid = int(line.split()[1]) if line.startswith("PID") else proc.pid
    return proc, real_pid


def _kill_pid(pid):
    """清理用：真死（Windows 走 taskkill，不用 os.kill(pid, 0)）。"""
    if not pid:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        import signal

        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


# --------------------------------------------------------------------------
# pid_alive：只能探活，不许动目标
# --------------------------------------------------------------------------


def test_pid_alive_sees_current_process():
    assert pid_alive(os.getpid()) is True


def test_pid_alive_rejects_garbage():
    assert pid_alive(0) is False
    assert pid_alive(-1) is False
    assert pid_alive(None) is False
    assert pid_alive("not-a-pid") is False


def test_pid_alive_returns_false_for_dead_pid():
    proc = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc.wait(timeout=30)
    assert pid_alive(proc.pid) is False


def test_pid_alive_does_not_kill_the_target(tmp_path):
    """核心回归：探活**不能**把目标进程干掉。

    这就是 os.kill(pid, 0) 在 Windows 上的行为 —— 广播 Ctrl+C。
    老实现会让"第二个实例"顺手杀死第一个实例。
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(8)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.3)
        assert pid_alive(proc.pid) is True
        time.sleep(0.3)
        assert proc.poll() is None, "pid_alive 把目标进程弄死了（Windows 上是 Ctrl+C 广播）"
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


# --------------------------------------------------------------------------
# 抢锁
# --------------------------------------------------------------------------


def test_first_instance_acquires_lock(lockpath):
    assert check_single_instance(lockpath) is True
    assert os.path.exists(lockpath)


def test_lock_file_contains_own_pid(lockpath):
    check_single_instance(lockpath)
    # 进程退出后锁还在（这是设计：靠 pid 存活判断，不靠自动释放）
    with open(lockpath, encoding="utf-8") as f:
        assert f.read().strip() == str(os.getpid())


def test_stale_lock_from_dead_pid_is_recovered(lockpath):
    """写一个不存在的 pid，下一个实例必须能接管。"""
    with open(lockpath, "w", encoding="utf-8") as f:
        f.write("999999999")
    assert check_single_instance(lockpath) is True
    with open(lockpath, encoding="utf-8") as f:
        assert f.read().strip() == str(os.getpid())


def test_corrupt_lock_is_recovered(lockpath):
    with open(lockpath, "w", encoding="utf-8") as f:
        f.write("这不是 pid")
    assert check_single_instance(lockpath) is True


def test_second_live_instance_is_blocked(tmp_path, lockpath):
    """核心断言：持锁进程还活着时，第二个实例必须退让。"""
    holder, real_pid = spawn_holder(tmp_path, lockpath)
    try:
        assert check_single_instance(lockpath) is False
        # 而且持锁者必须还活着 —— 不能为了"抢锁"把人干掉
        assert pid_alive(real_pid) is True, "第二次抢锁把第一个实例弄死了"
    finally:
        holder.kill()
        holder.wait(timeout=10)
        _kill_pid(real_pid)


def test_lock_released_after_holder_dies(tmp_path, lockpath):
    """持锁进程死掉后，新实例必须能接管（否则用户重启一次就永远打不开）。"""
    holder, real_pid = spawn_holder(tmp_path, lockpath)
    holder.kill()
    holder.wait(timeout=10)
    _kill_pid(real_pid)
    time.sleep(0.5)
    assert check_single_instance(lockpath) is True, "死进程的锁没被回收"


# --------------------------------------------------------------------------
# 真实 main.py 的接线：这层测试防的是"锁存在但没接上"
# --------------------------------------------------------------------------


def test_main_calls_single_instance_check():
    """main.py 必须在启动早期真的调用锁检查并退出。"""
    source = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert "check_single_instance" in source, "锁检查没了"
    assert "if not check_single_instance():" in source, "锁检查没被调用"
    assert "sys.exit(0)" in source, "抢不到锁时必须退出"

    # 调用必须发生在 import webview 之前，否则会先启 GUI 再退出
    lock_call = source.index("if not check_single_instance():")
    # 用带换行的精确匹配 —— 注释里也出现了 "import webview" 这几个字，
    # 直接 index("import webview") 会匹配到注释（踩过）。
    webview_import = source.index("\nimport webview\n")
    assert lock_call < webview_import, "锁检查太晚，GUI 已经起来了"


def test_lock_path_is_in_tempdir():
    from agent import single_instance

    assert single_instance.LOCK_PATH.endswith("MollyPaw.lock")
    assert "tempfile.gettempdir()" in open(
        single_instance.__file__, encoding="utf-8"
    ).read()
