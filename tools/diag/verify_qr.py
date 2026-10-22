"""验证自己写的二维码编码器 —— 用标准解码器读回来。

自己写的编码器必须能被**独立实现的解码器**读懂才算数，
不然就是自娱自乐（图形看着像二维码，手机扫不出来）。

这里用 Edge 内置的 BarcodeDetector API 解码（Chromium 自带，
属于操作系统/浏览器已有的能力，不引入任何新依赖）。

用法：
    .venv\\Scripts\\python.exe tools\\verify_qr.py
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from agent.relay import crypto as C
from agent.relay import qr

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append((name, detail))
        print(f"  [FAIL] {name} :: {detail}")


def find_browser():
    for path in (
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ):
        if path and os.path.isfile(path):
            return path
    return shutil.which("msedge") or shutil.which("chrome")


def main():
    # 复用 shot_settings 里的 CDP 客户端（它已经验证可用）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from shot_settings import MiniWS, wait_for_port

    print("=== 1. 编码器自检（结构层面）===")
    text = "MP1.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=.0123456789abcdef0123456789abcdef"
    matrix, version, mask = qr.encode_matrix(text)
    size = len(matrix)
    check("矩阵尺寸符合版本公式", size == version * 4 + 17, f"size={size} version={version}")
    check("版本在支持范围内", 1 <= version <= qr.MAX_VERSION, f"version={version}")
    check("掩码在 0..7", 0 <= mask <= 7, f"mask={mask}")
    check("矩阵只含 0/1", all(v in (0, 1) for row in matrix for v in row))
    # 三个定位图形必须存在
    finder_ok = True
    for (r0, c0) in ((0, 0), (0, size - 7), (size - 7, 0)):
        # 7x7 定位图形：外框全黑、次圈全白、中心 3x3 全黑
        if matrix[r0][c0] != 1 or matrix[r0 + 1][c0 + 1] != 0 or matrix[r0 + 3][c0 + 3] != 1:
            finder_ok = False
    check("三个定位图形正确", finder_ok)

    print("\n=== 2. 用 Edge 的 BarcodeDetector 解码（关键）===")
    browser = find_browser()
    if not browser:
        check("找到浏览器用于解码验证", False, "找不到 Edge/Chrome")
        return 1
    print(f"  浏览器: {browser}")

    # 生成几张不同内容的二维码，全部用标准解码器验
    cases = [
        "HELLO-MOLLYPAW-123",
        C.make_pairing_code(os.urandom(32), "0123456789abcdef0123456789abcdef"),
        C.make_pairing_code(os.urandom(32), "fedcba9876543210fedcba9876543210"),
        "A" * 80,
    ]

    tmp = tempfile.mkdtemp(prefix="qr-verify-")
    images = {}
    for i, payload in enumerate(cases):
        png = qr.make_png(payload, scale=6, border=4)
        path = os.path.join(tmp, f"qr{i}.png")
        with open(path, "wb") as f:
            f.write(png)
        images[f"qr{i}.png"] = payload
        print(f"  生成 qr{i}.png  payload={payload[:46]!r} ({len(png)} bytes)")

    # ---------------------------------------------------------------
    # 关键：BarcodeDetector 需要 secure context。
    # about:blank 的 origin 是不透明的，不算 secure → API 不存在。
    # 从 127.0.0.1 用 http 提供页面就被视为 secure context，API 就有了。
    # ---------------------------------------------------------------
    import http.server
    import threading

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=tmp, **kw)

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    http_port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"  本地静态服务: http://127.0.0.1:{http_port}/")

    decode_page = os.path.join(tmp, "decode.html")
    with open(decode_page, "w", encoding="utf-8") as f:
        f.write("<!doctype html><meta charset=utf-8><title>qr</title><body></body>")

    profile = tempfile.mkdtemp(prefix="qr-prof-")
    port = 9227
    proc = subprocess.Popen([
        browser, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--no-proxy-server", "--disable-extensions",
        f"--remote-debugging-port={port}", "--remote-allow-origins=*",
        f"--user-data-dir={profile}", "--window-size=900,900",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        if not wait_for_port(port):
            check("浏览器 CDP 可用", False, "启动失败")
            return 1
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
            targets = json.loads(r.read().decode())
        page = next(t for t in targets if t.get("type") == "page")
        ws = MiniWS(page["webSocketDebuggerUrl"])
        ws.call("Runtime.enable")
        ws.call("Page.enable")
        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{http_port}/decode.html"})
        time.sleep(1.2)

        def js(expr, timeout=40):
            res = ws.call("Runtime.evaluate", {
                "expression": expr, "returnByValue": True, "awaitPromise": True,
            }, timeout=timeout)
            r = res.get("result", {})
            if "exceptionDetails" in r:
                return {"__err__": str(r["exceptionDetails"])[:400]}
            return r.get("result", {}).get("value")

        secure = js("window.isSecureContext")
        print(f"  isSecureContext = {secure}")
        has_api = js("typeof BarcodeDetector !== 'undefined'")
        check("浏览器有 BarcodeDetector", has_api is True, f"typeof={has_api}")
        if has_api is not True:
            print("  该浏览器没有 BarcodeDetector，跳过解码验证")
        else:
            fmts = js("BarcodeDetector.getSupportedFormats ? BarcodeDetector.getSupportedFormats().then(f=>f) : []")
            print(f"  支持的格式: {fmts}")

            for fname, payload in images.items():
                result = js("""
                (async () => {
                  const img = new Image();
                  img.src = %s;
                  await img.decode();
                  const det = new BarcodeDetector({formats: ['qr_code']});
                  const codes = await det.detect(img);
                  return codes.map(c => c.rawValue);
                })()
                """ % json.dumps("/" + fname), timeout=60)

                if isinstance(result, dict) and "__err__" in result:
                    check(f"{fname} 解码", False, result["__err__"])
                    continue
                decoded = (result or [None])[0]
                check(f"{fname} 标准解码器读出原文", decoded == payload,
                      f"期望 {payload[:40]!r} 实际 {str(decoded)[:40]!r}")

        ws.close()
    finally:
        proc.kill()
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for name, detail in FAIL:
        print(f"  FAIL: {name} :: {detail}")
    print("=" * 56)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
