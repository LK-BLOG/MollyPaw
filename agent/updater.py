"""自动更新 —— 查 GitHub Release、下载、替换自身。

设计要点（都是踩过坑才这么写的）：

1. **弹窗确认，不静默升级**。用户要求"默认弹窗确认"，而且要把更新内容
   （CHANGELOG 正文，也就是 Release notes）一并展示出来，让人知道自己在升什么。

2. **下载进度推到左下角**。下载是后台线程，进度通过 events 队列
   （`_onUpdateProgress`）推给前端，前端画一条固定左下角的进度条。

3. **替换自身只能用批处理接力**。Windows 上跑着的 exe 不能覆盖自己，
   标准做法是：起一个 .bat，等本进程退出 → 改名旧 exe → 覆盖 → 启动新 exe。
   PyInstaller onefile 的 exe 路径就是 sys.executable。

4. **只有 frozen（打包后）才允许自替换**。源码跑的时候没有 exe 可换，
   直接告诉用户走 git pull，别假装能更新。
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.request

from agent.version import APP_VERSION, GITHUB_REPO, is_newer, version_tuple

API_URL = "https://api.github.com/repos/%s/releases?per_page=20" % GITHUB_REPO
UA = "MollyPaw-Updater/1.0 (+https://github.com/%s)" % GITHUB_REPO

_lock = threading.Lock()
_state = {
    "downloading": False,
    "ready": None,      # 下载好的文件路径
    "latest": None,
    "asset_name": None,
    "progress": 0,
    "error": None,
}


def current_version():
    return APP_VERSION


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def _http_get(url, timeout=10, headers=None):
    req = urllib.request.Request(url, headers=dict({"User-Agent": UA}, **(headers or {})))
    # urllib 在 Windows 上会自动读注册表里的系统代理；环境变量优先。
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _pick_release(releases):
    """挑最新一个带 .exe 资产的 release。

    跳过 draft；prerelease 要，因为我们自己发的 beta 就是 prerelease。
    """
    best = None
    for rel in releases or []:
        if rel.get("draft"):
            continue
        tag = rel.get("tag_name") or ""
        asset = None
        for item in rel.get("assets") or []:
            name = (item.get("name") or "").lower()
            if name.endswith(".exe"):
                asset = item
                break
        if asset is None:
            continue
        version = tag
        for prefix in ("beta-", "Beta-", "v", "V"):
            if version.startswith(prefix):
                version = version[len(prefix):]
                break
        if best is None or version_tuple(version) > version_tuple(best["version"]):
            best = {
                "tag": tag,
                "version": version,
                "notes": rel.get("body") or "",
                "published_at": rel.get("published_at") or "",
                "html_url": rel.get("html_url") or "",
                "asset": {
                    "name": asset.get("name") or "",
                    "size": asset.get("size") or 0,
                    "url": asset.get("browser_download_url") or "",
                },
            }
    return best


def check(timeout=10):
    """查有没有新版本。永远不抛异常 —— 更新检查失败不该影响主功能。"""
    result = {
        "ok": False,
        "current": current_version(),
        "latest": None,
        "available": False,
        "notes": "",
        "tag": "",
        "asset": None,
        "frozen": is_frozen(),
        "error": "",
    }
    try:
        raw = _http_get(API_URL, timeout=timeout, headers={"Accept": "application/vnd.github+json"})
        releases = json.loads(raw.decode("utf-8", "replace"))
        picked = _pick_release(releases)
        if not picked:
            result["error"] = "没找到带安装包的 Release"
            return result
        result.update({
            "ok": True,
            "latest": picked["version"],
            "tag": picked["tag"],
            "notes": picked["notes"],
            "published_at": picked["published_at"],
            "html_url": picked["html_url"],
            "asset": picked["asset"],
            "available": is_newer(picked["version"]),
        })
        with _lock:
            _state["latest"] = picked["version"]
            _state["asset_name"] = picked["asset"]["name"]
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        return result


def download_dir():
    base = os.path.join(tempfile.gettempdir(), "MollyPaw-update")
    os.makedirs(base, exist_ok=True)
    return base


def download(asset_url, filename, on_progress=None):
    """流式下载到临时目录，返回本地路径。"""
    dest = os.path.join(download_dir(), filename or "MollyPaw.exe")
    part = dest + ".part"
    req = urllib.request.Request(asset_url, headers={"User-Agent": UA})
    with _lock:
        _state["downloading"] = True
        _state["progress"] = 0
        _state["error"] = None
        _state["ready"] = None

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(part, "wb") as f:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    pct = int(done * 100 / total) if total else 0
                    with _lock:
                        _state["progress"] = pct
                    if on_progress:
                        try:
                            on_progress(pct, done, total)
                        except Exception:
                            pass
        os.replace(part, dest)
        with _lock:
            _state["downloading"] = False
            _state["progress"] = 100
            _state["ready"] = dest
        return dest
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _state["downloading"] = False
            _state["error"] = str(exc)
        try:
            if os.path.exists(part):
                os.remove(part)
        except Exception:
            pass
        raise


def state():
    with _lock:
        return dict(_state)


def _swap_bat(target_exe, new_exe, pid):
    """生成接力批处理：等本进程退出 -> 换文件 -> 启动新版本。"""
    bat = os.path.join(download_dir(), "apply_update.bat")
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "rem 等旧进程退出（最多 30 秒）",
        "set /a tries=0",
        ":wait",
        "tasklist /FI \"PID eq %d\" 2>nul | find \"%d\" >nul" % (pid, pid),
        "if errorlevel 1 goto swap",
        "set /a tries+=1",
        "if %tries% GEQ 150 goto swap",
        "timeout /t 1 /nobreak >nul 2>nul || ping -n 2 127.0.0.1 >nul",
        "goto wait",
        ":swap",
        "move /y \"%s\" \"%s.old\" >nul 2>nul" % (target_exe, target_exe),
        "copy /y \"%s\" \"%s\" >nul 2>nul" % (new_exe, target_exe),
        "if errorlevel 1 (",
        "  move /y \"%s.old\" \"%s\" >nul 2>nul" % (target_exe, target_exe),
        "  echo update failed > \"%s.failed\"" % target_exe,
        ") else (",
        "  del /q \"%s.old\" >nul 2>nul" % target_exe,
        "  start \"\" \"%s\"" % target_exe,
        ")",
        "del /q \"%%~f0\" >nul 2>nul",
        "",
    ]
    with open(bat, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines))
    return bat


def apply_update():
    """用已下载的 exe 替换当前进程。成功返回 True 后调用方应退出程序。"""
    import subprocess  # noqa: F401  (保持与其他模块一致的可读性)

    st = state()
    new_exe = st.get("ready")
    if not new_exe or not os.path.exists(new_exe):
        return False, "还没下载好新版本"
    if not is_frozen():
        return False, "源码运行模式不支持自替换，请用 git pull 更新"
    target = sys.executable
    if not target.lower().endswith(".exe"):
        return False, "当前不是 Windows 安装包，跳过自替换"

    bat = _swap_bat(target, new_exe, os.getpid())
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | \
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    subprocess.Popen(
        ["cmd", "/c", bat],
        close_fds=True,
        creationflags=flags,
        cwd=download_dir(),
    )
    return True, ""


def start_download_async(asset_url, filename, progress_cb=None, done_cb=None):
    """后台下载（前端用）。回调都在工作线程里触发。"""

    def worker():
        try:
            path = download(asset_url, filename, on_progress=progress_cb)
            if done_cb:
                done_cb(path, None)
        except Exception as exc:  # noqa: BLE001
            if done_cb:
                done_cb(None, exc)

    t = threading.Thread(target=worker, name="mollypaw-update", daemon=True)
    t.start()
    return t
