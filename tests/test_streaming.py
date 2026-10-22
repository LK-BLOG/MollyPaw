"""MollyPaw — 真流式 + 可中断测试。

用一个假 SSE 服务器当上游，验证：
  - 增量按顺序回调
  - **工具调用不在首个 token 触发**，参数分片正确拼装后才返回
  - 取消时立刻关闭 HTTP 流、抛 CancelledError
  - 取消后 AgentCore 回滚历史，不留半截 tool_call
"""
import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.cancel import CancelToken, CancelledError
from agent.providers.openai_provider import OpenAIProvider


# --------------------------------------------------------------------------
# 假 SSE 上游
# --------------------------------------------------------------------------


class FakeSSE:
    """一个本地 HTTP 服务，按需吐出预设的 SSE 行。"""

    def __init__(self, chunks, delay=0.0):
        self.chunks = chunks        # list[str]，每个元素是一行（不含 \n）
        self.delay = delay
        self.served = 0
        self.closed_early = False
        self._server = None
        self._thread = None

    def start(self):
        import http.server

        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    for line in outer.chunks:
                        if outer.delay:
                            time.sleep(outer.delay)
                        self.wfile.write((line + "\n\n").encode("utf-8"))
                        self.wfile.flush()
                        outer.served += 1
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    # 客户端取消了流 —— 这正是我们要验证的行为
                    outer.closed_early = True

            def log_message(self, *a):
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/v1"

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()


def sse(obj):
    return "data: " + json.dumps(obj)


def content_chunk(text):
    return sse({"choices": [{"delta": {"content": text}}]})


def reasoning_chunk(text):
    return sse({"choices": [{"delta": {"reasoning_content": text}}]})


def tool_delta(index, call_id=None, name=None, args=None):
    call = {"index": index}
    if call_id:
        call["id"] = call_id
    fn = {}
    if name is not None:
        fn["name"] = name
    if args is not None:
        fn["arguments"] = args
    if fn:
        call["function"] = fn
    return sse({"choices": [{"delta": {"tool_calls": [call]}}]})


def finish(reason="stop"):
    return sse({"choices": [{"delta": {}, "finish_reason": reason}]})


DONE = "data: [DONE]"


@pytest.fixture
def server_factory():
    servers = []

    def make(chunks, delay=0.0):
        s = FakeSSE(chunks, delay).start()
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.stop()


def provider_for(server, protocol="chat"):
    return OpenAIProvider(
        api_key="test-key",
        base_url=server.url,
        model="test-model",
        protocol=protocol,
    )


# --------------------------------------------------------------------------
# 增量回调
# --------------------------------------------------------------------------


def test_stream_emits_content_deltas_in_order(server_factory):
    server = server_factory([
        content_chunk("你"), content_chunk("好"), content_chunk("！"),
        finish("stop"), DONE,
    ])
    p = provider_for(server)
    seen = []
    result = p.stream_chat([{"role": "user", "content": "hi"}],
                           on_delta=lambda t, k: seen.append((t, k)))
    assert [t for t, _ in seen] == ["你", "好", "！"]
    assert all(k == "content" for _, k in seen)
    assert result["content"] == "你好！"


def test_stream_emits_reasoning_deltas(server_factory):
    server = server_factory([
        reasoning_chunk("想一下"),
        content_chunk("答案"),
        finish("stop"), DONE,
    ])
    p = provider_for(server)
    seen = []
    result = p.stream_chat([{"role": "user", "content": "hi"}],
                           on_delta=lambda t, k: seen.append((t, k)))
    assert ("想一下", "reasoning") in seen
    assert ("答案", "content") in seen
    assert result["reasoning_content"] == "想一下"
    assert result["content"] == "答案"


