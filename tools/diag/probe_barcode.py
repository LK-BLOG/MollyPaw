"""探测 Edge 在哪些 flag 下暴露 BarcodeDetector。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BROWSER = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9229

VARIants = [
    ("无 flag", []),
    ("ShapeDetection", ["--enable-features=ShapeDetection"]),
    ("BarcodeDetector", ["--enable-features=BarcodeDetector"]),
    ("两者+blink", ["--enable-features=ShapeDetection,BarcodeDetector",
                    "--enable-blink-features=ShapeDetection"]),
    ("enable-experimental", ["--enable-experimental-web-platform-features",
                             "--enable-features=ShapeDetection,BarcodeDetector"]),
]


def probe(flags):
    profile = tempfile.mkdtemp(prefix="qrflag-")
    args = [
        BROWSER, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--no-proxy-server", "--disable-extensions",
        f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
        f"--user-data-dir={profile}",
    ] + flags + ["about:blank"]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # 等 CDP
        ws_url = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as r:
                    targets = json.loads(r.read().decode())
                page = next((t for t in targets if t.get("type") == "page"), None)
                if page:
                    ws_url = page["webSocketDebuggerUrl"]
                    break
            except Exception:
                time.sleep(0.3)
        if not ws_url:
            return "CDP 起不来"

        from shot_settings import MiniWS
        ws = MiniWS(ws_url)
        ws.call("Runtime.enable")
        res = ws.call("Runtime.evaluate", {
            "expression": "typeof BarcodeDetector",
            "returnByValue": True,
        })
        val = res.get("result", {}).get("result", {}).get("value")
        try:
            fmts = ws.call("Runtime.evaluate", {
                "expression": "(typeof BarcodeDetector!=='undefined' && BarcodeDetector.getSupportedFormats) ? 'has-getSupported' : 'no'",
                "returnByValue": True,
            })
            hasget = fmts.get("result", {}).get("result", {}).get("value")
        except Exception:
            hasget = "?"
        ws.close()
        return f"{val} ({hasget})"
    finally:
        proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


def main():
    if not os.path.isfile(BROWSER):
        print("找不到 Edge")
        return 1
    print("探测 Edge 是否暴露 BarcodeDetector：\n")
    for name, flags in VARIants:
        # PORT 递增，避免上次残留占用
        global PORT
        PORT += 1
        try:
            result = probe(flags)
        except Exception as exc:
            result = f"异常 {exc}"
        print(f"  {name:24s} -> typeof BarcodeDetector = {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
