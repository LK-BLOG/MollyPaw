"""给按钮补上 data-i18n（把硬编码中文接进 i18n）。

背景：面板里有几个按钮直接写死了中文（保存密钥/随机生成/取消…），
切到英文界面会露馅。这个脚本把指定的按钮补上 data-i18n 属性，幂等。
"""
import io
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = os.path.join(ROOT, "frontend", "index.html")

# 按钮 id -> i18n key
TARGETS = {
    "relay-psk-save": "relay_psk_save",
    "relay-psk-gen": "relay_psk_gen",
    "relay-add-app": "relay_add_device",
    "relay-add-obs": "relay_add_observer",
    "relay-pin-cancel": "relay_cancel",
    "relay-psk-copy": "relay_copy",
}


def main():
    with io.open(PATH, "r", encoding="utf-8") as f:
        html = f.read()

    changed = 0
    for element_id, key in TARGETS.items():
        pattern = re.compile(
            r'(<button\b[^>]*\bid="' + re.escape(element_id) + r'"[^>]*)(>)',
            re.S,
        )

        def repl(match):
            attrs, close = match.group(1), match.group(2)
            if "data-i18n" in attrs:
                return match.group(0)
            return attrs + f' data-i18n="{key}"' + close

        new_html, n = pattern.subn(repl, html)
        if n:
            html = new_html
            # 判断这次是否真的加了（有可能本来就有）
            if f'id="{element_id}"' in html:
                changed += 1
                print(f"  {element_id} -> {key}")

    with io.open(PATH, "w", encoding="utf-8", newline="") as f:
        f.write(html)

    print(f"处理了 {changed} 个按钮")
    return 0


if __name__ == "__main__":
    sys.exit(main())
