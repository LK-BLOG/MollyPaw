"""用 CDP 驱动系统 Edge/Chrome，截 MollyPaw 设置面板各标签页。

**为什么不用 playwright**：
  - 要往项目里塞 node 依赖
  - 要额外下 200MB 浏览器二进制
这台机器本来就有 Edge，用 CDP（DevTools 协议）配合标准库就能点按钮、
量几何、截图。项目是纯 Python，工具也纯 Python。

CDP 只需要 WebSocket，标准库没有，所以用最小实现（RFC6455 客户端子集）。

用法：
    .venv\\Scripts\\python.exe tools\\shot_settings.py
    .venv\\Scripts\\python.exe tools\\shot_settings.py --url http://127.0.0.1:18765 --out shots
"""
import argparse
import base64
import json
import os
import shutil
import socket
import struct
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

DEBUG_PORT = 9223


# ---------------------------------------------------------------------------
# 最小 WebSocket 客户端（CDP 用）
# ---------------------------------------------------------------------------


class MiniWS:
    """CDP 客户端。

    用 websocket-client（项目本来就依赖它，relay 层在用），
    不要手搓 WebSocket 帧 —— 手搓过一次，`_read_exact` 的缓冲区逻辑是错的，
    折腾了半小时。能复用就别重写。
    """

    def __init__(self, url, timeout=30):
        import websocket

        self.ws = websocket.create_connection(
            url, timeout=timeout,
            # Edge/Chrome 新版会校验 Origin，不带会被拒
            origin="http://127.0.0.1",
            suppress_origin=False,
        )
        self._id = 0

    def call(self, method, params=None, timeout=30):
        self._id += 1
        msg_id = self._id
        self.ws.send(json.dumps({
            "id": msg_id, "method": method, "params": params or {}
        }))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.ws.settimeout(max(0.5, deadline - time.time()))
                raw = self.ws.recv()
            except Exception as exc:
                raise TimeoutError(f"CDP {method} 等待响应失败: {exc}")
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if data.get("id") == msg_id:
                return data
        raise TimeoutError(f"CDP {method} 超时")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 浏览器控制
# ---------------------------------------------------------------------------


def find_browser():
    for path in (
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ):
        if path and os.path.isfile(path):
            return path
    return shutil.which("msedge") or shutil.which("chrome")


