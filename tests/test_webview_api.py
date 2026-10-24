"""MollyPaw — main.py 里用到的 pywebview API 必须真实存在。

起因（用户实际踩到）：
main.py 的托盘 on_show 调用了 window.focus()，
但 pywebview 的 Window **没有 focus 方法** —— 点托盘"Show MollyPaw"
时 pystray 抛 `TypeError: 'bool' object is not callable`。

注意现象：**程序不会退出**，因为 pystray 自己在 dispatcher 里把异常
打出来就吞了。表现是"点了没反应、窗口不回来"，比崩溃更难发现。

所以用测试钉住：main.py 里 `window.xxx(...)` 调用的每个方法都必须真实存在。

实现要点：用 **AST** 找真实调用，不要用正则 ——
正则会把注释和文档字符串里出现的 `window.focus()` 也算进来（踩过）。
"""
import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PY = os.path.join(ROOT, "main.py")


def _real_webview():
    """拿到**真的** pywebview 模块。

    conftest 的 main_module fixture 会把 sys.modules["webview"] 换成假模块，
    假模块的 Window 就是个 object —— 直接 `import webview` 会拿到它，
    于是本文件所有"方法是否存在"的断言全部误报。这里强制取真模块。
    """
    import importlib

    import webview

    if getattr(webview, "__file__", None) is None:
        sys.modules.pop("webview", None)
        webview = importlib.import_module("webview")
    return webview


@pytest.fixture(scope="module")
def main_tree():
    with open(MAIN_PY, "r", encoding="utf-8") as f:
        return ast.parse(f.read(), filename=MAIN_PY)


def _window_calls(tree):
    """找出所有 `window.<name>(...)` 形式的真实调用（忽略注释/字符串）。"""
    calls = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        # 只认名字就叫 window 的变量（覆盖率足够，且不会误伤 obj.window.xxx）
        if isinstance(func.value, ast.Name) and func.value.id == "window":
            calls.add(func.attr)
    return calls


def _on_show_body(tree):
    """取出 on_show 函数的源码片段（用于检查容错写法）。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "on_show":
            return ast.get_source_segment(open(MAIN_PY, encoding="utf-8").read(), node)
    return None


def test_window_calls_were_found(main_tree):
    """保护性断言：没找到任何调用说明检测逻辑失效了。"""
    calls = _window_calls(main_tree)
    assert calls, "没找到任何 window.<method>() 调用，检测逻辑可能失效"


def test_called_window_methods_exist(main_tree):
    """main.py 里 window.<name>(...) 的方法必须真实存在于 pywebview。"""
    webview = _real_webview()

    called = _window_calls(main_tree)
    missing = []
    for name in sorted(called):
        attr = getattr(webview.Window, name, None)
        if attr is None:
            missing.append((name, "不存在"))
        elif not callable(attr):
            missing.append((name, "不是方法（是属性，不能调用）"))

    assert not missing, (
        "main.py 调用了 pywebview 上不存在的 Window 方法，运行到那一步会抛 TypeError：\n"
        + "\n".join(f"  window.{n}() —— {why}" for n, why in missing)
    )


def test_focus_is_not_called(main_tree):
    """专门钉住 focus 这个坑。

    pywebview 里跟 focus 有关的是 bool 属性 `focused`，
    没有方法。把窗口带回前台要用 `restore()`。
    """
    called = _window_calls(main_tree)
    assert "focus" not in called, (
        "pywebview 没有 focus() 方法（只有 bool 属性 focused）。"
        "把窗口带回前台请用 window.restore()。"
    )


def test_tray_show_uses_restore(window_tree=None):
    """托盘"显示"回调应当用 show/restore，并且包在 try 里。

    托盘回调抛异常时 pystray 只会打印 traceback 然后继续 ——
    用户看到的是"点了没反应"，很难排查。所以这里必须容错。
    """
    with open(MAIN_PY, "r", encoding="utf-8") as f:
        text = f.read()
    import re

    match = re.search(r"def on_show\(icon, item\):(.*?)(?=\n    def |\ndef )", text, re.S)
    assert match, "找不到 on_show 回调"
    body = match.group(0)
    assert "window.show()" in body or "window.restore()" in body
    assert "except" in body, "on_show 里的窗口操作必须容错"


def test_window_destroy_is_valid():
    """退出路径用的 destroy 必须存在（否则只能 os._exit）。"""
    webview = _real_webview()

    assert callable(getattr(webview.Window, "destroy", None))
