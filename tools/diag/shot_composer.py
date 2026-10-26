"""截聊天输入区：验证发送/停止按钮、键位提示、排队提示、停止中转圈。

发送 = 圆 + 向上箭头；停止 = 圆 + 圆角方块；点停止后方块换转圈。
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

    try:
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        ws.call("Emulation.setEmulatedMedia", {
            "features": [{"name": "prefers-reduced-motion", "value": "no-preference"}],
        })
        ws.call("Page.navigate", {"url": "http://127.0.0.1:%d/" % mock.PORT})
        time.sleep(3.5)
        # mock 会返回「有新版本」，弹窗会挡住输入区；先关掉
        js("var b=document.getElementById('update-later'); if(b) b.click();")
        time.sleep(0.3)
        js("var c=document.querySelector('.composer'); if(c) c.scrollIntoView({block:'center'});")
        time.sleep(0.2)

        # 1) 空闲：只有发送按钮
        js("var i=document.getElementById('user-input');"
           "i.value='帮我把这个项目打包';"
           "i.dispatchEvent(new Event('input',{bubbles:true}));")
        time.sleep(0.4)
        snap("composer_send.png")

        # 2) AI 跑着：只有停止按钮 + 排队提示
        js("document.getElementById('stop-btn').style.display='inline-flex';"
           "document.getElementById('send-btn').style.display='none';"
           "var q=document.getElementById('queue-hint');"
           "q.hidden=false; q.textContent='已排队 2 条，本轮结束自动发送';")
        time.sleep(0.4)
        snap("composer_stop.png")

        # 3) 点了停止：方块 -> 转圈
        js("document.getElementById('stop-btn').classList.add('stopping');")
        time.sleep(0.35)
        snap("composer_stopping.png")
        busy = val("getComputedStyle(document.querySelector('#stop-btn .icon-busy')).display")

        # 4) 停止之后：命令被转到后台，提示条出现（走真实的 refreshBgNotice 链路）
        js(
            "(function(){"
            "var orig = window.fetch;"
            "window.fetch = function(u, o){"
            "  if (String(u).indexOf('/api/processes') === 0) {"
            "    return Promise.resolve({ json: function(){ return Promise.resolve({"
            "      ok: true, count: 2, items: ["
            "        {pid: 20168, cmd: 'gradlew assembleRelease', alive: true},"
            "        {pid: 18444, cmd: 'fetch_releases.py', alive: true}"
            "      ] }); } });"
            "  }"
            "  return orig(u, o);"
            "};"
            "window.refreshBgNotice();"
            "})();"
        )
        time.sleep(0.6)
        snap("composer_bg_notice.png")
        bgShown = val("(function(){var b=document.getElementById('bg-notice');"
                      "return JSON.stringify({hidden: b.hidden,"
                      "text: document.getElementById('bg-notice-text').textContent,"
                      "btn: (document.getElementById('bg-kill')||{}).textContent,"
                      "bg: getComputedStyle(b).backgroundColor});})()")

        # 5) 切英文，检查 i18n 是否还有中文漏网
        js("localStorage.setItem('mollypaw_lang','en'); location.reload();")
        time.sleep(3.5)
        js("var b2=document.getElementById('update-later'); if(b2) b2.click();")
        time.sleep(0.3)
        js("var c2=document.querySelector('.composer'); if(c2) c2.scrollIntoView({block:'center'});")
        time.sleep(0.3)
        js(
            "(function(){"
            "var orig = window.fetch;"
            "window.fetch = function(u, o){"
            "  if (String(u).indexOf('/api/processes') === 0) {"
            "    return Promise.resolve({ json: function(){ return Promise.resolve({"
            "      ok: true, count: 1, items: [{pid: 777, cmd: 'x', alive: true}] }); } });"
            "  }"
            "  return orig(u, o);"
            "};"
            "window.refreshBgNotice();"
            "})();"
        )
        time.sleep(0.6)
        snap("composer_en.png")
        bgEn = val("document.getElementById('bg-notice-text').textContent")

        checks = val("JSON.stringify({"
                     "sendSvg: !!document.querySelector('#send-btn svg'),"
                     "stopSvg: !!document.querySelector('#stop-btn svg'),"
                     "busySvg: !!document.querySelector('#stop-btn .icon-busy'),"
                     "sendRadius: getComputedStyle(document.getElementById('send-btn')).borderRadius,"
                     "sendW: getComputedStyle(document.getElementById('send-btn')).width,"
                     "sendDisplay: getComputedStyle(document.getElementById('send-btn')).display,"
                     "kbdHints: document.querySelectorAll('.kbd-hint').length,"
                     "balance: (document.getElementById('balance-status')||{}).textContent,"
                     "kbdText: (document.querySelector('.kbd-hint')||{}).textContent"
                     "})")
        print("busy display =", busy)
        print("bg notice:", bgShown)
        print("bg notice (en):", bgEn)
        print("checks:", checks)
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
