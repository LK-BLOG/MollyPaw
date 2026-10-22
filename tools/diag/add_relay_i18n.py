"""补远程互联面板的新词条（两套语言都补），并修正过时文案。

改文案的原因：配对方式已经从「手输 6 位 PIN」改成「扫码一键导入」，
旧文案还在说"在手机上输入这串码""5 分钟内有效"，与实现不符。
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
PATH = os.path.join(ROOT, "frontend", "app.js")

ZH = {
    # 中继服务器选择
    "relay_server_label": "中继服务器",
    "relay_server_official": "官方中继（推荐）",
    "relay_server_official_hint": "开箱即用，不用自己搭服务器",
    "relay_server_custom": "自建中继",
    "relay_server_custom_hint": "你有自己的服务器时选这个",
    "relay_url_hint": "填你自己部署的中继地址，需以 ws:// 或 wss:// 开头",
    # 开关状态
    "relay_stop": "关闭远程互联",
    "relay_stop_short": "关闭",
    # 密钥
    "relay_show": "显示",
    "relay_hide": "隐藏",
    # 配对（文案全面改写：不再是"手输数字码"）
    "relay_scan_hint": "用手机 App 扫这个码就能连上，不用手输密钥。",
    "relay_code_manual": "手机扫不了？手动复制配对码",
    "relay_code_warning": "配对码等于临时钥匙，别截图发群里。15 分钟内有效，用过一次就作废。",
    "relay_qr_failed": "二维码生成失败，请用下面的配对码手动连接：",
    # 设备清退
    "relay_revoke_all": "全部吊销",
    "relay_revoke_all_hint": "换密钥后旧设备只是连不上、并没有被清退，要彻底断了点这里",
    "relay_revoke_all_confirm": "确定要吊销全部已配对设备吗？它们都需要重新扫码配对。",
    "relay_revoke_all_done": "已吊销 {n} 台设备。",
}

EN = {
    "relay_server_label": "Relay server",
    "relay_server_official": "Official relay (recommended)",
    "relay_server_official_hint": "Works out of the box — no server to run",
    "relay_server_custom": "Self-hosted relay",
    "relay_server_custom_hint": "Pick this if you run your own",
    "relay_url_hint": "Your own relay URL; must start with ws:// or wss://",
    "relay_stop": "Stop remote access",
    "relay_stop_short": "Stop",
    "relay_show": "Show",
    "relay_hide": "Hide",
    "relay_scan_hint": "Scan this with the phone app — no key typing needed.",
    "relay_code_manual": "Can't scan? Copy the pairing code",
    "relay_code_warning": "The pairing code is a temporary key. Don't screenshot it into group chats. Valid 15 minutes, single use.",
    "relay_qr_failed": "QR generation failed. Use the pairing code below instead:",
    "relay_revoke_all": "Revoke all",
    "relay_revoke_all_hint": "Changing the key only disconnects old devices — use this to actually revoke them",
    "relay_revoke_all_confirm": "Revoke every paired device? They will all need to pair again.",
    "relay_revoke_all_done": "Revoked {n} device(s).",
}

# 需要改掉的过时文案（值替换）
OLD_VALUES = {
    "relay_pin_hint": {
        "zh": "用手机 App 扫这个码就能连上，不用手输密钥。",
        "en": "Scan this with the phone app — no key typing needed.",
    },
    "relay_add_observer": {"zh": "添加只读设备", "en": "Add read-only"},
    # 旧文案说"5 分钟"，实际是 15 分钟
    "relay_pin_ttl": {"zh": "剩余", "en": "Expires in"},
}


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
        keys = re.findall(r"\b([a-z][a-z0-9_]{2,})\s*:", body)
        if len(set(keys)) < 15:
            continue
        blocks.append((name, brace, i, body))
    return blocks


def add_entries(body, entries, indent="      "):
    brace = body.index("{")
    lines = []
    for key, value in entries.items():
        if re.search(rf"\b{re.escape(key)}\s*:", body):
            continue
        v = value.replace('"', '\\"')
        lines.append(f'{indent}{key}: "{v}",')
    if not lines:
        return body, 0
    return body[:brace + 1] + "\n" + "\n".join(lines) + body[brace + 1:], len(lines)


def main():
    with io.open(PATH, "r", encoding="utf-8") as f:
        text = f.read()

    blocks = find_blocks(text)
    if len(blocks) < 2:
        print("找不到两套词条块")
        return 1

    total = 0
    # 先改 zh（靠后），再改 en
    for idx, entries in ((1, ZH), (0, EN)):
        name, start, end, body = blocks[idx]
        new_body, n = add_entries(body, entries)
        if new_body != body:
            text = text[:start] + new_body + text[end + 1:]
            total += n
            blocks = find_blocks(text)
            print(f"{name}: 补了 {n} 条")

    with io.open(PATH, "w", encoding="utf-8", newline="") as f:
        f.write(text)

    print(f"共补 {total} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
