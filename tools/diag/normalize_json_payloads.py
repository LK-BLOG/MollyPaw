"""把 main.py 里手写的 JSON 解码统一换成 _load_json_payload。

背景：`_read_body()` 返回 bytes，而多处代码写的是
    json.loads(x) if isinstance(x, str) else x
bytes 走 else 分支 → 直接把 bytes 当 dict → `**` 展开时炸
"argument after ** must be a mapping, not bytes"。
HTTP 层所有 POST body 都是 bytes，所以这条路径**一定会被真实请求踩到**。

这个脚本做机械替换，替换后逐处人工确认。
"""
import io
import os
import re
import sys

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                    "main.py")

# (行内模式, 替换为) —— 只处理"X 是 str 就 loads，否则原样"这种写法
REPLACEMENTS = [
    (r'json\.loads\((\w+)\) if isinstance\(\1, str\) else \(\1 or \{\}\)',
     r'_load_json_payload(\1)'),
    (r'json\.loads\((\w+)\) if isinstance\(\1, str\) else \1',
     r'_load_json_payload(\1)'),
]


def main():
    with io.open(PATH, "r", encoding="utf-8") as f:
        text = f.read()

    hits = []
    for pattern, repl in REPLACEMENTS:
        for match in re.finditer(pattern, text):
            hits.append(match.group(0))

    if not hits:
        print("没有需要替换的（可能已经改完）")
        return 0

    for pattern, repl in REPLACEMENTS:
        text = re.sub(pattern, repl, text)

    with io.open(PATH, "w", encoding="utf-8", newline="") as f:
        f.write(text)

    print(f"替换了 {len(hits)} 处：")
    for h in hits:
        print("  -", h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