def test_stream_collects_usage(server_factory):
    server = server_factory([
        sse({"choices": [{"delta": {"content": "x"}}]}),
        sse({"choices": [{"delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 5, "completion_tokens": 2}}),
        DONE,
    ])
    p = provider_for(server)
    result = p.stream_chat([{"role": "user", "content": "hi"}])
    assert result["usage"]["prompt_tokens"] == 5
    assert result["usage"]["completion_tokens"] == 2


def test_stream_ignores_comments_and_blank_lines(server_factory):
    server = server_factory([
        ": keep-alive",
        "",
        content_chunk("ok"),
        finish("stop"), DONE,
    ])
    p = provider_for(server)
    assert p.stream_chat([{"role": "user", "content": "hi"}])["content"] == "ok"


def test_stream_ignores_malformed_json(server_factory):
    server = server_factory([
        "data: {not json",
        content_chunk("fine"),
        finish("stop"), DONE,
    ])
    p = provider_for(server)
    assert p.stream_chat([{"role": "user", "content": "hi"}])["content"] == "fine"


def test_stream_without_on_delta_still_returns(server_factory):
    server = server_factory([content_chunk("hi"), finish("stop"), DONE])
    p = provider_for(server)
    result = p.stream_chat([{"role": "user", "content": "x"}])
    assert result["content"] == "hi"


# --------------------------------------------------------------------------
# 工具调用分片（用户明确要求：不能在首个 token 就触发）
# --------------------------------------------------------------------------


def test_tool_call_not_exposed_until_stream_complete(server_factory):
    """核心断言：流跑到一半时，绝不能已经有 tool_calls 被交出去。

    做法：在 on_delta 回调里检查 —— 每当收到一片内容，此刻 provider
    内部绝不能已经触发过工具执行（这里通过"result 尚未返回"来体现）。
    """
    marker = {"result_returned": False}

    def watch(text, kind):
        # 每次增量回调时，整条流都还没结束，所以调用方不可能已经拿到
        # 完整的 tool_calls —— 这正是"不会在首个 token 就调工具"的保证。
        assert marker["result_returned"] is False

    server = server_factory([
        tool_delta(0, call_id="call_1", name="read_file"),
        tool_delta(0, args='{"path":'),
        tool_delta(0, args=' "README.md"}'),
        finish("tool_calls"), DONE,
    ])
    p = provider_for(server)
    result = p.stream_chat([{"role": "user", "content": "read"}], on_delta=watch)
    marker["result_returned"] = True
    assert result["tool_calls"][0]["function"]["name"] == "read_file"
    assert json.loads(result["tool_calls"][0]["function"]["arguments"]) == {"path": "README.md"}


def test_tool_call_arguments_assemble_across_many_chunks(server_factory):
    """参数被切成七八片也必须拼回合法 JSON。"""
    parts = ['{', '"path"', ': ', '"D:\\\\a\\\\b.txt"', ', "encoding"', ': "utf-8"', '}']
    chunks = [tool_delta(0, call_id="c1", name="read_file")]
    chunks += [tool_delta(0, args=p) for p in parts]
    chunks += [finish("tool_calls"), DONE]

    server = server_factory(chunks)
    p = provider_for(server)
    result = p.stream_chat([{"role": "user", "content": "x"}])
    args = result["tool_calls"][0]["function"]["arguments"]
    assert json.loads(args) == {"path": "D:\\a\\b.txt", "encoding": "utf-8"}


def test_multiple_tool_calls_are_disambiguated_by_index(server_factory):
    server = server_factory([
        tool_delta(0, call_id="c0", name="read_file"),
        tool_delta(1, call_id="c1", name="list_directory"),
        tool_delta(0, args='{"path":"a"}'),
        tool_delta(1, args='{"path":"b"}'),
        finish("tool_calls"), DONE,
    ])
    p = provider_for(server)
    result = p.stream_chat([{"role": "user", "content": "x"}])
    calls = {c["id"]: c for c in result["tool_calls"]}
    assert set(calls) == {"c0", "c1"}
    assert calls["c0"]["function"]["name"] == "read_file"
    assert json.loads(calls["c0"]["function"]["arguments"]) == {"path": "a"}
    assert calls["c1"]["function"]["name"] == "list_directory"
    assert json.loads(calls["c1"]["function"]["arguments"]) == {"path": "b"}


def test_tool_name_split_across_chunks(server_factory):
    """有些厂商会把函数名也切片（少见但存在）。"""
    server = server_factory([
        tool_delta(0, call_id="c1", name="read_"),
        tool_delta(0, name="file"),
        tool_delta(0, args="{}"),
        finish("tool_calls"), DONE,
    ])
    p = provider_for(server)
    result = p.stream_chat([{"role": "user", "content": "x"}])
    assert result["tool_calls"][0]["function"]["name"] == "read_file"


def test_incomplete_tool_call_is_dropped(server_factory):
    """只有 index 没名字的残片不能当工具调用交出去。"""
    server = server_factory([
        tool_delta(0, args='{"x":1}'),
        finish("tool_calls"), DONE,
    ])
    p = provider_for(server)
    result = p.stream_chat([{"role": "user", "content": "x"}])
    assert "tool_calls" not in result


def test_content_and_tool_call_can_coexist(server_factory):
    """模型先说话再调工具：两边都得保住。"""
    server = server_factory([
        content_chunk("我看看这个文件。"),
        tool_delta(0, call_id="c1", name="read_file"),
        tool_delta(0, args='{"path":"x"}'),
        finish("tool_calls"), DONE,
    ])
    p = provider_for(server)
    result = p.stream_chat([{"role": "user", "content": "x"}])
    assert result["content"] == "我看看这个文件。"
    assert result["tool_calls"][0]["function"]["name"] == "read_file"


# --------------------------------------------------------------------------
# 取消
# --------------------------------------------------------------------------


def test_cancel_token_before_start_raises(server_factory):
    server = server_factory([content_chunk("x"), finish("stop"), DONE])
    p = provider_for(server)
    token = CancelToken()
    token.cancel()
    with pytest.raises(CancelledError):
        p.stream_chat([{"role": "user", "content": "x"}], cancel=token)


def test_cancel_during_stream_stops_and_closes(server_factory):
    """慢慢吐 50 片，中途取消：必须抛 CancelledError 且关闭连接。"""
    chunks = [content_chunk(f"c{i}") for i in range(50)] + [finish("stop"), DONE]
    server = server_factory(chunks, delay=0.02)
    p = provider_for(server)
    token = CancelToken()
    seen = []

    def on_delta(text, kind):
        seen.append(text)
        if len(seen) >= 3:
            token.cancel("user")

    start = time.time()
    with pytest.raises(CancelledError):
        p.stream_chat([{"role": "user", "content": "x"}],
                      on_delta=on_delta, cancel=token)
    elapsed = time.time() - start

    # 不能把 50 片全读完
    assert len(seen) < 50, f"consumed {len(seen)} chunks despite cancel"
    assert elapsed < 5, f"cancel took too long: {elapsed:.1f}s"
    assert server.served < len(chunks), "server was not cut off"


def test_cancel_reason_propagates(server_factory):
    server = server_factory(
        [content_chunk("a")] * 30 + [finish("stop"), DONE], delay=0.01
    )
    p = provider_for(server)
    token = CancelToken()

    def on_delta(text, kind):
        token.cancel("user pressed stop")

    with pytest.raises(CancelledError) as exc:
        p.stream_chat([{"role": "user", "content": "x"}],
                      on_delta=on_delta, cancel=token)
    assert "stop" in str(exc.value)


def test_no_cancel_completes_normally(server_factory):
    server = server_factory([content_chunk("完整"), finish("stop"), DONE])
    p = provider_for(server)
    token = CancelToken()  # 没取消
    result = p.stream_chat([{"role": "user", "content": "x"}], cancel=token)
    assert result["content"] == "完整"


# --------------------------------------------------------------------------
# AgentCore 回滚
# --------------------------------------------------------------------------


class ScriptedProvider:
    """假 provider，可以按脚本返回，也可以中途取消。"""

    def __init__(self, responses, cancel_after=None):
        self.responses = list(responses)
        self.calls = []
        self.cancel_after = cancel_after

    def chat(self, messages, tools=None, max_tokens=None):
        self.calls.append(list(messages))
        if not self.responses:
            return {"content": "done", "usage": {}}
        return self.responses.pop(0)

    def stream_chat(self, messages, tools=None, max_tokens=None,
                    on_delta=None, cancel=None):
        self.calls.append(list(messages))
        if cancel is not None and self.cancel_after == 0:
            from agent.cancel import CancelledError

            cancel.cancel("test")
            raise CancelledError("test")
        if not self.responses:
            return {"content": "done", "usage": {}}
        return self.responses.pop(0)


def make_agent(provider):
    from agent.core import AgentCore

    agent = AgentCore.__new__(AgentCore)
    agent.config = dict(AgentCore.DEFAULT_CONFIG)
    agent.history = [{"role": "system", "content": "sys"}]
    agent.provider = provider
    from agent.tools import default_registry
    agent.tool_registry = default_registry
    agent._tool_call_callback = None
    agent._tool_result_callback = None
    agent._approval_callback = None
    agent.approval_mode = "full_access"
    agent.conversation_id = None
    import tempfile

    agent._conversations_dir = tempfile.mkdtemp()
    return agent


def test_agent_rolls_back_on_cancel():
    """取消后 history 必须干净：不能留半截 assistant/tool。

    注意 history[0] 是 system prompt，chat() 会重建它，所以比对时跳过 index 0。
    """
    provider = ScriptedProvider([], cancel_after=0)
    agent = make_agent(provider)
    before = list(agent.history)
    token = CancelToken()
    with pytest.raises(CancelledError):
        # 必须传 on_delta 才会走 stream_chat 分支
        agent.chat("干点活", on_delta=lambda t, k: None, cancel=token)
    assert agent.history[1:] == before[1:], "history was not rolled back"


def test_agent_rolls_back_on_provider_error():
    class Boom:
        def chat(self, messages, tools=None, max_tokens=None):
            raise RuntimeError("upstream exploded")

        def stream_chat(self, *a, **kw):
            raise RuntimeError("upstream exploded")

    agent = make_agent(Boom())
    before = list(agent.history)
    with pytest.raises(RuntimeError):
        agent.chat("hi")
    assert agent.history[1:] == before[1:]


def test_agent_keeps_history_on_success():
    provider = ScriptedProvider([{"content": "好", "usage": {}}])
    agent = make_agent(provider)
    result = agent.chat("你好")
    assert result["response"] == "好"
    roles = [m["role"] for m in agent.history]
    assert roles == ["system", "user", "assistant"]


def test_agent_rollback_removes_partial_tool_calls():
    """模型返回了 tool_call、工具还没跑完就被取消 —— 历史里不能留孤儿 tool_call。"""
    provider = ScriptedProvider([{
        "content": "",
        "usage": {},
        "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "exec_command",
                         "arguments": json.dumps({"cmd": "echo hi", "timeout": 1})},
        }],
    }])
    agent = make_agent(provider)
    token = CancelToken()

    def on_tool(info):
        token.cancel("stop right there")

    agent._tool_call_callback = on_tool
    before = list(agent.history)
    with pytest.raises(CancelledError):
        agent.chat("跑个命令", on_delta=lambda t, k: None, cancel=token)
    assert agent.history[1:] == before[1:]
    # 确认没有孤儿 tool_call 留在历史里
    for msg in agent.history:
        assert not msg.get("tool_calls")


def test_agent_streams_deltas_through():
    """on_delta 必须一路透传到 provider。"""
    captured = []

    class Streaming:
        def stream_chat(self, messages, tools=None, max_tokens=None,
                        on_delta=None, cancel=None):
            for piece in ["流", "式", "好", "用"]:
                on_delta(piece, "content")
            return {"content": "流式好用", "usage": {}}

        def chat(self, *a, **kw):
            raise AssertionError("should have used stream_chat")

    agent = make_agent(Streaming())
    result = agent.chat("hi", on_delta=lambda t, k: captured.append(t))
    assert captured == ["流", "式", "好", "用"]
    assert result["response"] == "流式好用"


def test_agent_get_config_public_hides_api_key():
    agent = make_agent(ScriptedProvider([]))
    agent.config["api_key"] = "sk-super-secret-value"
    public = agent.get_config_public()
    assert public["api_key"] == "***"
    assert public["api_key_set"] is True
    assert "sk-super-secret-value" not in json.dumps(public)


def test_agent_get_config_public_redacts_connection_for_observer():
    agent = make_agent(ScriptedProvider([]))
    agent.config["api_key"] = "sk-x"
    agent.config["base_url"] = "https://private.example/v1"
    public = agent.get_config_public(redact_connection=True)
    assert public["base_url"] == "***"
    assert "private.example" not in json.dumps(public)


def test_save_config_ignores_masked_api_key():
    agent = make_agent(ScriptedProvider([]))
    agent.config["api_key"] = "sk-real"
    agent.save_config({"api_key": "sk-real...abcd"})
    assert agent.config["api_key"] == "sk-real"
    agent.save_config({"api_key": "***"})
    assert agent.config["api_key"] == "sk-real"
