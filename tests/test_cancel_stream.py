"""取消令牌的回调机制 + 流式请求能被"秒停"的回归测试。

背景（用户实测）：点停止后界面卡在「正在停...」几分钟甚至更久。
根因是 requests 的读超时 300 秒 —— 模型不吐字时 iter_lines() 一直阻塞，
循环体里的 raise_if_cancelled() 根本没机会执行。
修法是 cancel 时从另一个线程 close 掉 response，让读立刻抛异常。
"""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.cancel import CancelToken, CancelledError  # noqa: E402


# --------------------------------------------------------------------------
# CancelToken.on_cancel
# --------------------------------------------------------------------------


def test_on_cancel_runs_callback():
    token = CancelToken()
    hits = []
    token.on_cancel(lambda: hits.append(1))
    assert hits == []
    assert token.cancel("test") is True
    assert hits == [1]


def test_on_cancel_runs_immediately_when_already_cancelled():
    token = CancelToken()
    token.cancel("already")
    hits = []
    token.on_cancel(lambda: hits.append(1))
    assert hits == [1], "已经取消了才注册的回调也必须执行"


def test_callback_exception_does_not_break_cancel():
    token = CancelToken()

    def boom():
        raise RuntimeError("callback blew up")

    hits = []
    token.on_cancel(boom)
    token.on_cancel(lambda: hits.append(1))
    assert token.cancel("test") is True
    assert token.cancelled is True
    assert hits == [1], "一个回调炸了不能影响后面的回调和取消本身"


def test_remove_cancel_callback():
    token = CancelToken()
    hits = []
    fn = token.on_cancel(lambda: hits.append(1))
    token.remove_cancel_callback(fn)
    token.cancel("test")
    assert hits == [], "注销过的回调不该再执行"


def test_child_inherits_cancel_callbacks_are_per_token():
    parent = CancelToken()
    child = parent.child()
    parent_hits = []
    parent.on_cancel(lambda: parent_hits.append("p"))
    parent.cancel("test")
    assert child.cancelled is True
    assert parent_hits == ["p"]


# --------------------------------------------------------------------------
# 流式请求的取消：模拟 requests 的阻塞读取
# --------------------------------------------------------------------------


class _BlockingResponse:
    """模拟 requests 的流式响应：iter_lines 一直阻塞，直到 close() 才抛错。"""

    def __init__(self):
        self.closed = threading.Event()
        self.started = threading.Event()

    def raise_for_status(self):
        return None

    def close(self):
        self.closed.set()

    def iter_lines(self, decode_unicode=False):
        self.started.set()
        # 模拟"模型不吐字"：这里一直卡着，只有 close() 能打断
        while not self.closed.is_set():
            time.sleep(0.02)
        raise RuntimeError("Connection broken: read aborted (simulated)")


def _run_stream(response, token):
    """复刻 provider 里的读循环与取消语义。"""
    from agent.cancel import CancelledError

    token.on_cancel(response.close)
    try:
        for _ in response.iter_lines():
            token.raise_if_cancelled()
    except CancelledError:
        raise
    except Exception as exc:
        if token.cancelled:
            raise CancelledError("cancelled while streaming") from exc
        raise


def test_cancel_interrupts_blocked_stream_quickly():
    """关键回归：取消必须在 2 秒内打断阻塞的流，而不是等到超时。"""
    response = _BlockingResponse()
    token = CancelToken()
    result = {}

    def worker():
        try:
            _run_stream(response, token)
            result["outcome"] = "finished"
        except CancelledError:
            result["outcome"] = "cancelled"
        except Exception as exc:  # noqa: BLE001
            result["outcome"] = "error:%s" % exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    assert response.started.wait(2), "读取没有开始"

    started_at = time.time()
    token.cancel("user clicked stop")
    thread.join(timeout=2.0)
    elapsed = time.time() - started_at

    assert not thread.is_alive(), "取消后读循环仍然卡着"
    assert result["outcome"] == "cancelled"
    assert elapsed < 2.0, f"取消用了 {elapsed:.2f}s，太慢"


def test_stream_without_cancel_completes_normally():
    class _QuickResponse(_BlockingResponse):
        def iter_lines(self, decode_unicode=False):
            yield b"data: {}\n"
            yield b"[DONE]\n"

    token = CancelToken()
    _run_stream(_QuickResponse(), token)
