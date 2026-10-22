"""检查 frontend/app.js 的 i18n 是否两套语言都齐全。

背景：加"远程互联"词条时脚本只改了一套语言，
结果中文界面里那个面板整片是英文（用户截图发现）。
这个脚本把"单边词条"全部列出来，防止再犯。
"""
import io
import os
import re
import sys

# Windows 控制台默认 GBK，输出中文/符号会炸
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                    "frontend", "app.js")


def main():
    with io.open(PATH, "r", encoding="utf-8") as f:
        text = f.read()

    # 找出所有 i18n 对象块：形如  xxx: {  ... key: "value", ... }
    # 用"含 msg_you / msg_mollypaw"这种锚点定位
    blocks = []
    for match in re.finditer(r"\n\s*([A-Za-z_][\w]*)\s*:\s*\{", text):
        start = match.start()
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
        # 只认"像词条表"的块
        if body.count(":") < 15:
            continue
        if '"' not in body and "'" not in body:
            continue
        # 只认行首（缩进后）的 key。
        # 不能用 \b...:  那种宽松写法 —— 值里出现 "xxx:" 会被误当成 key，
        # 例如 "Use the pairing code below instead:" 里的 instead:。
        keys = set(re.findall(r"\n\s+([a-z][a-z0-9_]{2,})\s*:", body))
        if len(keys) < 15:
            continue
        blocks.append((name, start, keys, body))

    if len(blocks) < 2:
        print("只找到 %d 个词条块，预期至少 2（en / zh）" % len(blocks))
        for name, start, keys, _ in blocks:
            print("  - %s (%d keys)" % (name, len(keys)))
        return 1

    print("找到 %d 个词条块：" % len(blocks))
    for name, start, keys, _ in blocks:
        print("  - %s: %d keys" % (name, len(keys)))

    # 以第一个为基准，逐个对比
    base_name, _, base_keys, _ = blocks[0]
    problems = 0
    for name, _, keys, _ in blocks[1:]:
        missing = base_keys - keys
        extra = keys - base_keys
        if missing:
            problems += 1
            print("\n[缺] %s 里没有（%s 有）:" % (name, base_name))
            for k in sorted(missing):
                print("     %s" % k)
        if extra:
            problems += 1
            print("\n[多] %s 里有（%s 没有）:" % (name, base_name))
            for k in sorted(extra):
                print("     %s" % k)

    if problems == 0:
        print("\n两套语言词条一致 ✅")
    else:
        print("\n发现 %d 处不一致 ❌" % problems)

    # ------------------------------------------------------------------
    # 反向检查：**所有**被引用的 key 语言表里必须真的有。
    #
    # 三个来源都要查，少查一个就会漏：
    #   1. HTML 的 data-i18n / data-i18n-prompt 属性
    #   2. JS 的 t("key") 调用
    #   3. JS 的 data-i18n 动态设置（setAttribute）
    #
    # 为什么之前漏了：只做了 en/zh 两块互相比对。
    # 新 key 两块都没有时，"两块一致" → 脚本报告无缺失 → 界面显示原始 key 名。
    # 只比 A 和 B，永远发现不了"两个都缺 C"。
    # ------------------------------------------------------------------
    base_dir = os.path.dirname(PATH)
    referenced = {}

    html_path = os.path.join(base_dir, "index.html")
    if os.path.isfile(html_path):
        with io.open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        for key in re.findall(r'data-i18n(?:-prompt)?="([a-zA-Z0-9_]+)"', html):
            referenced.setdefault(key, set()).add("index.html")
        # data-i18n-attr="placeholder" 里前面的 data-i18n 已单独匹配，这里忽略属性名

    for js_name in ("app.js", "pet.js"):
        js_path = os.path.join(base_dir, js_name)
        if not os.path.isfile(js_path):
            continue
        with io.open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        for key in re.findall(r'\bt\(\s*["\']([a-zA-Z0-9_]+)["\']', js):
            referenced.setdefault(key, set()).add(js_name)
        # 动态拼接的 key（如 t("thinking_" + level)）不该报缺失：
        # 正则只会抓到 "thinking_"，那是个前缀不是完整 key。
        # 判据：JS 里该字符串后面紧跟 " +" 的，视为前缀，跳过。
        prefixes = set(re.findall(r'\bt\(\s*["\']([a-zA-Z0-9_]+)["\']\s*\+', js))
        for key in prefixes:
            referenced.pop(key, None)
        for key in re.findall(r'data-i18n["\']?\s*\]?\s*=\s*["\']([a-zA-Z0-9_]+)["\']', js):
            referenced.setdefault(key, set()).add(js_name)

    referenced.pop("placeholder", None)
    referenced.pop("title", None)
    referenced.pop("aria", None)

    table = blocks[0][2]
    missing = {k: sorted(v) for k, v in referenced.items() if k not in table}
    if missing:
        problems += len(missing)
        print("\n[引用了但语言表里没有] 界面上会显示原始 key 名：")
        for key in sorted(missing):
            print("     %-28s 来自 %s" % (key, ", ".join(missing[key])))
    else:
        print("引用的 %d 个 key 全部存在于语言表 ✅" % len(referenced))

    # 拼写可疑：引用的 key 里存在，但另一个极其相近的 key 更可能是想写的
    near = []
    for key in sorted(referenced):
        if key in table:
            continue
        for cand in table:
            if cand != key and (cand.startswith(key) or key.startswith(cand)):
                near.append((key, cand))
    if near:
        print("\n（提示）以下 key 可能拼错，近似的已有 key：")
        for key, cand in near[:20]:
            print("     %-28s 是不是想写 %s ？" % (key, cand))

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
