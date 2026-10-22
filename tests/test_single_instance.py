"""MollyPaw — 单实例锁测试。

背景：这个锁之前"看起来有"，实际没挡住第二个实例 —— 用户手动开着旧进程，
我又起了一个新的，结果新的没退、旧的还占着 18765 端口，测了半天旧代码。

锁写在 `main.py` 模块顶层（import 时执行），所以这里**不能直接 import main**，
否则跑测试自身就被锁挡掉。做法：把锁的实现抽出来单独测。
"""
import os
import subprocess
import sys
import tempfile
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 直接从 main.py 里把锁逻辑抠出来测 —— 保持与生产代码一致
LOCK_SOURCE = '''
import os
import tempfile

_LOCK_PATH = os.path.join(tempfile.gettempdir(), "{lock_name}")

def _check_single_instance():
    try:
        fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            with open(_LOCK_PATH, "r") as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            return False
        except Exception:
            try:
                os.remove(_LOCK_PATH)
            except Exception:
                pass
            return _check_single_instance()

if __name__ == "__main__":
    print("ACQUIRED" if _check_single_instance() else "BLOCKED")
'''


@pytest.fixture
def lockname():
    name = f"MollyPawTest_{os.getpid()}_{int(time.time()*1000)}.lock"
    yield name
    path = os.path.join(tempfile.gettempdir(), name)
    try:
        os.remove(path)
    except OSError:
        pass


def write_probe(tmp_path, lockname):
    path = tmp_path / "probe.py"
    path.write_text(LOCK_SOURCE.format(lock_name=lockname), encoding="utf-8")
    return str(path)


def run_probe(probe, timeout=20):
    """跑一个探针进程，返回它的 stdout。"""
    proc = subprocess.run(
        [sys.executable, probe],
        capture_output=True, text=True, timeout=timeout,
    )
    return proc.stdout.strip()


def test_first_instance_acquires_lock(tmp_path, lockname):
    probe = write_probe(tmp_path, lockname)
    assert run_probe(probe) == "ACQUIRED"


def test_lock_file_contains_pid(tmp_path, lockname):
    probe = write_probe(tmp_path, lockname)
    run_probe(probe)
    path = os.path.join(tempfile.gettempdir(), lockname)
    assert os.path.exists(path)
    # 进程退出后锁还在（这是设计：靠 pid 存活判断，不靠自动释放）
    content = open(path).read().strip()
    assert content.isdigit()


def test_stale_lock_from_dead_pid_is_recovered(tmp_path, lockname):
    """写一个不存在的 pid，下一个实例必须能接管。"""
    path = os.path.join(tempfile.gettempdir(), lockname)
    with open(path, "w") as f:
        f.write("999999999")  # 几乎不可能存在的 pid
    probe = write_probe(tmp_path, lockname)
    assert run_probe(probe) == "ACQUIRED"


def test_second_live_instance_is_blocked(tmp_path, lockname):
    """核心断言：持锁进程还活着时，第二个实例必须退让。

    用探针改成"拿到锁就睡 8 秒"，这样窗口足够长，能可靠观察。
    """
    holder_src = LOCK_SOURCE.replace(
        'print("ACQUIRED" if _check_single_instance() else "BLOCKED")',
        'ok = _check_single_instance()\n'
        '    print("ACQUIRED" if ok else "BLOCKED", flush=True)\n'
        '    import time as _t\n'
        '    _t.sleep(8)'
    )
    holder = tmp_path / "holder.py"
    holder.write_text(holder_src.format(lock_name=lockname), encoding="utf-8")

    h = subprocess.Popen(
        [sys.executable, str(holder)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        first = h.stdout.readline().strip()
        assert first == "ACQUIRED", f"holder failed to acquire: {first}"

        # 持锁者还活着，第二个必须被挡
        probe = write_probe(tmp_path, lockname)
        second = run_probe(probe)
        assert second == "BLOCKED", (
            f"第二个实例竟然拿到了锁（返回 {second!r}）—— 单实例锁没生效"
        )
    finally:
        h.kill()
        h.wait(timeout=5)


def test_lock_released_after_holder_dies(tmp_path, lockname):
    """持锁进程死掉后，新实例必须能接管（否则用户重启一次就永远打不开）。"""
    holder_src = LOCK_SOURCE.replace(
        'print("ACQUIRED" if _check_single_instance() else "BLOCKED")',
        'ok = _check_single_instance()\n'
        '    print("ACQUIRED" if ok else "BLOCKED", flush=True)\n'
        '    import time as _t\n'
        '    _t.sleep(30)'
    )
    holder = tmp_path / "holder2.py"
    holder.write_text(holder_src.format(lock_name=lockname), encoding="utf-8")

    h = subprocess.Popen(
        [sys.executable, str(holder)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert h.stdout.readline().strip() == "ACQUIRED"
        h.kill()
        h.wait(timeout=5)
        time.sleep(0.5)

        probe = write_probe(tmp_path, lockname)
        assert run_probe(probe) == "ACQUIRED", "死进程的锁没被回收"
    finally:
        if h.poll() is None:
            h.kill()


# --------------------------------------------------------------------------
# 真实 main.py 的锁：这层测试防的是"锁存在但没接上"
# --------------------------------------------------------------------------


def test_main_actually_calls_single_instance_check():
    """main.py 必须在启动早期真的调用锁检查并退出。"""
    source = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert "_check_single_instance" in source, "锁函数没了"
    assert "if not _check_single_instance():" in source, "锁检查没被调用"
    # 调用必须发生在 import webview 之前，否则会先启 GUI 再退出
    lock_call = source.index("if not _check_single_instance():")
    webview_import = source.index("import webview")
    assert lock_call < webview_import, "锁检查太晚，GUI 已经起来了"


def test_lock_path_is_in_tempdir():
    source = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert "MollyPaw.lock" in source
    assert "tempfile.gettempdir()" in source
