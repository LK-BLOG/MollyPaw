"""MollyPaw — 取消令牌与流式可中断测试。"""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.cancel import (
    CancelToken,
    CancelledError,
    current_token,
    kill_process_tree,
    use_token,
)


# --------------------------------------------------------------------------
# CancelToken
# --------------------------------------------------------------------------


def test_token_starts_clean():
    t = CancelToken()
    assert not t.cancelled
    assert t.reason == ""


def test_cancel_sets_state():
    t = CancelToken()
    assert t.cancel("user") is True
    assert t.cancelled
    assert t.reason == "user"


def test_cancel_is_idempotent():
    t = CancelToken()
    assert t.cancel("first") is True
    assert t.cancel("second") is False
    assert t.reason == "first"  # 第一次的原因保留


def test_raise_if_cancelled():
    t = CancelToken()
    t.raise_if_cancelled()  # 不抛
    t.cancel()
    with pytest.raises(CancelledError):
        t.raise_if_cancelled()


def test_reset_is_forbidden_by_design():
    """取消是单向的 —— 故意不提供复位。"""
    t = CancelToken()
    with pytest.raises(NotImplementedError):
        t.reset()


def test_wait_returns_on_cancel():
    t = CancelToken()

    def _cancel():
        time.sleep(0.05)
        t.cancel()

    threading.Thread(target=_cancel, daemon=True).start()
    assert t.wait(timeout=2) is True


def test_wait_times_out():
    t = CancelToken()
    assert t.wait(timeout=0.05) is False


def test_child_cancelled_with_parent():
    parent = CancelToken()
    child = parent.child()
    parent.cancel("stop")
    assert child.cancelled
    assert child.reason == "stop"


def test_child_created_after_parent_cancel():
    """父已取消时新建的子令牌必须立即也是取消态。"""
    parent = CancelToken()
    parent.cancel("gone")
    child = parent.child()
    assert child.cancelled


def test_child_cancel_does_not_affect_parent():
    parent = CancelToken()
    child = parent.child()
    child.cancel("child only")
    assert child.cancelled
    assert not parent.cancelled


def test_grandchild_cascade():
    root = CancelToken()
    mid = root.child()
    leaf = mid.child()
    root.cancel()
    assert mid.cancelled and leaf.cancelled


def test_thread_safety_many_cancels():
    t = CancelToken()
    results = []

    def worker():
        results.append(t.cancel())

    threads = [threading.Thread(target=worker) for _ in range(30)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    # 只有一次 cancel 能返回 True
    assert results.count(True) == 1


# --------------------------------------------------------------------------
# 上下文令牌
# --------------------------------------------------------------------------


def test_context_token_default_none():
    assert current_token() is None


def test_use_token_sets_and_restores():
    t = CancelToken()
    assert current_token() is None
    with use_token(t):
        assert current_token() is t
    assert current_token() is None


def test_use_token_nested():
    outer, inner = CancelToken(), CancelToken()
    with use_token(outer):
        assert current_token() is outer
        with use_token(inner):
            assert current_token() is inner
        assert current_token() is outer
    assert current_token() is None


def test_context_token_is_not_shared_across_threads():
    """线程不应互相串令牌。"""
    t = CancelToken()
    seen = []

    def worker():
        seen.append(current_token())

    with use_token(t):
        th = threading.Thread(target=worker)
        th.start()
        th.join()
        assert current_token() is t
    # 子线程没设过令牌，应该是 None
    assert seen == [None]


# --------------------------------------------------------------------------
# 进程树
# --------------------------------------------------------------------------


def test_kill_process_tree_no_pid():
    assert kill_process_tree(0) is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX 专属：Windows 没有进程组，走 taskkill /T")
def test_kill_process_tree_does_not_kill_own_group():
    """**不能连带杀掉自己这一组**。

    这是个真 bug：POSIX 下无条件 `os.killpg(os.getpgid(pid), SIGTERM)`，
    而目标进程若没独立成组（没带 start_new_session=True），
    getpgid(pid) 返回的就是**父进程（pytest / 你的应用）的组** ——
    一发信号，整个进程连带被杀。

    实测：CI 上 pytest 跑到第 18 个测试就整体退出（exit 143）。
    """
    import subprocess

    # 故意**不**用 start_new_session=True —— 就是要复现"同组"这个危险场景
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        own_group = os.getpgid(0)
        target_group = os.getpgid(proc.pid)
        assert target_group == own_group, "这个测试需要目标与自己同组"

        # 调用不能把整组杀掉 —— 也就是不能把我们自己干掉
        assert kill_process_tree(proc.pid) is True
        # 如果还活着（SIGTERM 没立刻生效）也没关系，重点是"我们还活着"
        time.sleep(0.3)
        assert os.getpgid(0) == own_group
    finally:
        if proc.poll() is None:
            proc.kill()


def test_kill_process_tree_kills_real_process():
    import subprocess

    # 睡 30 秒太长 —— CI 上被 SIGTERM 打断就会挂住整轮测试。
    # 5 秒足够验证"杀掉了"，又不会拖慢。
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert proc.poll() is None
        assert kill_process_tree(proc.pid) is True
        proc.wait(timeout=5)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()


def test_kill_process_tree_kills_children():
    """关键：必须连子进程一起杀（Windows 用 taskkill /T）。"""
    import subprocess

    # 父进程再起一个睡眠子进程
    script = (
        "import subprocess,sys,time;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)']);"
        "print(p.pid,flush=True);"
        "time.sleep(5)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        line = proc.stdout.readline()
        assert line, "子进程没报出 pid"
        child_pid = int(line.strip())
        assert kill_process_tree(proc.pid) is True
        proc.wait(timeout=5)
        time.sleep(0.6)
        # 子进程应该也没了
        assert not _pid_alive(child_pid), "grandchild survived the kill"
    finally:
        if proc.poll() is None:
            proc.kill()
        # 孙子进程可能还活着（如果 taskkill 失败），顺手清掉，
        # 别让它在 CI 机器上挂 5 秒
        try:
            _kill_pid(child_pid)
        except Exception:
            pass


def _kill_pid(pid):
    """尽力杀掉一个 pid（测试清理用）。"""
    import subprocess
    import signal

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def _pid_alive(pid):
    """跨平台检测进程是否还在。"""
    if os.name == "nt":
        import subprocess

        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True,
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
