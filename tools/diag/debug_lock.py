"""诊断单实例锁：把每一步写进文件，避免依赖 stdout 管道。

跑法：& D:\\MollyPaw Agent\\.venv\\Scripts\\python.exe tools\\debug_lock.py
"""
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = os.path.join(tempfile.gettempdir(), "mollypaw_lock_debug.log")


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.time():.3f} pid={os.getpid()} {msg}\n")


HOLDER = r'''
import os, sys, time
lock = sys.argv[1]
out = sys.argv[2]
with open(out, "a", encoding="utf-8") as f:
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        f.write("HOLDER_ACQUIRED pid=%d\n" % os.getpid())
        f.flush()
        time.sleep(30)
    except FileExistsError:
        f.write("HOLDER_BLOCKED\n")
        f.flush()
'''

PROBE = r'''
import os, sys
lock = sys.argv[1]
out = sys.argv[2]
with open(out, "a", encoding="utf-8") as f:
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        f.write("PROBE_ACQUIRED pid=%d\n" % os.getpid())
        f.flush()
    except FileExistsError:
        try:
            with open(lock) as g:
                old = int(g.read().strip())
            f.write("PROBE read old_pid=%d\n" % old)
            f.flush()
            os.kill(old, 0)
            f.write("PROBE os.kill ok -> BLOCKED\n")
            f.flush()
        except Exception as e:
            f.write("PROBE os.kill raised %s: %s -> would delete+retry\n"
                    % (type(e).__name__, e))
            f.flush()
'''


def main():
    if os.path.exists(LOG):
        os.remove(LOG)
    lock = os.path.join(tempfile.gettempdir(), "MollyPawDebug.lock")
    try:
        os.remove(lock)
    except OSError:
        pass

    log("=== start ===")
    log(f"sys.executable = {sys.executable}")

    holder_py = os.path.join(tempfile.gettempdir(), "mp_holder.py")
    probe_py = os.path.join(tempfile.gettempdir(), "mp_probe.py")
    open(holder_py, "w", encoding="utf-8").write(HOLDER)
    open(probe_py, "w", encoding="utf-8").write(PROBE)

    # 不用 PIPE，直接继承 stdout（避免管道带来的任何干扰）
    h = subprocess.Popen([sys.executable, holder_py, lock, LOG],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log(f"holder launched, Popen.pid = {h.pid}")

    # 等锁文件出现
    for _ in range(100):
        if os.path.exists(lock):
            break
        time.sleep(0.05)
    time.sleep(0.5)

    if os.path.exists(lock):
        content = open(lock).read().strip()
        log(f"lock file content = {content!r}")
    else:
        log("lock file 没出现")

    log(f"holder.poll() = {h.poll()}  (None 表示还活着)")

    p = subprocess.run([sys.executable, probe_py, lock, LOG],
                       capture_output=True, text=True, timeout=20)
    log(f"probe rc={p.returncode} out={p.stdout!r} err={p.stderr!r}")

    log(f"after probe: holder.poll() = {h.poll()}")

    try:
        h.kill()
        h.wait(timeout=5)
    except Exception as e:
        log(f"kill holder failed: {e}")

    log("=== done ===")
    print(open(LOG, encoding="utf-8").read())
    return 0


if __name__ == "__main__":
    sys.exit(main())
