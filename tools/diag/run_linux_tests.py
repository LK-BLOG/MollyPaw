"""在 Linux（WSL）里跑主仓库的测试，模拟 CI 的 Ubuntu runner。

为什么要专门跑这个：
CI 的 Ubuntu runner 上，pywebview 在 **import 时**就探测 X display，
没有 display 就抛 Xlib.error.DisplayNameError。
本地 Windows 没这问题，所以必须真的在 Linux 上验一遍。

用法（在 Windows 上跑）：
    wsl bash -c "cd '/mnt/d/MollyPaw Agent' && python3 tools/diag/run_linux_tests.py"
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
RELAY = "/mnt/d/MollyPaw-Relay"


def run(cmd, cwd=None):
    print(f"$ {cmd}")
    proc = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    print(out[-4000:])
    return proc.returncode


def main():
    print(f"仓库: {ROOT}")
    print(f"python: {sys.executable}")

    # 依赖检查
    rc = run("python3 -c 'import pytest, websockets, cryptography; print(\"deps ok\")'")
    if rc != 0:
        print("\n缺依赖，尝试装（Arch 的 pacman）")
        run("sudo pacman -S --needed --noconfirm python-pytest python-websockets "
            "python-cryptography || true")
        rc = run("python3 -c 'import pytest, websockets, cryptography; print(\"deps ok\")'")
        if rc != 0:
            print("依赖仍然缺失，跳过 Linux 验证")
            return 2

    # 造一个可写的隔离数据目录（Linux 上不能用 Windows 的 %APPDATA%）
    data_dir = "/tmp/mollypaw-test-data"
    os.makedirs(data_dir, exist_ok=True)

    # 路径里有空格（MollyPaw Agent），必须加引号 ——
    # 否则 shell 会把 "MollyPaw" 和 "Agent:..." 当成两个参数。
    env_prefix = (
        f"MOLLYPAW_DATA_DIR='{data_dir}' "
        f"PYTHONPATH='{ROOT}:{RELAY}' "
    )

    print("\n=== 跑关键测试（不联网）===")
    rc = run(
        env_prefix + "python3 -m pytest tests/ -q -m 'not network' "
        "--tb=short -p no:cacheprovider",
        cwd=ROOT,
    )
    return rc


if __name__ == "__main__":
    sys.exit(main())
