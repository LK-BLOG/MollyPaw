"""POSIX 下的 kill_process_tree 行为验证（可在 Linux/WSL 上直接跑）。

背景：CI 的 Ubuntu/macOS runner 上 pytest 跑到第 18 个测试就整体被杀（exit 143）。
根因：POSIX 分支无条件 `os.killpg(os.getpgid(pid), SIGTERM)`，
而目标进程没独立成组时，getpgid 拿到的是**父进程自己的组** ——
一发信号，父进程（pytest / 你的应用）跟着一起死。

这个脚本在 Linux/WSL 上验证修复后的行为：
  1. 目标与自己同组 → 只能杀单个进程，自己必须活着
  2. 目标独立成组   → 整组被杀（这是想要的行为：连子进程一起清）
  3. 孙子进程也要死

用法：python tools/diag/verify_kill_posix.py
"""
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from agent.cancel import kill_process_tree  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append((name, detail))
        print(f"  [FAIL] {name} :: {detail}")


def alive(pid):
    """进程是否还活着。

    注意：不能用 `os.kill(pid, 0)` 单独判断 —— 父进程没 wait 回收时
    目标会变成僵尸，此时 os.kill 仍然成功，看起来"还活着"。
    可靠判据是 poll()：负数表示已被信号杀死。
    """
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def proc_gone(proc):
    """进程是否真的终止了（poll() 返回非 None）。"""
    return proc.poll() is not None


def main():
    if os.name == "nt":
        print("这个脚本要在 Linux/macOS 上跑（Windows 走 taskkill 分支）")
        return 2

    print("=== 1. 目标与自己同组：不能连自己一起杀 ===")
    # 故意不用 start_new_session
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(20)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    own_group = os.getpgid(0)
    try:
        target_group = os.getpgid(proc.pid)
        check("目标与自己同组（复现危险场景）", target_group == own_group,
              f"own={own_group} target={target_group}")
        check("调用返回 True", kill_process_tree(proc.pid) is True)
        time.sleep(0.3)
        check("调用后自己还活着", os.getpgid(0) == own_group)
    finally:
        if proc.poll() is None:
            proc.kill()

    print("\n=== 2. 目标独立成组：整组应该被杀 ===")
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(20)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        target_group = os.getpgid(proc.pid)
        check("目标独立成组", target_group != own_group,
              f"own={own_group} target={target_group}")
        check("调用返回 True", kill_process_tree(proc.pid) is True)
        time.sleep(0.5)
        check("目标被杀了", proc_gone(proc), f"poll()={proc.poll()}")
    finally:
        if proc.poll() is None:
            proc.kill()

    print("\n=== 3. 孙子进程也要死 ===")
    script = (
        "import subprocess,sys,time;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)']);"
        "print(p.pid,flush=True);"
        "time.sleep(20)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        start_new_session=True,
    )
    try:
        child_pid = int(proc.stdout.readline().strip())
        check("拿到孙子 pid", child_pid > 0)
        check("调用返回 True", kill_process_tree(proc.pid) is True)
        time.sleep(0.8)
        check("孙子进程也死了", not alive(child_pid))
    finally:
        if proc.poll() is None:
            proc.kill()

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for name, detail in FAIL:
        print(f"  FAIL: {name} :: {detail}")
    print("=" * 56)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
