"""端到端验收远程互联面板：真的去点按钮，检查有没有反馈。

用户反馈过三件事，这个脚本就是把它们变成可重复的自动断言：
  1. 点"开启远程互联"没反应（点不动）
  2. 随机生成的密钥看不见（password 框）
  3. 界面显示 relay_copy 这种原始 key 名

用法：先起好应用，再跑
    .venv\\Scripts\\python.exe tools\\verify_relay_panel.py
"""
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

PORT = 9226
URL = "http://127.0.0.1:18765"

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append((name, detail))
        print(f"  [FAIL] {name} :: {detail}")


def main():
    browser = find_browser()
    profile = tempfile.mkdtemp(prefix="mp-verify-")
    proc = subprocess.Popen([
        browser, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--no-proxy-server", "--disable-extensions",
        f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
        f"--user-data-dir={profile}", "--window-size=1180,900",
        "--hide-scrollbars", "about:blank",
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
        time.sleep(3.2)

        def js(expr, timeout=25):
            res = ws.call("Runtime.evaluate", {
                "expression": expr, "returnByValue": True, "awaitPromise": True,
            }, timeout=timeout)
            r = res.get("result", {})
            if "exceptionDetails" in r:
                return {"__err__": str(r["exceptionDetails"])[:300]}
            return r.get("result", {}).get("value")

        print("\n[0] 页面身份")
        ident = js("({url:location.href, title:document.title, has:!!document.getElementById('settings-modal')})")
        check("截到的是 MollyPaw 主界面", isinstance(ident, dict) and ident.get("has"), str(ident))

        js("document.getElementById('settings-btn').click()")
        time.sleep(0.6)
        js("document.querySelector('[data-settings-tab=\"relay\"]').click()")
        time.sleep(0.8)

        print("\n[1] 界面不能出现原始 i18n key")
        texts = js("""
        (function(){
          var panel = document.querySelector('[data-settings-panel="relay"]');
          if (!panel) return null;
          return panel.innerText;
        })()
        """)
        check("面板能取到文本", isinstance(texts, str) and len(texts) > 20, str(texts)[:120])
        leaked = []
        if isinstance(texts, str):
            for token in ("relay_", "stop_failed", "busy_hint"):
                if token in texts:
                    leaked.append(token)
        check("没有泄漏原始 key 名", not leaked, f"泄漏了 {leaked}")

        print("\n[2] 密钥框类型（必须是 text，否则生成后看不见）")
        psk_type = js("(document.getElementById('relay-psk')||{}).type")
        check("密钥输入框 type=text", psk_type == "text", f"实际 {psk_type}")
        has_copy = js("!!document.getElementById('relay-psk-copy')")
        check("有复制按钮", has_copy is True)

        print("\n[3] 随机生成密钥：看得见 + 能复制")
        js("document.getElementById('relay-psk-gen').click()")
        time.sleep(0.4)
        val = js("(document.getElementById('relay-psk')||{}).value")
        visible = js("""
        (function(){
          var el = document.getElementById('relay-psk');
          if (!el) return null;
          var cs = getComputedStyle(el);
          return {type: el.type, value: el.value, w: Math.round(el.getBoundingClientRect().width)};
        })()
        """)
        check("生成了密钥", isinstance(val, str) and len(val) >= 16, f"值={val!r}")
        check("密钥是明文可见的（type=text）",
              isinstance(visible, dict) and visible.get("type") == "text",
              str(visible))
        if isinstance(val, str) and val:
            has_upper = any(c.isupper() for c in val)
            has_lower = any(c.islower() for c in val)
            has_digit = any(c.isdigit() for c in val)
            check("生成的密钥满足强度（大小写+数字）",
                  has_upper and has_lower and has_digit,
                  f"upper={has_upper} lower={has_lower} digit={has_digit}")

        print("\n[4] 点复制按钮要有反馈")
        js("document.getElementById('relay-psk-copy').click()")
        time.sleep(0.5)
        hint = js("(document.getElementById('relay-psk-hint')||{}).textContent || ''")
        check("复制后给了提示", bool(hint and hint.strip()), f"hint={hint!r}")

        print("\n[5] 点开启：不能静默无反应")
        js("document.getElementById('relay-psk').value = 'MollyPawVerify123'")
        js("document.getElementById('relay-psk-save').click()")
        time.sleep(1.2)
        before = js("(document.getElementById('relay-psk-hint')||{}).textContent || ''")
        check("保存密钥有反馈", bool(before and before.strip()), f"hint={before!r}")

        js("document.getElementById('relay-toggle').click()")
        time.sleep(3.0)
        after = js("(document.getElementById('relay-psk-hint')||{}).textContent || ''")
        state = js("(document.getElementById('relay-state')||{}).textContent || ''")
        toggle_txt = js("(document.getElementById('relay-toggle')||{}).textContent || ''")
        toggle_disabled = js("(document.getElementById('relay-toggle')||{}).disabled")
        check("点开启后有状态变化或提示",
              state.strip() not in ("", "已关闭") or bool(after and after.strip()),
              f"state={state!r} hint={after!r}")
        check("按钮没有卡在禁用状态", toggle_disabled is not True,
              f"disabled={toggle_disabled} text={toggle_txt!r}")

        print("\n[6] CSS 布局：按钮宽度必须贴合内容")
        # 先点一下"添加设备"把配对区展开 —— 否则里面的元素是 hidden，
        # getBoundingClientRect 全是 0，测出来的"失败"是假的。
        js("document.getElementById('relay-add-app').click()")
        time.sleep(1.8)

        pair_visible = js("!document.getElementById('relay-pair-box').hidden")
        check("配对区能展开", pair_visible is True, f"hidden={pair_visible}")

        # 二维码必须真的渲染出来（后端生成了但前端没用上，曾经就是这样）
        qr_src = js("(document.getElementById('relay-qr')||{}).src || ''")
        check("二维码已显示",
              isinstance(qr_src, str) and qr_src.startswith("data:image/png"),
              f"src={str(qr_src)[:40]!r}")

        qr_size = js("""
        (function(){
          var el = document.getElementById('relay-qr');
          if (!el) return null;
          var r = el.getBoundingClientRect();
          return {w: Math.round(r.width), h: Math.round(r.height)};
        })()
        """)
        check("二维码尺寸合理",
              isinstance(qr_size, dict) and qr_size.get("w", 0) > 100
              and qr_size.get("h", 0) > 100, str(qr_size))

        # 配对码要能在界面上看到（扫不了码时的退路）
        code_val = js("(document.getElementById('relay-code')||{}).value || ''")
        check("配对码可手动复制",
              isinstance(code_val, str) and code_val.startswith("MP1."),
              f"值={str(code_val)[:24]!r}")

        geo = js("""
        (function(){
          var out = {};
          [['#relay-toggle',300],['#relay-psk-save',300],['#relay-add-app',90],
           ['#relay-add-obs',90],['#relay-psk-copy',200],['#relay-pin-cancel',200],
           ['#relay-code-copy',200]].forEach(function(p){
            var el = document.querySelector(p[0]);
            if (!el) { out[p[0]] = null; return; }
            var r = el.getBoundingClientRect();
            out[p[0]] = {w: Math.round(r.width), h: Math.round(r.height),
                         text: (el.textContent||'').trim()};
          });
          return out;
        })()
        """)
        for sel, maxw in (("#relay-toggle", 300), ("#relay-psk-save", 300),
                          ("#relay-add-app", 90), ("#relay-add-obs", 90),
                          ("#relay-psk-copy", 200), ("#relay-pin-cancel", 200),
                          ("#relay-code-copy", 200)):
            g = (geo or {}).get(sel)
            if g is None:
                check(f"{sel} 存在且有宽度", False, "元素不存在")
                continue
            check(f"{sel} 宽度正常（{g['w']}px, 文字 {g['text'][:8]!r}）",
                  0 < g["w"] <= maxw and g["h"] >= 20,
                  f"w={g['w']} h={g['h']} 上限={maxw}")

        # 单选按钮布局：radio 必须紧挨着它自己的文字（在左侧），
        # 不能被 .form-group input 的 width:100% 推到整行最右边。
        radio_geo = js("""
        (function(){
          var box = document.querySelector('.relay-server-choice');
          if (!box) return null;
          var radios = box.querySelectorAll('input[type=radio]');
          var out = [];
          for (var i = 0; i < radios.length; i++) {
            var rr = radios[i].getBoundingClientRect();
            var label = radios[i].closest('.relay-radio');
            var lr = label ? label.getBoundingClientRect() : null;
            out.push({
              rx: Math.round(rr.x), rw: Math.round(rr.width),
              lx: lr ? Math.round(lr.x) : -1,
              lw: lr ? Math.round(lr.width) : 0
            });
          }
          return out;
        })()
        """)
        if isinstance(radio_geo, list) and radio_geo:
            # 宽度必须是小圆点尺寸（不能被撑成整行）
            widths_ok = all(r["rw"] <= 24 for r in radio_geo)
            # 位置必须在 label 左半边
            side_ok = all(r["rx"] <= r["lx"] + r["lw"] / 2 for r in radio_geo)
            check("单选按钮没被撑宽（宽度 <= 24px）", widths_ok, str(radio_geo))
            check("单选按钮在文字左侧", side_ok, str(radio_geo))
        else:
            check("找到服务器单选组", False, str(radio_geo))

        print("\n[7] 关闭中继，收尾")
        js("document.getElementById('relay-toggle').click()")
        time.sleep(2.0)
        print("  已尝试关闭")

        ws.close()
    finally:
        proc.kill()
        shutil.rmtree(profile, ignore_errors=True)

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for name, detail in FAIL:
        print(f"  FAIL: {name} :: {detail}")
    print("=" * 56)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
