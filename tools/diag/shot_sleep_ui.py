"""截「设置 → 睡眠」面板：验证空闲分钟数输入真的显示后端值、中英文都对。

背景（都是修过的真 bug）：
  - 以前 `idle_minutes` 在两个地方被硬编码成 0.5 分钟，界面上根本没有入口；
  - 以前有个 `max_llm_calls` 输入框，现在功能删了，界面不能再冒出来。
"""
import base64
import importlib.util
import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHOTS = os.path.join(ROOT, "shots")


def load_shot_tools():
    spec = importlib.util.spec_from_file_location(
        "shot_settings", os.path.join(ROOT, "tools", "shot_settings.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    sys.path.insert(0, os.path.join(ROOT, "tools", "diag"))
    import shot_update_ui as mock

    # 让 mock 的 /api/sleep 返回一份带 idle_minutes 的配置
    original_get = mock.Handler.do_GET

    def patched_get(self):
        if self.path.split("?")[0] == "/api/sleep":
            return self._json({
                "ok": True,
                "sleep": {"mode": "full", "tasks": ["memory", "review", "dream"],
                          "idle_minutes": 30},
                "status": {"state": "awake", "idle_minutes": 30},
            })
        return original_get(self)

    mock.Handler.do_GET = patched_get

    srv = ThreadingHTTPServer(("127.0.0.1", mock.PORT), mock.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.3)

    shot = load_shot_tools()
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

    def js(expr):
        return ws.call("Runtime.evaluate", {
            "expression": expr, "awaitPromise": True, "returnByValue": True,
        })

    def val(expr):
        res = js(expr)
        inner = res.get("result") or {}
        if "result" in inner:
            return inner["result"].get("value")
        return None

    def snap(name):
        res = ws.call("Page.captureScreenshot", {"format": "png"})
        data = (res.get("result") or {}).get("data")
        if not data:
            print("截图失败:", name)
            return
        path = os.path.join(SHOTS, name)
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        print("  ->", path)

    def open_sleep_tab():
        js("var s=document.querySelector('[data-settings-tab=\"sleep\"]'); if(s) s.click();")
        time.sleep(0.5)
        js("var i=document.getElementById('cfg-sleep-idle'); if(i) i.scrollIntoView({block:'center'});")
        time.sleep(0.3)

    try:
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        ws.call("Page.navigate", {"url": "http://127.0.0.1:%d/" % mock.PORT})
        time.sleep(3.5)
        js("var b=document.getElementById('update-later'); if(b) b.click();")
        time.sleep(0.3)
        js("var s=document.getElementById('settings-btn'); if(s) s.click();")
        time.sleep(0.6)
        open_sleep_tab()
        snap("settings_sleep_zh.png")
        zh = val(
            "JSON.stringify({"
            "idleValue: (document.getElementById('cfg-sleep-idle')||{}).value,"
            "hasMaxCalls: !!document.getElementById('cfg-sleep-max-calls'),"
            "label: (document.querySelector('label[for=cfg-sleep-idle]')||{}).textContent,"
            "hint: (document.querySelector('#cfg-sleep-idle')||{}).nextElementSibling"
            " && document.querySelector('#cfg-sleep-idle').nextElementSibling.textContent"
            "})")

        js("localStorage.setItem('mollypaw_lang','en'); location.reload();")
        time.sleep(3.5)
        js("var b2=document.getElementById('update-later'); if(b2) b2.click();")
        time.sleep(0.3)
        js("var s2=document.getElementById('settings-btn'); if(s2) s2.click();")
        time.sleep(0.6)
        open_sleep_tab()
        snap("settings_sleep_en.png")
        en = val(
            "JSON.stringify({"
            "label: (document.querySelector('label[for=cfg-sleep-idle]')||{}).textContent,"
            "hasMaxCalls: !!document.getElementById('cfg-sleep-max-calls')"
            "})")
        print("zh:", zh)
        print("en:", en)
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
