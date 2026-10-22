"""用系统自带的 Edge/Chrome headless 截设置面板的图。

**为什么不用 playwright**：那要往项目里塞 node 依赖、还得下浏览器二进制。
这台机器本来就有 Edge，`--headless --screenshot` 就够了。
项目是纯 Python，工具也用 Python。

用法：
    .venv\\Scripts\\python.exe tools\\shot_ui.py
    .venv\\Scripts\\python.exe tools\\shot_ui.py --url http://127.0.0.1:18765 --out shots
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def find_browser():
    """找一个可用的 Chromium 内核浏览器。"""
    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge",
                     "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge",
                     "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome",
                     "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome",
                     "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome",
                     "Application", "chrome.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    found = shutil.which("msedge") or shutil.which("chrome")
    return found


def shot(browser, url, out_path, size="1180,900", wait_ms=2500, extra_args=None):
    """截一张全页图。返回 (ok, 说明)。"""
    profile = tempfile.mkdtemp(prefix="mp-shot-")
    args = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile}",
        f"--window-size={size}",
        f"--screenshot={out_path}",
        f"--virtual-time-budget={wait_ms}",
        "--hide-scrollbars",
        url,
    ]
    if extra_args:
        args[1:1] = extra_args
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=90)
        ok = os.path.exists(out_path) and os.path.getsize(out_path) > 0
        return ok, (proc.stderr or "")[-400:]
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def http_get(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18765")
    parser.add_argument("--out", default="shots")
    args = parser.parse_args()

    browser = find_browser()
    if not browser:
        print("找不到 Edge/Chrome，无法截图")
        return 1
    print(f"浏览器: {browser}")

    try:
        status, _ = http_get(args.url + "/")
    except Exception as exc:
        print(f"应用没起来（{args.url}）: {exc}")
        return 1
    print(f"应用在线: HTTP {status}")

    os.makedirs(args.out, exist_ok=True)

    # 主界面
    ok, err = shot(browser, args.url, os.path.join(args.out, "01-main.png"))
    print(f"主界面: {'OK' if ok else '失败 ' + err}")

    # 设置面板各标签页：用 JS 打开并切页。Chromium headless 不支持直接注入脚本，
    # 所以走一个本地小页面把目标 URL 用 hash 传进去，由页面自己点。
    # 简单起见：这里只能截默认打开的页面，切页需要在页面上手动点。
    # 设置面板的标签页截图另走 tools/shot_settings.py（用 CDP）。
    print("\n提示：设置面板分页截图请用 tools/shot_settings.py（走 CDP，能点按钮）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
