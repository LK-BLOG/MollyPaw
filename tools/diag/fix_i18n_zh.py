"""把缺失的中文词条补进 frontend/app.js 的 zh 语言块。

背景：加"远程互联"时只写了 en，中文界面里整片面板显示英文。
这个脚本以 en 为基准，把 zh 缺的词条补上（值从一个中文表里取）。
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

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                    "frontend", "app.js")

ZH = {
    "stop": "停止",
    "stopping": "正在停...",
    "stopped": "已停止。",
    "stop_failed": "停不下来：",
    "busy_hint": "还有一轮在跑，先点停止。",
    "live": "实时",
    "polling": "轮询",
    "relay_title": "远程互联",
    "relay_desc": "让手机通过加密通道连上这台电脑。",
    "relay_enable": "开启远程互联",
    "relay_url": "中继地址",
    "relay_psk": "连接密钥",
    "relay_psk_ph": "至少 16 位，含大写、小写、数字",
    "relay_psk_saved": "已保存（留空则不改）",
    "relay_room": "房间",
    "relay_state": "状态",
    "relay_add_device": "添加设备",
    "relay_add_observer": "添加只读设备",
    "relay_pin_hint": "在手机上输入这串码。5 分钟内有效。",
    "relay_pin_ttl": "剩余",
    "relay_devices": "已配对设备",
    "relay_no_devices": "还没有配对过设备。",
    "relay_revoke": "吊销",
    "relay_remove": "删除",
    "relay_role_app": "控制端",
    "relay_role_observer": "只读端",
    "relay_audit": "文件访问日志",
    "relay_audit_empty": "没有文件访问记录。",
    "relay_connected": "已连接",
    "relay_disconnected": "已断开",
    "relay_reconnecting": "重连中",
    "relay_stopped": "已关闭",
    "relay_error": "出错",
    "relay_last_seen": "最后在线",
    "relay_added": "添加于",
    # 交互反馈与密钥操作
    "relay_working": "处理中...",
    "relay_starting": "正在开启...",
    "relay_stopping": "正在关闭...",
    "relay_need_psk": "先填一个连接密钥再开启。",
    "relay_psk_save": "保存密钥",
    "relay_psk_gen": "随机生成一个",
    "relay_psk_generated": "已生成，已自动选中，可直接 Ctrl+C 复制。",
    "relay_copy": "复制",
    "relay_copied": "已复制到剪贴板。",
    "relay_copy_failed": "复制失败，请手动选中复制。",
    "relay_nothing_to_copy": "还没有密钥可复制。",
    "relay_cancel": "取消",
}

# 英文侧（en 基础表里缺的，脚本会一并补）
EN_EXTRA = {
    "relay_working": "Working...",
    "relay_starting": "Starting...",
    "relay_stopping": "Stopping...",
    "relay_need_psk": "Set a connection key first.",
    "relay_psk_save": "Save key",
    "relay_psk_gen": "Generate one",
    "relay_psk_generated": "Generated and selected — press Ctrl+C to copy.",
    "relay_copy": "Copy",
    "relay_copied": "Copied to clipboard.",
    "relay_copy_failed": "Copy failed, select and copy manually.",
    "relay_nothing_to_copy": "No key to copy yet.",
    "relay_cancel": "Cancel",
}


def find_blocks(text):
    """返回 [(name, brace_start, brace_end, body)]，只挑词条表。"""
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
        keys = re.findall(r"\b([a-z][a-z0-9_]{2,})\s*:", body)
        if len(set(keys)) < 15:
            continue
        blocks.append((name, brace, i, body))
    return blocks


def main():
    with io.open(PATH, "r", encoding="utf-8") as f:
        text = f.read()

    blocks = find_blocks(text)
    if len(blocks) < 2:
        print("找不到两套词条块")
        return 1

    en_name, en_start, en_end, en_body = blocks[0]
    zh_name, zh_start, zh_end, zh_body = blocks[1]
    en_keys = set(re.findall(r"\b([a-z][a-z0-9_]{2,})\s*:", en_body))
    zh_keys = set(re.findall(r"\b([a-z][a-z0-9_]{2,})\s*:", zh_body))

    # 还要看 HTML 引用了什么 —— 光比对两块会漏掉"两套都没有"的 key
    html_path = os.path.join(os.path.dirname(PATH), "index.html")
    html_keys = set()
    if os.path.isfile(html_path):
        with io.open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        html_keys = set(re.findall(r'data-i18n(?:-prompt)?="([a-zA-Z0-9_]+)"', html))

    # JS 里 t("key") 引用的（动态拼接的前缀排除掉）
    js_path = os.path.join(os.path.dirname(PATH), "app.js")
    js_keys = set()
    if os.path.isfile(js_path):
        with io.open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        js_keys = set(re.findall(r'\bt\(\s*["\']([a-zA-Z0-9_]+)["\']', js))
        prefixes = set(re.findall(r'\bt\(\s*["\']([a-zA-Z0-9_]+)["\']\s*\+', js))
        js_keys -= prefixes

    referenced = html_keys | js_keys

    added = 0

    # 1) zh 缺的补中文（含引用但 zh 没有的）
    missing_zh = sorted((en_keys | referenced) - zh_keys)
    unknown = [k for k in missing_zh if k not in ZH]
    if unknown:
        print("以下 key 没有现成中文，需要人工补：")
        for k in unknown:
            print("   ", k)
    todo_zh = [k for k in missing_zh if k in ZH]
    if todo_zh:
        lines = ['      %s: "%s",' % (k, ZH[k].replace('"', '\\"')) for k in todo_zh]
        at = zh_body.index("{") + 1
        zh_body = zh_body[:at] + "\n" + "\n".join(lines) + zh_body[at:]
        added += len(lines)
        print("补 %d 个中文词条：%s" % (len(lines), ", ".join(todo_zh)))

    # 2) en 缺的补英文（含引用但 en 没有的）
    zh_keys_now = set(re.findall(r"\b([a-z][a-z0-9_]{2,})\s*:", zh_body))
    missing_en = sorted((zh_keys_now | referenced) - en_keys)
    todo_en = [k for k in missing_en if k in EN_EXTRA]
    missing_en_unknown = [k for k in missing_en if k not in EN_EXTRA]
    if missing_en_unknown:
        print("以下 key 没有现成英文：")
        for k in missing_en_unknown:
            print("   ", k)
    if todo_en:
        lines = ['      %s: "%s",' % (k, EN_EXTRA[k].replace('"', '\\"')) for k in todo_en]
        at = en_body.index("{") + 1
        en_body = en_body[:at] + "\n" + "\n".join(lines) + en_body[at:]
        added += len(lines)
        print("补 %d 个英文词条：%s" % (len(lines), ", ".join(todo_en)))

    # 重建：先改靠后的 zh，再改 en（en 在 zh 之前，位置不会因 zh 变化而漂）
    if zh_body != blocks[1][3]:
        text = text[:zh_start] + zh_body + text[zh_end + 1:]
    blocks2 = find_blocks(text)
    if len(blocks2) >= 2:
        _, en_start2, en_end2, en_body2 = blocks2[0]
        if en_body != en_body2:
            text = text[:en_start2] + en_body + text[en_end2 + 1:]

    with io.open(PATH, "w", encoding="utf-8", newline="") as f:
        f.write(text)

    print("共补了 %d 条" % added)
    return 0


if __name__ == "__main__":
    sys.exit(main())