def wait_for_port(port, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                return json.loads(r.read().decode())
        except Exception:
            time.sleep(0.3)
    return None


def launch(browser, url=None, port=DEBUG_PORT, size=(1180, 900)):
    """启动 headless 浏览器。

    故意不把目标 URL 放在命令行上 —— 命令行 URL 会被主页设置、
    代理、浏览器劫持插件改道（这台机器上就被导到过广告页）。
    统一先开 about:blank，再通过 CDP 的 Page.navigate 显式导航，
    导航目标完全由我们控制。
    """
    profile = tempfile.mkdtemp(prefix="mp-cdp-")
    args = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-proxy-server",
        "--disable-extensions",
        f"--remote-debugging-port={port}",
        # Edge/Chrome 新版本默认拒绝非本机 Origin 的 CDP 连接，
        # 必须显式放行，否则 WebSocket 握手成功但收不到任何消息。
        "--remote-allow-origins=*",
        f"--user-data-dir={profile}",
        f"--window-size={size[0]},{size[1]}",
        "--hide-scrollbars",
        "about:blank",
    ]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    version = wait_for_port(port)
    if not version:
        proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        return None, None, None
    # 拿页面 target
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
        targets = json.loads(r.read().decode())
    page = next((t for t in targets if t.get("type") == "page"), None)
    if not page:
        proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        return None, None, None
    return proc, profile, page["webSocketDebuggerUrl"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18765")
    parser.add_argument("--out", default="shots")
    args = parser.parse_args()

    browser = find_browser()
    if not browser:
        print("找不到 Edge/Chrome")
        return 1
    print(f"浏览器: {browser}")

    try:
        with urllib.request.urlopen(args.url + "/", timeout=15) as r:
            print(f"应用在线: HTTP {r.status}")
    except Exception as exc:
        print(f"应用没起来: {exc}")
        return 1

    os.makedirs(args.out, exist_ok=True)
    proc, profile, ws_url = launch(browser, args.url)
    if not proc:
        print("浏览器启动失败")
        return 1

    try:
        ws = MiniWS(ws_url)
        ws.call("Runtime.enable")
        ws.call("Page.enable")
        ws.call("Emulation.setDeviceMetricsOverride", {
            "width": 1180, "height": 900, "deviceScaleFactor": 1, "mobile": False,
        })

        # 显式导航，不走命令行 URL —— 否则主页设置 / 代理 / 扩展能把它改道
        ws.call("Page.navigate", {"url": args.url + "/"})
        time.sleep(3.0)

        def js(expr, timeout=20):
            res = ws.call("Runtime.evaluate", {
                "expression": expr, "returnByValue": True, "awaitPromise": True,
            }, timeout=timeout)
            result = res.get("result", {})
            if "exceptionDetails" in result:
                return {"__error__": str(result["exceptionDetails"])[:300]}
            return result.get("result", {}).get("value")

        # 页面身份断言：确认我们真的截到了 MollyPaw，而不是别的什么页面。
        # （这台机器的浏览器被导到过 APKPure 广告页，靠这个断言当场发现。）
        identity = js("""
        (function(){
          return { url: location.href, title: document.title,
                   hasMessages: !!document.getElementById('messages'),
                   hasSettings: !!document.getElementById('settings-modal'),
                   bodyLen: (document.body ? document.body.innerHTML.length : 0) };
        })()
        """)
        print(f"页面身份: {identity}")
        if not isinstance(identity, dict) or not identity.get("hasMessages"):
            print("!! 截到的不是 MollyPaw 主界面 —— 导航被改道或页面没加载完")
            print("   实际 URL:", (identity or {}).get("url"))
            ws.close()
            return 2

        def shot(name):
            res = ws.call("Page.captureScreenshot", {"format": "png"})
            data = res.get("result", {}).get("data")
            if not data:
                return False
            path = os.path.join(args.out, name)
            with open(path, "wb") as f:
                f.write(base64.b64decode(data))
            print(f"  截图 -> {path}")
            return True

        def set_viewport(w, h):
            ws.call("Emulation.setDeviceMetricsOverride", {
                "width": w, "height": h, "deviceScaleFactor": 1, "mobile": False,
            })

        shot("00-main.png")

        # 打开设置：多种可能的入口
        opened = js("""
        (function(){
          var cands = [
            document.getElementById('settings-btn'),
            document.getElementById('btn-settings'),
            document.querySelector('.settings-btn')
          ].filter(Boolean);
          if (cands.length) { cands[0].click(); return 'id:' + (cands[0].id||cands[0].className); }
          var all = Array.from(document.querySelectorAll('button,a'));
          var hit = all.find(function(b){ return (b.textContent||'').trim() === '设置'; });
          if (hit) { hit.click(); return 'text'; }
          return null;
        })()
        """)
        print(f"打开设置: {opened}")
        time.sleep(0.8)

        modal = js("""
        (function(){
          var m = document.getElementById('settings-modal');
          if (!m) return 'missing';
          var cs = getComputedStyle(m);
          return 'display=' + cs.display + ' z=' + cs.zIndex;
        })()
        """)
        print(f"settings-modal: {modal}")

        for tab in ("model", "permissions", "relay", "sleep"):
            ok = js(
                "var b=document.querySelector('[data-settings-tab=\"%s\"]');"
                "if(b){b.click();'ok'}else{'missing'}" % tab
            )
            if ok != "ok":
                print(f"  标签 {tab}: {ok}")
                continue
            time.sleep(0.5)
            shot(f"10-settings-{tab}.png")

        # 几何数据：用数字说明 CSS 有没有写歪
        metrics = js("""
        (function(){
          var sels = ['[data-settings-panel="relay"]','.relay-status-row','#relay-toggle',
            '#relay-url','#relay-psk','.relay-psk-actions','#relay-psk-save','#relay-psk-gen',
            '.relay-pair-block','.relay-pair-head','.relay-pair-actions','#relay-add-app',
            '#relay-add-obs','.relay-device-list','.relay-audit'];
          var vw = window.innerWidth;
          return sels.map(function(s){
            var el = document.querySelector(s);
            if (!el) return {sel:s, missing:true};
            var r = el.getBoundingClientRect();
            var cs = getComputedStyle(el);
            return {sel:s, x:Math.round(r.x), y:Math.round(r.y),
                    w:Math.round(r.width), h:Math.round(r.height),
                    display:cs.display, over: r.right > vw + 1 ? 'OVERFLOW' : 'ok',
                    pos:cs.position};
          });
        })()
        """)
        print("\n--- 几何 ---")
        for m in metrics or []:
            if m.get("missing"):
                print(f"  {m['sel']}  MISSING")
            else:
                print("  %-40s x=%4d y=%4d w=%4d h=%3d %-6s %-8s %s" % (
                    m["sel"], m["x"], m["y"], m["w"], m["h"],
                    m.get("display", ""), m.get("pos", ""), m.get("over", "")))

        tabs = js("""
        Array.from(document.querySelectorAll('.settings-tab')).map(function(el){
          var r = el.getBoundingClientRect();
          return {text: el.textContent.trim(), x: Math.round(r.x), w: Math.round(r.width),
                  h: Math.round(r.height)};
        })
        """)
        print("\n--- 标签页 ---")
        for t in tabs or []:
            print("  %-12s x=%4d w=%4d h=%3d" % (t["text"], t["x"], t["w"], t["h"]))

        # 切到英文看看 i18n 有没有漏
        js("localStorage.setItem('mollypaw_lang','en');")
        ws.close()
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        shutil.rmtree(profile, ignore_errors=True)

    print("\n完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
