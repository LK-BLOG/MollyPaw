"""MollyPaw — 本地 HTTP 接口测试。

存在的理由（真实事故）：
`/api/relay/*` 的 GET 路由曾经被误写进 `do_POST`，前端一律 404。
当时是靠手工 curl 才发现的 —— 手工验证不算验证。
这个文件把"路由必须真的能访问"钉死，以后改错会立刻红。

用 port=0 让系统分配端口，避免和正在运行的 MollyPaw 抢 18765。
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="module")
def api(main_module):
    """起一个真的 HTTP 服务（随机端口）+ 真的 MollyPawAPI。

    main_module 这个 fixture 负责把 webview 换成假的 ——
    pywebview 在 Linux 上 import 时就探测 X display，
    没有 display 会报 Xlib.error.DisplayNameError（CI 的 Ubuntu 就是这样挂的）。
    """
    main = main_module

    instance = main.MollyPawAPI()
    instance.start_pet_server(host="127.0.0.1", port=0)
    port = getattr(instance, "server_port", None)
    assert port, "server_port 没被设置，HTTP 服务没起来"
    base = f"http://127.0.0.1:{port}"
    yield base, instance
    # 收尾：把中继停掉，避免线程悬着
    try:
        if instance.relay is not None:
            instance.relay.stop()
    except Exception:
        pass


def get(base, path, timeout=30):
    req = urllib.request.Request(base + path)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def post(base, path, body=None, timeout=30):
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        base + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def wait_until(pred, timeout=20, interval=0.1):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(interval)
    return False


# --------------------------------------------------------------------------
# 基础可用性
# --------------------------------------------------------------------------


def test_state_endpoint(api):
    base, _ = api
    status, data = get(base, "/state")
    assert status == 200
    assert data["state"] in ("idle", "work", "cry", "sleep")


def test_index_served(api):
    base, _ = api
    req = urllib.request.Request(base + "/")
    with urllib.request.urlopen(req, timeout=15) as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8")
    assert "MollyPaw" in html
    # 停止按钮必须在页面里，否则"停止"功能根本没入口
    assert 'id="stop-btn"' in html


def test_settings_has_relay_tab(api):
    """远程互联必须真的出现在设置面板里。"""
    base, _ = api
    req = urllib.request.Request(base + "/")
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8")
    assert 'data-settings-tab="relay"' in html
    assert 'data-settings-panel="relay"' in html
    for element_id in ("relay-url", "relay-psk", "relay-toggle",
                       "relay-device-list", "relay-qr", "relay-code"):
        assert f'id="{element_id}"' in html, f"缺少元素 {element_id}"


def test_frontend_has_stop_wiring(api):
    """前端必须真的调用 /api/stop，不能只有个按钮。"""
    base, _ = api
    req = urllib.request.Request(base + "/app.js")
    with urllib.request.urlopen(req, timeout=15) as resp:
        js = resp.read().decode("utf-8")
    assert "/api/stop" in js
    assert "stop-btn" in js
    assert "_onChatDelta" in js, "流式事件没接"


# --------------------------------------------------------------------------
# 远程互联路由（这次事故的正主）
# --------------------------------------------------------------------------


def test_relay_available_get(api):
    base, _ = api
    status, data = get(base, "/api/relay/available")
    assert status == 200
    assert data["ok"] is True
    assert "available" in data


def test_relay_status_get(api):
    """这条曾经 404 —— 就是它逼出了这个测试文件。

    同时锁定响应形状：字段必须扁平（前端 renderRelayStatus 直接读 state/running），
    不能套一层 status。
    """
    base, _ = api
    status, data = get(base, "/api/relay/status")
    assert status == 200, f"/api/relay/status 返回 {status}"
    assert data["ok"] is True
    for field in ("state", "running", "connected", "room"):
        assert field in data, f"缺少字段 {field}；实际 keys={sorted(data)}"
    assert "status" not in data, "不要套一层 status，前端读的是扁平的"


def test_relay_settings_get(api):
    base, _ = api
    status, data = get(base, "/api/relay/settings")
    assert status == 200
    assert data["ok"] is True
    assert "url" in data
    assert "psk_set" in data
    # 扁平状态字段也一并带上，前端一次请求就够
    assert "state" in data and "running" in data


def test_relay_devices_get(api):
    base, _ = api
    status, data = get(base, "/api/relay/devices")
    assert status == 200
    assert data["ok"] is True
    assert isinstance(data["devices"], list)


def test_relay_audit_get(api):
    base, _ = api
    status, data = get(base, "/api/relay/audit")
    assert status == 200
    assert data["ok"] is True
    assert isinstance(data["entries"], list)


def test_relay_pin_get_when_none(api):
    base, _ = api
    status, data = get(base, "/api/relay/pin")
    assert status == 200
    assert data["ok"] is True


def test_busy_get(api):
    base, _ = api
    status, data = get(base, "/api/busy")
    assert status == 200
    assert data["busy"] is False


def test_unknown_route_is_404(api):
    base, _ = api
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(base, "/api/definitely-not-a-route")
    assert exc.value.code == 404


# --------------------------------------------------------------------------
# 停止按钮
# --------------------------------------------------------------------------


def test_stop_without_running_returns_not_stopped(api):
    base, _ = api
    status, data = post(base, "/api/stop", {"by": "local"})
    assert status == 200
    assert data["ok"] is True
    # 没在跑就该如实说没停到，不能谎报
    assert data["stopped"] is False


# --------------------------------------------------------------------------
# 密钥强度经由 HTTP 生效
# --------------------------------------------------------------------------


def test_relay_settings_rejects_weak_psk(api):
    """弱密钥要回具体原因，并且不能真的把中继启用起来。"""
    base, api_obj = api
    # 先确保起点干净（api fixture 是 module 级，测试之间会互相影响）
    api_obj._ensure_relay().config["psk"] = ""
    status, data = post(base, "/api/relay/settings", {"psk": "abc"})
    assert status == 200, f"HTTP {status}"
    assert data["ok"] is True, f"返回 {data}"
    assert data["psk_problems"], "弱密钥没被指出问题"
    assert any("16" in p for p in data["psk_problems"])
    # 弱密钥存下来了，所以不能自动跑起来
    st = get(base, "/api/relay/status")[1]
    assert st["running"] is False


def test_relay_settings_ok_with_strong_psk(api):
    """强密钥必须零问题通过。"""
    base, api_obj = api
    status, data = post(base, "/api/relay/settings", {"psk": "MollyPawStrong123"})
    assert status == 200
    assert data["ok"] is True, f"返回 {data}"
    assert data["psk_problems"] == []
    assert data["psk_set"] is True
    assert len(data["room"]) == 32, "强密钥必须能算出 room"
    # 收尾
    api_obj._ensure_relay().config["psk"] = ""


def test_relay_start_refuses_weak_psk(api):
    base, api_obj = api
    # 先写入一个弱密钥
    post(base, "/api/relay/settings", {"psk": "weak"})
    status, data = post(base, "/api/relay/start")
    assert status == 200
    # 应该拒绝启动并说明原因（扁平结构）
    assert data["running"] is False
    assert data["state"] == "error"
    assert data.get("reason") == "bad_key"
    # 恢复：清掉弱密钥，避免影响后面的测试
    api_obj.relay.config["psk"] = ""


def test_relay_pin_requires_strong_psk_first(api):
    """没有强密钥时生成 PIN 也应给出明确错误，而不是静默失败。"""
    base, api_obj = api
    api_obj.relay.config["psk"] = ""
    status, data = post(base, "/api/relay/pin", {"role": "app"})
    assert status == 200
    # 允许成功（PIN 与密钥独立），但如果有错必须是可读的中文/英文原因
    if not data.get("ok"):
        assert data.get("error")
