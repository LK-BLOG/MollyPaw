"""截聊天输入区：验证发送/停止按钮的 SVG 渲染。

发送 = 圆 + 向上箭头；停止 = 圆 + 圆角方块（都只在 input-wrapper 里）。
用假后端喂数据，不依赖真 app 在跑。
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

    try:
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        ws.call("Emulation.setEmulatedMedia", {
            "features": [{"name": "prefers-reduced-motion", "value": "no-preference"}],
        })
        ws.call("Page.navigate", {"url": "http://127.0.0.1:%d/" % mock.PORT})
        time.sleep(3.5)

        # 发送按钮：可选态（有文字才亮）
        js("var i=document.getElementById('user-input');"
           "i.value='帮我把这个项目打包';"
           "i.dispatchEvent(new Event('input',{bubbles:true}));")
        time.sleep(0.4)
        js("var c=document.querySelector('.composer'); c.scrollIntoView({block:'center'});")
        time.sleep(0.3)
        snap("composer_send.png")

        # 停止按钮：显示出来（模拟 agent 正在跑）
        js("document.getElementById('stop-btn').style.display='inline-flex';"
           "document.getElementById('send-btn').disabled=true;")
        time.sleep(0.4)
        snap("composer_stop.png")

        info = js("JSON.stringify({"
                  "sendSvg: !!document.querySelector('#send-btn svg'),"
                  "stopSvg: !!document.querySelector('#stop-btn svg'),"
                  "sendRadius: getComputedStyle(document.getElementById('send-btn')).borderRadius,"
                  "sendW: getComputedStyle(document.getElementById('send-btn')).width,"
                  "stopBg: getComputedStyle(document.getElementById('stop-btn')).backgroundColor"
                  "})")
        print("checks:", (info.get("result") or {}).get("value"))
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
