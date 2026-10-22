"""列出 pywebview Window 上实际可用的方法，避免再写出不存在的 API。

起因：main.py 的托盘 on_show 里调用了 window.focus()，
而 pywebview 里 focus 是个 bool 属性（focused），不是方法 ——
点托盘"Show MollyPaw"直接抛 TypeError。
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import webview  # noqa: E402

names = [
    "show", "hide", "destroy", "focus", "focused", "restore",
    "minimize", "toggle_fullscreen", "resize", "move", "evaluate_js",
]

print("pywebview Window 成员实况：")
for name in names:
    attr = getattr(webview.Window, name, None)
    if attr is None:
        print(f"  {name:20s} 不存在")
    else:
        kind = "方法" if callable(attr) else "属性"
        print(f"  {name:20s} {kind}")
