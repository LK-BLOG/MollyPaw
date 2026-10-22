"""MollyPaw — 模拟手机客户端（CLI）端到端测试。

这是"CLI 到底能不能用"的自动化断言，不靠手敲命令。
链路：本地中继 + 真实 RelayManager（PC 端）+ PhoneClient（模拟手机）
全程真实加密、真实 WS、真实配对码。

用真实 AgentCore 之外的东西（假 provider）避免调 LLM 花钱。
"""
import base64
import json
import os
import sys
import tempfile
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "MollyPaw-Relay"))

from relay.dev_server import DevRelay  # noqa: E402

from agent.relay import crypto as C  # noqa: E402
from agent.relay.manager import RelayManager  # noqa: E402
from tools.mp_phone import PhoneClient  # noqa: E402

PSK = "MollyPawCliTest99"
PORT = 18993


@pytest.fixture(scope="module")
def relay():
    r = DevRelay("127.0.0.1", PORT)
    r.start_background()
    yield r
    r.shutdown()


@pytest.fixture
def manager(tmp_path, relay):
    """一台挂了本地中继的 PC（不接 LLM）。"""
    from agent.relay.devices import DeviceStore
    from agent.service import MollyPawService

    service = MollyPawService()
    mgr = RelayManager(
        service,
        config={"url": f"ws://127.0.0.1:{PORT}/server", "psk": PSK},
    )
    # 用临时设备库，别碰真数据目录
    mgr.devices = DeviceStore(path=str(tmp_path / "relay" / "devices.json"))
    mgr.bridge.devices = mgr.devices

    mgr.start()
    _wait(lambda: mgr.status()["connected"], timeout=10)
    yield mgr
    mgr.stop()


def _wait(pred, timeout=5, interval=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(interval)
    return False


def _make_phone(mgr, role="app", name="测试手机"):
    """生成配对码并让模拟手机完成配对。返回 (client, 配对响应)。

    会话登记必须用**服务端授予的角色**（res["role"]），不是客户端自称的
    phone.role —— 客户端连上时一律自称 app，真实权限只有配对结果才知道。
    早先用了 phone.role，导致 observer 的请求被当成 app 放行，
    越权断言全部失效。
    """
    session = mgr.new_pairing(role)
    assert session.get("ok"), session
    phone = PhoneClient(
        f"ws://127.0.0.1:{PORT}/server", PSK, dev_name=name
    )
    # 用 pair_and_reconnect：配对成功后要用主 PSK 重连，
    # 否则服务端已作废配对密钥，后续请求全超时。
    ok, res = phone.pair_and_reconnect(session["code"])
    assert ok, f"配对失败: {res}"
    assert phone.wait_key(timeout=5)
    granted = res.get("role", role)
    mgr.bridge.register_session(phone.dev_id, phone.dev_id, granted, name)
    return phone, res


# --------------------------------------------------------------------------
# 配对
# --------------------------------------------------------------------------


def test_pairing_succeeds_with_code_only(relay, manager):
    """只用配对码就能配对 —— 手机上不需要先知道 PSK 才能找到房间。"""
    session = manager.new_pairing("app")
    assert session["ok"] is True
    assert session["code"].startswith("MP1.")
    assert session["room"] == C.derive_room(PSK)

    phone = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="小戡的手机")
    try:
        ok, res = phone.pair(session["code"])
        assert ok, res
        assert res["role"] == "app"
        assert len(base64.b64decode(res["token"])) == 32
    finally:
        phone.close()


def test_pairing_code_is_single_use(relay, manager):
    """配对码一次性。

    第二次使用会失败。失败的**具体形式**是 timeout 而不是 bad_code：
    PC 端在第一次配对成功后就把配对密钥清掉了（配对码一次性），
    所以第二次连帧都解不开，只能等到超时。

    这是合理行为 —— 从攻击者角度看，"解不开"和"被拒绝"一样安全，
    而且不给出额外的信息（不会泄露"这个码存在但用过了"）。
    """
    session = manager.new_pairing("app")

    phone1 = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="第一台")
    try:
        ok, _ = phone1.pair(session["code"])
        assert ok
    finally:
        phone1.close()

    phone2 = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="第二台")
    try:
        ok, err = phone2.pair(session["code"], timeout=6)
        assert not ok, "同一个配对码不该能配两次"
        # 允许 timeout（PC 已清密钥，解不开）或 bad_code（若实现改成先校验）
        assert err in ("bad_code", "timeout", "expired"), f"意外错误: {err}"
    finally:
        phone2.close()


def test_used_pairing_code_leaves_no_trace(relay, manager):
    """配对码用过之后，服务端不该再留着它（否则就是个长期后门）。"""
    session = manager.new_pairing("app")
    assert manager.current_pairing() is not None

    phone = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="用过就清")
    try:
        ok, _ = phone.pair(session["code"])
        assert ok
    finally:
        phone.close()

    assert manager.current_pairing() is None, (
        "配对码用过之后必须作废，不能继续留在内存里"
    )


def test_pairing_rejects_garbage_code(relay, manager):
    phone = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="坏码")
    try:
        with pytest.raises(ValueError):
            phone.pair("NOT-A-CODE")
    finally:
        phone.close()


def test_observer_role_paired(relay, manager):
    session = manager.new_pairing("observer")
    phone = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="只读端")
    try:
        ok, res = phone.pair(session["code"])
        assert ok
        assert res["role"] == "observer"
    finally:
        phone.close()


