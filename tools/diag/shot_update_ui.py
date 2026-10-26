"""用假后端截「自动更新弹窗 + 左下角进度条 + 工具调用历史」的实际渲染。

为什么不用真 app：真 app 正被用户开着，而且更新弹窗只有在真检测到新版本时
才出现。这里用一个最小 HTTP 服务喂假数据，验证前端渲染是否正常。

用法：python tools/diag/shot_update_ui.py
输出：shots/update_modal.png、shots/update_progress.png、shots/tool_history.png
"""
import base64
import importlib.util
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND = os.path.join(ROOT, "frontend")
PORT = 18871
SHOTS = os.path.join(ROOT, "shots")

NOTES = """## [0.0.0.2.1] - 2026-10-24

### 新增

- **自动更新**：启动检查新版本，弹窗列出更新内容，确认后左下角显示下载进度
- **会话历史里的工具调用会完整显示**（工具名、参数、结果，可折叠）
- **中继连接自动选路**：自动探测系统代理，代理/直连并发竞速

### 修复

- **中继没连上也能生成配对码**：界面照样给二维码，手机扫了一直等不到响应
- **桌面端连官方中继无限重连**：不读 Windows 系统代理，裸连时 TLS 握手超时

### 下载

- `MollyPaw.exe`（Windows）
"""

EVENTS = []
EVENTS_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            return self._file(os.path.join(FRONTEND, "index.html"), "text/html; charset=utf-8")
        if p in ("/app.js", "/style.css", "/marked.min.js"):
            ctype = "text/css" if p.endswith(".css") else "application/javascript"
            return self._file(os.path.join(FRONTEND, p.lstrip("/")), ctype)
        if p == "/api/events":
            with EVENTS_LOCK:
                batch = list(EVENTS)
                EVENTS.clear()
            return self._json({"ok": True, "events": batch})
        if p == "/api/update/check":
            return self._json({
                "ok": True, "current": "0.0.0.2.0", "latest": "0.0.0.2.1",
                "available": True, "tag": "beta-0.0.0.2.1", "notes": NOTES,
                "published_at": "2026-10-24T12:00:00Z",
                "html_url": "https://github.com/LK-BLOG/MollyPaw/releases",
                "asset": {"name": "MollyPaw.exe", "size": 31500000,
                          "url": "https://example.invalid/MollyPaw.exe"},
                "frozen": True, "error": "",
            })
        if p == "/api/processes":
            # 默认没有后台进程；?demo=1 时喂两条，给截图用
            if "demo=1" in self.path:
                return self._json({
                    "ok": True, "count": 2, "items": [
                        {"pid": 20168,
                         "cmd": "powershell -NoProfile -Command gradlew.bat assembleRelease",
                         "alive": True, "age_seconds": 96, "exit_code": None,
                         "killed_by": None, "stdout": "> Task :app:compileReleaseKotlin",
                         "stderr": ""},
                        {"pid": 18444, "cmd": "python tools/fetch_releases.py",
                         "alive": True, "age_seconds": 21, "exit_code": None,
                         "killed_by": None, "stdout": "", "stderr": ""},
                    ],
                })
            return self._json({"ok": True, "count": 0, "items": []})
        if p == "/api/version":
            return self._json({"ok": True, "version": "0.0.0.2.0"})
        if p == "/api/relay/available":
            return self._json({"ok": True, "available": True, "error": ""})
        if p == "/api/relay/status":
            return self._json({
                "ok": True, "running": True, "connected": True, "state": "connected",
                "room": "cfec772d9fdb587e929f1352814852e8", "psk_set": True,
                "proxy": "auto", "proxy_active": "127.0.0.1:7897", "devices": 1,
            })
        if p == "/api/relay/settings":
            return self._json({
                "ok": True, "url": "wss://mollypaw-online.pages.dev/server",
                "psk": "MollyPawDemoKey123456", "psk_set": True, "psk_problems": [],
                "auto_start": True, "room": "cfec772d9fdb587e929f1352814852e8",
                "running": True, "connected": True, "state": "connected",
            })
        if p in ("/api/relay/devices",):
            return self._json({"ok": True, "devices": []})
        if p in ("/api/relay/pin",):
            return self._json({"ok": True, "pin": None})
        if p in ("/api/relay/audit",):
            return self._json({"ok": True, "entries": []})
        if p in ("/api/busy", "/api/state", "/api/status", "/api/config"):
            return self._json({"ok": True, "busy": False, "owner": None})
        if p.startswith("/api/conversations"):
            return self._json({"ok": True, "conversations": [
                {"id": "demo", "title": "演示会话", "updated_at": time.time()},
            ]})
        return self._json({"ok": True})

    def do_POST(self):
        p = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if p == "/api/update/download":
            def feed():
                for pct in (0, 8, 21, 37, 52, 66, 78, 89, 96, 100):
                    time.sleep(0.3)
                    with EVENTS_LOCK:
                        EVENTS.append({
                            "name": "_onUpdateProgress",
                            "payload": {"percent": pct,
                                        "done": pct * 315000,
                                        "total": 31500000},
                        })
                time.sleep(0.3)
                with EVENTS_LOCK:
                    EVENTS.append({
                        "name": "_onUpdateReady",
                        "payload": {"path": "C:/tmp/MollyPaw.exe", "frozen": True},
                    })

            threading.Thread(target=feed, daemon=True).start()
            return self._json({"ok": True, "started": True})
        return self._json({"ok": True})


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


TOOL_HISTORY_JS = r"""
document.getElementById('update-later').click();
window._onLoadConversationResult({ok:true, conversation:{id:'demo', title:'演示',
  messages:[
    {role:'user', content:'帮我看下项目里有哪些 py 文件'},
    {role:'assistant', content:'', tool_calls:[{id:'call_1', type:'function',
      function:{name:'shell', arguments:'{"command":"ls *.py","cwd":"D:\\\\MollyPaw Agent"}'}}]},
    {role:'tool', tool_call_id:'call_1', content:'agent\nmain.py\npet.py\ntools/'},
    {role:'assistant', content:'找到 3 个入口相关文件：`main.py`、`pet.py`、`agent/`。'}
  ]}});
"""


def main():
    srv = serve()
    time.sleep(0.3)
    print(f"mock server on http://127.0.0.1:{PORT}")

    spec = importlib.util.spec_from_file_location(
        "shot_settings", os.path.join(ROOT, "tools", "shot_settings.py")
    )
    shot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shot)

    browser = shot.find_browser()
    if not browser:
        print("找不到 Edge/Chrome")
        return 1

    proc, profile, ws_url = shot.launch(browser)
    if not ws_url:
        print("浏览器起不来")
        return 1

    ws = shot.MiniWS(ws_url)
    os.makedirs(SHOTS, exist_ok=True)

    def snap(name):
        res = ws.call("Page.captureScreenshot", {"format": "png"})
        data = (res.get("result") or {}).get("data")
        if not data:
            print(f"  截图失败: {name}")
            return
        path = os.path.join(SHOTS, name)
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        print(f"  截图 -> {path}")

    def js(expr):
        return ws.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True})

    try:
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        ws.call("Emulation.setEmulatedMedia", {
            "features": [{"name": "prefers-reduced-motion", "value": "no-preference"}],
        })
        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{PORT}/"})
        time.sleep(4.5)
        snap("update_modal.png")

        js("document.getElementById('update-now').click()")
        time.sleep(2.2)
        snap("update_progress.png")

        js(TOOL_HISTORY_JS)
        time.sleep(1.2)
        snap("tool_history.png")
    finally:
        try:
            ws.close()
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
