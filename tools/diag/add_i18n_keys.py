"""往 frontend/app.js 的 en / zh 两套 i18n 里插入远程互联相关的词条。

用脚本而不是手改，是因为 app.js 有 1300 行、两套语言表混在一起，
手工插容易插错位置或漏一边（漏了就会看到 key 而不是文案）。
幂等：已经有了就跳过。
"""
import io
import os
import re
import sys

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                    "frontend", "app.js")

# 英文词条
EN_NEW = {
    "stop": "Stop",
    "stopping": "Stopping...",
    "stopped": "Stopped.",
    "stop_failed": "Could not stop: ",
    "busy_hint": "Another round is still running. Stop it first.",
    "live": "Live",
    "polling": "Polling",
    "relay_title": "Remote Access",
    "relay_desc": "Connect your phone to this computer over an encrypted channel.",
    "relay_enable": "Enable remote access",
    "relay_url": "Relay address",
    "relay_psk": "Connection key",
    "relay_psk_ph": "At least 16 chars, with upper, lower and digit",
    "relay_psk_saved": "Key saved (leave blank to keep)",
    "relay_room": "Room",
    "relay_state": "State",
    "relay_add_device": "Add device",
    "relay_add_observer": "Add read-only device",
    "relay_pin_hint": "Type this code on your phone. Valid for 5 minutes.",
    "relay_pin_ttl": "Expires in",
    "relay_devices": "Paired devices",
    "relay_no_devices": "No devices paired yet.",
    "relay_revoke": "Revoke",
    "relay_remove": "Remove",
    "relay_role_app": "Control",
    "relay_role_observer": "Read-only",
    "relay_audit": "File access log",
    "relay_audit_empty": "No file access recorded.",
    "relay_connected": "Connected",
    "relay_disconnected": "Disconnected",
    "relay_reconnecting": "Reconnecting",
    "relay_stopped": "Off",
    "relay_error": "Error",
    "relay_last_seen": "Last seen",
    "relay_added": "Added",
}

# 中文词条
ZH_NEW = {
    "stop": "\u505C\u6B62",
    "stopping": "\u6B63\u5728\u505C...",
    "stopped": "\u5DF2\u505C\u6B62\u3002",
    "stop_failed": "\u505C\u4E0D\u4E0B\u6765\uFF1A",
    "busy_hint": "\u8FD8\u6709\u4E00\u8F6E\u5728\u8DD1\uFF0C\u5148\u70B9\u505C\u6B62\u3002",
    "live": "\u5B9E\u65F6",
    "polling": "\u8F6E\u8BE2",
    "relay_title": "\u8FDC\u7A0B\u4E92\u8054",
    "relay_desc": "\u8BA9\u624B\u673A\u901A\u8FC7\u52A0\u5BC6\u901A\u9053\u8FDE\u4E0A\u8FD9\u53F0\u7535\u8111\u3002",
    "relay_enable": "\u5F00\u542F\u8FDC\u7A0B\u4E92\u8054",
    "relay_url": "\u4E2D\u7EE7\u5730\u5740",
    "relay_psk": "\u8FDE\u63A5\u5BC6\u94A5",
    "relay_psk_ph": "\u81F3\u5C11 16 \u4F4D\uFF0C\u542B\u5927\u5199\u3001\u5C0F\u5199\u3001\u6570\u5B57",
    "relay_psk_saved": "\u5DF2\u4FDD\u5B58\uFF08\u7559\u7A7A\u5219\u4E0D\u6539\uFF09",
    "relay_room": "\u623F\u95F4",
    "relay_state": "\u72B6\u6001",
    "relay_add_device": "\u6DFB\u52A0\u8BBE\u5907",
    "relay_add_observer": "\u6DFB\u52A0\u53EA\u8BFB\u8BBE\u5907",
    "relay_pin_hint": "\u5728\u624B\u673A\u4E0A\u8F93\u5165\u8FD9\u4E32\u7801\u30025 \u5206\u949F\u5185\u6709\u6548\u3002",
    "relay_pin_ttl": "\u5269\u4F59",
    "relay_devices": "\u5DF2\u914D\u5BF9\u8BBE\u5907",
    "relay_no_devices": "\u8FD8\u6CA1\u6709\u914D\u5BF9\u8FC7\u8BBE\u5907\u3002",
    "relay_revoke": "\u540A\u9500",
    "relay_remove": "\u5220\u9664",
    "relay_role_app": "\u63A7\u5236\u7AEF",
    "relay_role_observer": "\u53EA\u8BFB\u7AEF",
    "relay_audit": "\u6587\u4EF6\u8BBF\u95EE\u65E5\u5FD7",
    "relay_audit_empty": "\u6CA1\u6709\u6587\u4EF6\u8BBF\u95EE\u8BB0\u5F55\u3002",
    "relay_connected": "\u5DF2\u8FDE\u63A5",
    "relay_disconnected": "\u5DF2\u65AD\u5F00",
    "relay_reconnecting": "\u91CD\u8FDE\u4E2D",
    "relay_stopped": "\u5DF2\u5173\u95ED",
    "relay_error": "\u51FA\u9519",
    "relay_last_seen": "\u6700\u540E\u5728\u7EBF",
    "relay_added": "\u6DFB\u52A0\u4E8E",
}


def find_block(text, marker):
    """找到以 marker 开头的对象字面量块，返回 (start, end) 的行号区间。"""
    idx = text.find(marker)
    if idx < 0:
        raise SystemExit(f"找不到标记: {marker}")
    # 从 marker 往后找第一个 '{'，然后配对花括号
    brace = text.find("{", idx)
    depth = 0
    i = brace
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return idx, i + 1
        i += 1
    raise SystemExit("花括号不配对")


def insert_entries(block, entries, indent="      "):
    """把词条插进块的最前面（{ 之后）。"""
    brace = block.find("{")
    body = block[brace + 1:]
    lines = []
    for key, value in entries.items():
        if re.search(rf"\b{re.escape(key)}\s*:", block):
            continue
        lines.append(f'{indent}{key}: "{value}",')
    if not lines:
        return block
    return block[:brace + 1] + "\n" + "\n".join(lines) + body


def main():
    with io.open(PATH, "r", encoding="utf-8") as f:
        text = f.read()

    # en 是文件里第一个 i18n 块，zh 是第二个
    en_marker = "typing:"
    # 直接按已知的英文/中文锚点定位
    en_start = text.find('      msg_mollypaw: "MollyPaw",')
    if en_start < 0:
        raise SystemExit("找不到英文锚点")

    # 英文块：从 msg_mollypaw 往前找到块的起点（var I18N = { 那一行）
    pre = text.rfind("{", 0, en_start)

    zh_anchor = text.find("typing: \"MollyPaw \\u6B63\\u5728\\u601D\\u8003...\"")
    if zh_anchor < 0:
        raise SystemExit("找不到中文锚点")

    changed = 0
    for entries, anchor in ((EN_NEW, en_start), (ZH_NEW, zh_anchor)):
        # 找到包含该锚点的块
        start = text.rfind("{", 0, anchor)
        # 往前再确认这个 { 是对象开始（不是函数体）
        depth = 0
        i = start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        block = text[start:i + 1]
        new_block = insert_entries(block, entries)
        if new_block != block:
            text = text[:start] + new_block + text[i + 1:]
            changed += 1

    with io.open(PATH, "w", encoding="utf-8", newline="") as f:
        f.write(text)

    print(f"更新了 {changed} 个语言块")
    return 0


if __name__ == "__main__":
    sys.exit(main())
