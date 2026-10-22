"""MollyPaw — 本地聊天不能因为"远程互联没开"而崩。

事故复盘（用户实测报的 traceback）：
    File "main.py", line 651, in do_POST
      token = service.controller.acquire("local")
    AttributeError: 'NoneType' object has no attribute 'acquire'

根因：`RelayController` 早先只在 RelayManager 里创建，而 MollyPawService
是独立构造的（controller=None）。于是只要用户没开远程互联，
**本地发消息就会崩** —— 这个关联极其反直觉，也说明接线错了。

修法：service 自己兜底建一个 controller；RelayManager 复用它。

这个文件把"controller 永远存在"钉死。
"""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.service import MollyPawService


# --------------------------------------------------------------------------
# controller 必须永远可用
# --------------------------------------------------------------------------


def test_service_has_controller_without_relay():
    """不开远程互联时，service 也必须自带 controller。"""
    svc = MollyPawService()
    assert svc.controller is not None, (
        "controller 为 None 会导致本地聊天崩（AttributeError: 'NoneType' "
        "object has no attribute 'acquire'）"
    )


def test_controller_exposes_required_api():
    """controller 的接口是 main.py 直接调的，缺一个就崩。"""
    svc = MollyPawService()
    ctrl = svc.controller
    for name in ("acquire", "release", "stop", "busy", "owner",
                 "add_approval", "resolve_approval", "list_approvals",
                 "cancel_all_approvals", "current_token"):
        assert hasattr(ctrl, name), f"controller 缺少 {name}"


def test_single_flight_lock_works():
    """单飞：同一时刻只能有一轮在跑。"""
    svc = MollyPawService()
    token1 = svc.controller.acquire("local")
    assert token1 is not None
    assert svc.controller.busy is True

    # 第二次必须拿不到
    token2 = svc.controller.acquire("app:phone-1")
    assert token2 is None, "单飞锁失效：允许多轮同时跑"

    svc.controller.release()
    assert svc.controller.busy is False
    token3 = svc.controller.acquire("local")
    assert token3 is not None
    svc.controller.release()


def test_stop_cancels_current_token():
    """停止必须真的取消当前令牌。"""
    svc = MollyPawService()
    token = svc.controller.acquire("local")
    assert token.cancelled is False
    stopped = svc.controller.stop(by="local")
    assert stopped is True
    assert token.cancelled is True
    svc.controller.release()


def test_stop_when_idle_returns_false():
    svc = MollyPawService()
    assert svc.controller.stop(by="local") is False


# --------------------------------------------------------------------------
# 审批：不超时，且能被本地解决
# --------------------------------------------------------------------------


def test_approval_blocks_until_resolved():
    """审批不超时；用户点了才返回。"""
    svc = MollyPawService()
    svc.controller.acquire("local")
    result = {}

    def wait_approval():
        result["approved"] = svc.controller.add_approval(
            name="write_file", args={"path": "x"}, danger="moderate"
        )

    t = threading.Thread(target=wait_approval, daemon=True)
    t.start()

    # 等审批登记进来
    deadline = time.time() + 5
    request_id = None
    while time.time() < deadline and not request_id:
        pending = svc.controller.list_approvals()
        if pending:
            request_id = pending[0]["request_id"]
        time.sleep(0.05)
    assert request_id, "审批没登记进列表"

    # 确认它真的在等（3 秒内不该自己结束）
    t.join(timeout=1.0)
    assert t.is_alive(), "审批不该自己返回（不设超时）"

    assert svc.controller.resolve_approval(request_id, True) is True
    t.join(timeout=3)
    assert result.get("approved") is True
    svc.controller.release()


def test_approval_cancelled_by_stop_raises():
    """点停止时挂着的审批要立刻放弃（抛 CancelledError），别悬着。"""
    from agent.cancel import CancelledError

    svc = MollyPawService()
    svc.controller.acquire("local")
    captured = {}

    def wait_approval():
        try:
            svc.controller.add_approval(name="exec_command", args={}, danger="dangerous")
            captured["outcome"] = "approved"
        except CancelledError:
            captured["outcome"] = "cancelled"

    t = threading.Thread(target=wait_approval, daemon=True)
    t.start()
    time.sleep(0.5)
    svc.controller.stop(by="local")
    t.join(timeout=5)
    assert captured.get("outcome") == "cancelled", captured
    svc.controller.release()


def test_approval_rejected():
    svc = MollyPawService()
    svc.controller.acquire("local")
    result = {}

    def wait_approval():
        result["approved"] = svc.controller.add_approval(
            name="fs.delete", args={"path": "y"}, danger="dangerous"
        )

    t = threading.Thread(target=wait_approval, daemon=True)
    t.start()
    deadline = time.time() + 5
    request_id = None
    while time.time() < deadline and not request_id:
        pending = svc.controller.list_approvals()
        if pending:
            request_id = pending[0]["request_id"]
        time.sleep(0.05)
    assert request_id
    svc.controller.resolve_approval(request_id, False)
    t.join(timeout=3)
    assert result.get("approved") is False
    svc.controller.release()


# --------------------------------------------------------------------------
# main.py 的接线
# --------------------------------------------------------------------------


def test_main_api_creates_service_with_controller():
    """MollyPawAPI 造出来的 service 必须带着可用的 controller。"""
    import main

    api = main.MollyPawAPI()
    assert api.service.controller is not None
    # 能真的拿到锁 —— 这正是当初崩的那一行
    token = api.service.controller.acquire("local")
    assert token is not None
    api.service.controller.release()


def test_main_stop_endpoint_does_not_crash():
    """没在跑的时候点停止也应正常返回，而不是抛异常。"""
    import main
    import json

    api = main.MollyPawAPI()
    res = json.loads(api.stop_chat("{}"))
    assert res["ok"] is True
    assert res["stopped"] is False


# --------------------------------------------------------------------------
# RelayManager 必须复用 service 的 controller
# --------------------------------------------------------------------------


def test_relay_manager_reuses_service_controller(tmp_path):
    """RelayManager 不能另造一个 controller。

    否则本地 UI 和手机会各持一把单飞锁：
    手机点停止停不掉电脑上的那一轮，两边还能同时跑两轮 agent。
    """
    from agent.relay.devices import DeviceStore
    from agent.relay.manager import RelayManager

    svc = MollyPawService()
    mgr = RelayManager(svc, config={"psk": "MollyPawTest1234"})
    mgr.devices = DeviceStore(path=str(tmp_path / "devices.json"))

    assert mgr.controller is svc.controller, (
        "RelayManager 应该复用 service.controller，而不是新建一个 —— "
        "否则单飞锁/取消/审批表会分裂成两份"
    )


def test_relay_manager_fallback_when_service_lacks_controller(tmp_path):
    """万一 service 没有 controller，RelayManager 也得能自建（容错）。"""
    from agent.relay.devices import DeviceStore
    from agent.relay.manager import RelayManager

    class Bare:
        controller = None

    mgr = RelayManager(Bare(), config={"psk": "MollyPawTest1234"})
    mgr.devices = DeviceStore(path=str(tmp_path / "devices.json"))
    assert mgr.controller is not None
    assert mgr.controller.acquire("local") is not None
