"""诊断：远程互联面板的 CSS 为什么没生效。

思路：不看源码猜，直接在渲染后的页面里问浏览器
「这条规则你到底用了没有 / 被谁覆盖了」。
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shot_settings import MiniWS, find_browser, wait_for_port  # noqa: E402

PORT = 9225
URL = "http://127.0.0.1:18765"


def main():
    browser = find_browser()
    profile = tempfile.mkdtemp(prefix="mp-diag-css-")
    proc = subprocess.Popen([
        browser, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--no-proxy-server", "--disable-extensions",
        f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
        f"--user-data-dir={profile}", "--window-size=1180,900",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        if not wait_for_port(PORT):
            print("浏览器起不来")
            return 1
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=5) as r:
            targets = json.loads(r.read().decode())
        page = next(t for t in targets if t.get("type") == "page")
        ws = MiniWS(page["webSocketDebuggerUrl"])
        ws.call("Runtime.enable")
        ws.call("Page.enable")
        ws.call("Page.navigate", {"url": URL + "/"})
        time.sleep(3)

        def js(expr):
            res = ws.call("Runtime.evaluate", {
                "expression": expr, "returnByValue": True, "awaitPromise": True,
            })
            r = res.get("result", {})
            if "exceptionDetails" in r:
                return {"__err__": str(r["exceptionDetails"])[:400]}
            return r.get("result", {}).get("value")

        # 打开设置 + 切到 relay
        js("document.getElementById('settings-btn').click()")
        time.sleep(0.5)
        js("document.querySelector('[data-settings-tab=\"relay\"]').click()")
        time.sleep(0.8)

        print("=== 1. 样式表加载情况 ===")
        print(js("""
        Array.from(document.styleSheets).map(function(s){
          var n = 0; try { n = s.cssRules.length; } catch(e) { n = -1; }
          return {href: s.href, rules: n};
        })
        """))

        print("\n=== 2. 我的规则是否在样式表里 ===")
        print(js("""
        (function(){
          var found = [];
          Array.from(document.styleSheets).forEach(function(s){
            var rules; try { rules = s.cssRules; } catch(e) { return; }
            for (var i=0;i<rules.length;i++){
              var t = rules[i].selectorText || '';
              if (t.indexOf('relay') !== -1) found.push(t);
            }
          });
          return {count: found.length, sample: found.slice(0,8)};
        })()
        """))

        print("\n=== 3. 面板可见性 ===")
        print(js("""
        (function(){
          var p = document.querySelector('[data-settings-panel="relay"]');
          if (!p) return 'panel missing';
          var cs = getComputedStyle(p);
          var r = p.getBoundingClientRect();
          return {display: cs.display, cls: p.className,
                  w: Math.round(r.width), h: Math.round(r.height),
                  active: p.classList.contains('active')};
        })()
        """))

        print("\n=== 4. 关键元素的实际计算样式 ===")
        print(json.dumps(js("""
        (function(){
          var out = {};
          ['.relay-section','.relay-status-row','#relay-toggle','.relay-psk-actions',
           '#relay-psk-save','.relay-pair-head','.relay-pair-actions','#relay-add-app',
           '#relay-add-obs'].forEach(function(sel){
            var el = document.querySelector(sel);
            if (!el) { out[sel] = 'MISSING'; return; }
            var cs = getComputedStyle(el);
            var r = el.getBoundingClientRect();
            out[sel] = {display: cs.display, flex: cs.flex, padding: cs.padding,
                        width: Math.round(r.width), height: Math.round(r.height),
                        cls: el.className};
          });
          return out;
        })()
        """), ensure_ascii=False, indent=2))

        print("\n=== 5. 哪些规则命中了 #relay-add-app（按层叠顺序）===")
        print(json.dumps(js("""
        (function(){
          var el = document.querySelector('#relay-add-app');
          if (!el) return 'missing';
          var hits = [];
          Array.from(document.styleSheets).forEach(function(s, si){
            var rules; try { rules = s.cssRules; } catch(e) { return; }
            function walk(rs, ctx){
              for (var i=0;i<rs.length;i++){
                var rule = rs[i];
                if (rule.cssRules && rule.selectorText) {
                  // @media 等
                  walk(rule.cssRules, rule.conditionText || rule.selectorText);
                  continue;
                }
                if (!rule.selectorText) continue;
                try { if (el.matches(rule.selectorText)) {
                  hits.push({sheet: si, ctx: ctx || null,
                             sel: rule.selectorText,
                             css: rule.style.cssText.slice(0,180)});
                } } catch(e) {}
              }
            }
            walk(rules, null);
          });
          return hits;
        })()
        """), ensure_ascii=False, indent=2))

        ws.close()
    finally:
        proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
