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


def test_kill_process_tree_kills_real_process():
    import subprocess

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
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
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        "print(p.pid,flush=True);"
        "time.sleep(30)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        child_pid = int(proc.stdout.readline().strip())
        assert kill_process_tree(proc.pid) is True
        proc.wait(timeout=5)
        time.sleep(0.6)
        # 子进程应该也没了
        assert not _pid_alive(child_pid), "grandchild survived the kill"
    finally:
        if proc.poll() is None:
            proc.kill()


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
