"""MollyPaw — max_tokens 必须"默认不发"。

事故（用户实测）：桌面端发消息全是 400。
上游原话：
    This endpoint's maximum context length is 262144 tokens.
    However, you requested about 2048012 tokens
    (12 of text input, 2048000 in the output).

用户配置里 max_tokens = 2048000（两百万），比模型总上下文还大。
更根本的问题是：**这个参数本来就不该默认发。**

为什么"不发"才是对的：
  - 有些模型（尤其推理模型）不认 max_tokens，带了直接 400；
  - 填一个超出模型上下文的值，上游会算成"输入 + 输出 > 上限" → 400；
  - OpenAI 兼容接口里它本来就是可选项，不带 = 服务端默认，几乎总是安全。

规则：只有显式设了**正数**才发。0 / 空 / None / 非数字 / 负数 一律不带。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.providers.openai_provider import OpenAIProvider


def make(max_tokens):
    return OpenAIProvider(
        api_key="test-key",
        base_url="http://127.0.0.1:1/v1",
        model="test-model",
        protocol="chat",
        max_tokens=max_tokens,
    )


# --------------------------------------------------------------------------
# 取值规则
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", [0, None, "", "abc", -5, -1])
def test_no_limit_when_not_positive(value):
    """非正数/无效值一律表示"不带该参数"。"""
    provider = make(value)
    assert provider._effective_max_tokens(None) is None


@pytest.mark.parametrize("value,expected", [(2048, 2048), ("4096", 4096), (1, 1)])
def test_limit_when_positive(value, expected):
    provider = make(value)
    assert provider._effective_max_tokens(None) == expected


def test_override_takes_precedence():
    provider = make(0)
    assert provider._effective_max_tokens(1024) == 1024
    # override=0 仍然表示"不带"
    assert provider._effective_max_tokens(0) is None


# --------------------------------------------------------------------------
# 实际 payload
# --------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


@pytest.fixture
def capture_post():
    """拦截 _post，抓 payload，不联网。"""
    box = {}

    def install(provider, response_data):
        def fake_post(path, payload):
            box["path"] = path
            box["payload"] = payload
            return _FakeResp(response_data)
        provider._post = fake_post
        return box

    return install


def test_chat_omits_max_tokens_when_zero(capture_post):
    provider = make(0)
    box = capture_post(provider, {"choices": [{"message": {"content": "ok"}}], "usage": {}})
    provider.chat([{"role": "user", "content": "hi"}])
    assert "max_tokens" not in box["payload"], (
        "max_tokens=0 时不该把该参数发出去 —— 那正是 400 的来源之一"
    )


def test_chat_sends_max_tokens_when_set(capture_post):
    provider = make(2048)
    box = capture_post(provider, {"choices": [{"message": {"content": "ok"}}], "usage": {}})
    provider.chat([{"role": "user", "content": "hi"}])
    assert box["payload"]["max_tokens"] == 2048


def test_responses_protocol_omits_when_zero(capture_post):
    provider = make(0)
    provider.protocol = "responses"
    box = capture_post(provider, {"output_text": "ok", "usage": {}})
    provider.chat([{"role": "user", "content": "hi"}])
    assert "max_output_tokens" not in box["payload"]


def test_responses_protocol_sends_when_set(capture_post):
    provider = make(4096)
    provider.protocol = "responses"
    box = capture_post(provider, {"output_text": "ok", "usage": {}})
    provider.chat([{"role": "user", "content": "hi"}])
    assert box["payload"]["max_output_tokens"] == 4096


# --------------------------------------------------------------------------
# 流式路径同样规则
# --------------------------------------------------------------------------


def test_stream_omits_max_tokens_when_zero():
    """流式分支也必须遵守同一规则（它是桌面端现在实际走的路径）。"""
    provider = make(0)
    captured = {}

    class FakeStreamResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def iter_lines(self, decode_unicode=False):
            yield b'data: {"choices":[{"delta":{"content":"ok"}}]}'
            yield b'data: [DONE]'

        def close(self):
            pass

    import requests as _requests

    original = _requests.post

    def fake_post(url, **kwargs):
        captured["json"] = kwargs.get("json")
        return FakeStreamResp()

    _requests.post = fake_post
    try:
        provider.stream_chat([{"role": "user", "content": "hi"}])
    finally:
        _requests.post = original

    assert "max_tokens" not in captured["json"], (
        f"流式请求不该带 max_tokens，实际 payload 键：{sorted(captured['json'])}"
    )


def test_stream_sends_max_tokens_when_set():
    provider = make(3072)
    captured = {}

    class FakeStreamResp:
        def raise_for_status(self):
            pass

        def iter_lines(self, decode_unicode=False):
            yield b'data: {"choices":[{"delta":{"content":"ok"}}]}'
            yield b'data: [DONE]'

        def close(self):
            pass

    import requests as _requests

    original = _requests.post

    def fake_post(url, **kwargs):
        captured["json"] = kwargs.get("json")
        return FakeStreamResp()

    _requests.post = fake_post
    try:
        provider.stream_chat([{"role": "user", "content": "hi"}])
    finally:
        _requests.post = original

    assert captured["json"]["max_tokens"] == 3072


# --------------------------------------------------------------------------
# 默认配置
# --------------------------------------------------------------------------


def test_default_config_has_no_max_tokens():
    """默认配置必须是 0（不带），不是某个"看起来合理"的数字。"""
    from agent.core import AgentCore

    assert AgentCore.DEFAULT_CONFIG["max_tokens"] == 0


def test_final_text_does_not_invent_limit():
    """_request_final_text 不能把"不带"（0）悄悄顶成 4096。

    早先无条件 max(old, 4096)，等于替用户带上了参数 ——
    而有些模型带它就 400。
    """
    import inspect
    from agent.core import AgentCore

    src = inspect.getsource(AgentCore._request_final_text)
    # 必须是有条件的抬高，不能无条件 max(...)
    assert "if old_max_tokens and old_max_tokens > 0" in src, (
        "_request_final_text 里必须在 old_max_tokens > 0 时才抬高 max_tokens"
    )


# --------------------------------------------------------------------------
# 前端
# --------------------------------------------------------------------------


def test_frontend_allows_empty_max_tokens():
    """前端必须允许留空（留空 = 不发该参数）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "frontend", "index.html"), encoding="utf-8") as f:
        html = f.read()
    match = __import__("re").search(r'<input[^>]*id="cfg-max-tokens"[^>]*>', html)
    assert match, "找不到 cfg-max-tokens 输入框"
    tag = match.group(0)
    # 不再要求最小值 256（那会让用户没法留空/填小值）
    assert 'min="256"' not in tag, f"不该再限制最小 256：{tag}"
    assert "留空" in html, "界面上应说明可以留空"


def test_frontend_maps_empty_to_zero():
    """前端把空值映射成 0（=不发），不是某个默认数字。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "frontend", "app.js"), encoding="utf-8") as f:
        js = f.read()
    assert "cfg.max_tokens = 0" in js, "空值应该映射成 0"
    # 只看**代码**（注释里提到过这个旧写法，不能算）
    code = "\n".join(
        line for line in js.splitlines()
        if not line.strip().startswith("//")
    )
    assert "Math.max(256" not in code, "不该再强制最小 256"
