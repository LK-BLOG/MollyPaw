"""MollyPaw — 前端 i18n 一致性测试。

背景（用户两次反馈）：
  1. 中文界面里"远程互联"整个面板是英文 —— en 有词条、zh 没有。
  2. 界面直接显示 `relay_copy`、`relay_psk_gen` 这种原始 key 名 ——
     key 被引用了，但**两套表里都没有**。

第 2 种最阴：补词条的脚本只做 en/zh 互相比对，
两个表都缺同一个 key 时它们"完全一致"，脚本报告无缺失。
所以必须**从引用侧反查**：HTML 的 data-i18n、JS 的 t("key") 都得能查到。

这个测试把那次的教训钉死。
"""
import io
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(ROOT, "frontend", "app.js")
INDEX_HTML = os.path.join(ROOT, "frontend", "index.html")


def _read(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def _find_blocks(text):
    """找出所有"词条表"块，返回 [(name, body)]。"""
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
        # 只认行首（缩进后）的 key。
        # 不能用宽松的 \b...: —— 词条值里出现 "xxx:" 会被误当成 key，
        # 例如 "Use the pairing code below instead:" 里的 instead:。
        keys = set(re.findall(r"\n\s+([a-z][a-z0-9_]{2,})\s*:", body))
        if len(keys) >= 15:
            blocks.append((name, body, keys))
    return blocks


@pytest.fixture(scope="module")
def i18n():
    text = _read(APP_JS)
    blocks = _find_blocks(text)
    assert len(blocks) >= 2, f"预期至少两套词条（en/zh），实际 {len(blocks)}"
    en_name, en_body, en_keys = blocks[0]
    zh_name, zh_body, zh_keys = blocks[1]
    return {
        "text": text,
        "blocks": blocks,
        "en_keys": en_keys,
        "zh_keys": zh_keys,
        "all_keys": en_keys | zh_keys,
    }


@pytest.fixture(scope="module")
def referenced():
    """所有被引用的 key（HTML + JS），排除动态拼接的前缀。"""
    keys = {}

    html = _read(INDEX_HTML)
    for key in re.findall(r'data-i18n(?:-prompt)?="([a-zA-Z0-9_]+)"', html):
        keys.setdefault(key, set()).add("index.html")

    js = _read(APP_JS)
    for key in re.findall(r'\bt\(\s*["\']([a-zA-Z0-9_]+)["\']', js):
        keys.setdefault(key, set()).add("app.js")
    # t("thinking_" + level) 这种是前缀，不是完整 key
    for prefix in re.findall(r'\bt\(\s*["\']([a-zA-Z0-9_]+)["\']\s*\+', js):
        keys.pop(prefix, None)

    return keys


# --------------------------------------------------------------------------
# 两套语言必须齐平
# --------------------------------------------------------------------------


def test_two_language_tables_exist(i18n):
    names = [b[0] for b in i18n["blocks"]]
    assert "en" in names, f"找不到英文词条表，实际有 {names}"
    assert "zh" in names, f"找不到中文词条表，实际有 {names}"


def test_both_tables_have_same_keys(i18n):
    """en / zh 词条必须一一对应。

    历史上出现过 en 103 条、zh 68 条 —— 中文界面整片显示英文。
    """
    only_en = sorted(i18n["en_keys"] - i18n["zh_keys"])
    only_zh = sorted(i18n["zh_keys"] - i18n["en_keys"])
    assert not only_en, f"这些 key 只有英文，中文界面会显示英文：{only_en}"
    assert not only_zh, f"这些 key 只有中文，英文界面会显示中文：{only_zh}"


def test_table_is_not_suspiciously_small(i18n):
    """词条表被截断/解析失败的保护性断言。"""
    assert len(i18n["all_keys"]) >= 60, (
        f"词条只有 {len(i18n['all_keys'])} 条，像是解析失败或文件被截断"
    )


# --------------------------------------------------------------------------
# 引用侧反查（这次事故的关键）
# --------------------------------------------------------------------------


def test_every_referenced_key_exists(i18n, referenced):
    """被引用的 key 必须在语言表里存在。

    缺了不会报错，界面直接显示原始 key 名（用户看到的是 relay_copy）。
    只比对 en/zh 两块发现不了这个 —— 必须从引用侧反查。
    """
    missing = {k: sorted(v) for k, v in referenced.items() if k not in i18n["all_keys"]}
    assert not missing, (
        "以下 key 被引用但语言表里没有，界面会显示原始 key 名：\n"
        + "\n".join(f"  {k}  (来自 {', '.join(v)})" for k, v in sorted(missing.items()))
    )


def test_relay_panel_keys_all_present(i18n):
    """远程互联面板用到的 key 一个都不能少。"""
    required = [
        "relay_title", "relay_desc", "relay_enable", "relay_url", "relay_psk",
        "relay_psk_save", "relay_psk_gen", "relay_copy", "relay_psk_saved",
        "relay_add_device", "relay_add_observer", "relay_pin_hint", "relay_pin_ttl",
        "relay_cancel", "relay_devices", "relay_no_devices", "relay_revoke",
        "relay_remove", "relay_role_app", "relay_role_observer", "relay_audit",
        "relay_audit_empty", "relay_connected", "relay_disconnected",
        "relay_reconnecting", "relay_stopped", "relay_error",
        "relay_working", "relay_starting", "relay_stopping", "relay_need_psk",
        "relay_psk_generated", "relay_copied", "relay_copy_failed",
        "relay_nothing_to_copy",
    ]
    missing = [k for k in required if k not in i18n["all_keys"]]
    assert not missing, f"远程互联面板缺少词条：{missing}"


def test_stop_button_keys_present(i18n):
    for key in ("stop", "stopping", "stopped", "stop_failed", "busy_hint"):
        assert key in i18n["all_keys"], f"缺少停止按钮词条 {key}"


def test_no_chinese_in_english_table(i18n):
    """英文表里不该混入中文字符（复制粘贴时最容易犯）。"""
    en_body = i18n["blocks"][0][1]
    # 只检查值，不检查 key
    cjk = re.findall(r':\s*"([^"]*[\u4e00-\u9fff][^"]*)"', en_body)
    assert not cjk, f"英文词条里混入了中文：{cjk[:5]}"


def test_no_english_only_in_chinese_table(i18n):
    """中文表里不该整条都是英文（除了 relay_psk 这种缩写值）。"""
    zh_body = i18n["blocks"][1][1]
    suspicious = []
    for key, value in re.findall(r'\b([a-z][a-z0-9_]{2,})\s*:\s*"([^"]*)"', zh_body):
        if not value:
            continue
        has_cjk = bool(re.search(r"[\u4e00-\u9fff]", value))
        looks_english = bool(re.match(r"^[A-Za-z0-9 ,\.\-_'/()]+$", value))
        if looks_english and not has_cjk and len(value) > 3:
            suspicious.append((key, value))
    # 允许少量（比如 "MollyPaw" 这种品牌词）
    assert len(suspicious) <= 6, f"中文表里有疑似未翻译的条目：{suspicious[:8]}"


# --------------------------------------------------------------------------
# HTML 结构
# --------------------------------------------------------------------------


def test_html_has_stop_button():
    html = _read(INDEX_HTML)
    assert 'id="stop-btn"' in html, "停止按钮没在页面里"


def test_html_has_relay_panel():
    html = _read(INDEX_HTML)
    assert 'data-settings-tab="relay"' in html
    assert 'data-settings-panel="relay"' in html
    for element_id in ("relay-url", "relay-psk", "relay-toggle", "relay-qr", "relay-code"):
        assert f'id="{element_id}"' in html


def test_psk_input_is_text_not_password():
    """密钥框必须是 text。

    用 password 时用户反馈过：随机生成后看不见、复制不了，
    浏览器也不给"显示密码"按钮（那只对用户自己输入过的登录框生效）。
    """
    html = _read(INDEX_HTML)
    match = re.search(r'<input[^>]*id="relay-psk"[^>]*>', html)
    assert match, "找不到 relay-psk 输入框"
    tag = match.group(0)
    assert 'type="text"' in tag, f"密钥框应该是 text，实际：{tag}"
    assert 'type="password"' not in tag


def test_html_buttons_use_i18n_not_hardcoded():
    """面板里的按钮文字必须走 i18n，不能硬编码。

    硬编码中文的话，切到英文界面会露馅。
    """
    html = _read(INDEX_HTML)
    for element_id in ("relay-psk-save", "relay-psk-gen", "relay-add-app",
                       "relay-add-obs", "relay-pin-cancel"):
        match = re.search(rf'<button[^>]*id="{element_id}"[^>]*>(.*?)</button>', html, re.S)
        assert match, f"找不到按钮 {element_id}"
        full_tag = match.group(0)
        assert "data-i18n=" in full_tag, (
            f"按钮 {element_id} 没有 data-i18n，切换语言会露馅：{full_tag[:120]}"
        )