# --------------------------------------------------------------------------
# 设备 token 认证
# --------------------------------------------------------------------------


def test_auth_with_saved_token(relay, manager):
    session = manager.new_pairing("app")
    phone1 = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="手机")
    try:
        ok, res = phone1.pair(session["code"])
        assert ok
        token = res["token"]
        dev_id = phone1.dev_id
    finally:
        phone1.close()

    # 换一条新连接，用 token 认证（模拟重连）
    room = C.derive_room(PSK)
    phone2 = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_id=dev_id, dev_name="手机")
    try:
        phone2.url = f"ws://127.0.0.1:{PORT}/server"
        phone2.connect(room)
        assert phone2.wait_key(timeout=5)
        ok, res = phone2.auth(token)
        assert ok, res
        assert res["role"] == "app"
    finally:
        phone2.close()


def test_revoked_device_cannot_auth(relay, manager):
    session = manager.new_pairing("app")
    phone1 = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_name="待吊销")
    try:
        ok, res = phone1.pair(session["code"])
        assert ok
        token, dev_id = res["token"], phone1.dev_id
    finally:
        phone1.close()

    assert manager.revoke_device(dev_id) is True

    room = C.derive_room(PSK)
    phone2 = PhoneClient(f"ws://127.0.0.1:{PORT}/server", PSK, dev_id=dev_id)
    try:
        phone2.connect(room)
        assert phone2.wait_key(timeout=5)
        ok, err = phone2.auth(token)
        assert not ok
        assert err in ("revoked", "unknown")
    finally:
        phone2.close()


# --------------------------------------------------------------------------
# 业务方法
# --------------------------------------------------------------------------


def test_status_and_conversations(relay, manager):
    phone, _ = _make_phone(manager)
    try:
        ok, status = phone.call("status.get")
        assert ok, status
        assert "pet_state" in status

        ok, convs = phone.call("conv.list")
        assert ok
        assert isinstance(convs.get("conversations"), list)
    finally:
        phone.close()


def test_config_never_leaks_api_key(relay, manager):
    manager.service._ensure_agent().config["api_key"] = "sk-CLI-TEST-SECRET"
    phone, _ = _make_phone(manager)
    try:
        ok, cfg = phone.call("config.get")
        assert ok, cfg
        assert cfg["api_key"] == "***"
        assert "sk-CLI-TEST-SECRET" not in json.dumps(cfg)
    finally:
        phone.close()


def test_file_browse_and_download(relay, manager, tmp_path):
    target = tmp_path / "cli-test.txt"
    target.write_text("CLI 下载测试内容", encoding="utf-8")

    phone, _ = _make_phone(manager)
    try:
        ok, listing = phone.call("fs.list", {"path": str(tmp_path)})
        assert ok, listing
        assert any(e["name"] == "cli-test.txt" for e in listing["entries"])

        ok, blob = phone.call("fs.read", {"path": str(target)})
        assert ok, blob
        assert base64.b64decode(blob["data_b64"]).decode("utf-8") == "CLI 下载测试内容"
    finally:
        phone.close()


def test_observer_cannot_write(relay, manager):
    phone, _ = _make_phone(manager, role="observer", name="只读端")
    try:
        ok, err = phone.call("config.save", {"max_tokens": 999})
        assert not ok
        assert err == "forbidden"

        ok, err = phone.call("fs.list", {"path": "."})
        assert not ok
        assert err == "forbidden"
    finally:
        phone.close()


def test_device_list(relay, manager):
    phone, _ = _make_phone(manager, name="列设备用")
    try:
        ok, res = phone.call("device.list")
        assert ok, res
        assert isinstance(res.get("devices"), list)
        # 刚配对的这台应该在列表里
        assert any(d["dev_id"] == phone.dev_id for d in res["devices"])
    finally:
        phone.close()


def test_unknown_method_rejected(relay, manager):
    phone, _ = _make_phone(manager)
    try:
        ok, err = phone.call("does.not.exist")
        assert not ok
        assert err == "forbidden"
    finally:
        phone.close()


# --------------------------------------------------------------------------
# 停止
# --------------------------------------------------------------------------


def test_stop_when_idle_reports_not_stopped(relay, manager):
    phone, _ = _make_phone(manager)
    try:
        ok, res = phone.call("chat.stop")
        assert ok, res
        assert res["stopped"] is False
    finally:
        phone.close()


# --------------------------------------------------------------------------
# 二维码（CLI 的 qr 子命令）
# --------------------------------------------------------------------------


def test_cli_qr_command_writes_png(relay, manager, tmp_path):
    from tools.mp_phone import cmd_qr
    import argparse

    session = manager.new_pairing("app")
    out = tmp_path / "pair.png"
    args = argparse.Namespace(code=session["code"], out=str(out), scale=6)
    assert cmd_qr(args) == 0
    assert out.exists()
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_pairing_code_within_qr_version_limit(relay, manager):
    """配对码长度必须能塞进我们支持的二维码版本（<= 6）。"""
    from agent.relay import qr as qr_mod

    session = manager.new_pairing("app")
    code = session["code"]
    version = qr_mod.pick_version(len(code.encode("utf-8")))
    assert version <= qr_mod.MAX_VERSION, (
        f"配对码 {len(code)} 字符需要版本 {version}，超出支持范围 "
        f"{qr_mod.MAX_VERSION}"
    )
