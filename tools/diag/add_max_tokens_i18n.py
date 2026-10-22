"""补齐 max_tokens 相关的新词条（两套语言）+ .field-hint 样式。

背景：max_tokens 改成"允许留空、留空即不带该参数"。
界面文案必须跟着改，否则用户还是不知道怎么填，
而填错就是上游 400（实测过）。
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
APP_JS = os.path.join(ROOT, "frontend", "app.js")
CSS = os.path.join(ROOT, "frontend", "style.css")

ZH = {
    "max_tokens_label": "最大输出 tokens",
    "max_tokens_ph": "留空 = 由服务端决定（推荐）",
    "max_tokens_hint": "留空最安全。填了就必须小于模型上下文上限，否则上游会报 400。",
}

EN = {
    "max_tokens_label": "Max output tokens",
    "max_tokens_ph": "Leave empty = let the server decide (recommended)",
    "max_tokens_hint": "Empty is safest. If set, it must be below the model's context limit or the API returns 400.",
}

CSS_RULE = """
/* 表单字段下方的说明文字 */
.field-hint {
  display: block;
  margin-top: 5px;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--mid-brown);
}
"""


def find_blocks(text):
    blocks = []
    for match in re.finditer(r"\n\s*([A-Za-z_][\w]*)\s*:\s*\{", text):
        name = match.group(1)
        brace = text.index("{", match.start())
        depth = 0
        i = brace
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = text[brace:i + 1]
        keys = set(re.findall(r"\n\s+([a-z][a-z0-9_]{2,})\s*:", body))
        if len(keys) >= 15:
            blocks.append((name, brace, i, body))
    return blocks


def add(body, entries):
    brace = body.index("{")
    lines = []
    for key, value in entries.items():
        if re.search(rf"\n\s+{re.escape(key)}\s*:", body):
            continue
        v = value.replace('"', '\\"')
        lines.append(f'      {key}: "{v}",')
    if not lines:
        return body, 0
    return body[:brace + 1] + "\n" + "\n".join(lines) + body[brace + 1:], len(lines)


def main():
    with io.open(APP_JS, encoding="utf-8") as f:
        text = f.read()

    blocks = find_blocks(text)
    if len(blocks) < 2:
        print("找不到两套词条块")
        return 1

    total = 0
    # 先改靠后的 zh，再改 en
    for idx, entries in ((1, ZH), (0, EN)):
        name, start, end, body = blocks[idx]
        new_body, n = add(body, entries)
        if n:
            text = text[:start] + new_body + text[end + 1:]
            total += n
            blocks = find_blocks(text)
            print(f"{name}: 补了 {n} 条")

    with io.open(APP_JS, "w", encoding="utf-8", newline="") as f:
        f.write(text)

    # 补 .field-hint 样式
    with io.open(CSS, encoding="utf-8") as f:
        css = f.read()
    if ".field-hint" not in css:
        css += CSS_RULE
        with io.open(CSS, "w", encoding="utf-8", newline="") as f:
            f.write(css)
        print("已补 .field-hint 样式")

    print(f"共补 {total} 条词条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
