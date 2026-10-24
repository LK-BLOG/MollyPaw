"""MollyPaw — 远程互联端到端测试。

跑法：本地中继（relay/dev_server.py）+ 真实 RelayManager（PC 端）
+ 一个模拟手机客户端，全程走真实加密与真实 WS。

不上 Cloudflare 也能验证整条链路；上 CF 的验证在 tools/relay_smoke.py。
"""
import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "MollyPaw-Relay"))

from relay.dev_server import DevRelay  # noqa: E402

import websocket  # noqa: E402

from agent.relay import crypto as C  # noqa: E402
from agent.relay import protocol as P  # noqa: E402
from agent.relay.manager import RelayManager  # noqa: E402

PSK = "MollyPawE2ETest99"
PORT = 18991


# --------------------------------------------------------------------------
# 模拟手机客户端
# --------------------------------------------------------------------------


class FakePhone:
    """一个精简版的手机端：握手 + 加密收发 + 请求/响应配对。"""

    def __init__(self, url, room, psk, role="app", dev_id="test-phone",
                 name="测试手机"):
        self.url = url
        self.room = room
        self.psk = psk
        self.role = role
        self.dev_id = dev_id
        self.name = name

        self.ws = None
        self.eph_priv = None
        self.eph_pub = None
        self.hs = None
        self.peer_eph = None
        self.peer_hs = None
        self.key = None
        self.pc_key = None
        self.seq = 0

        self.inbox = []                 # 收到的事件（非响应）
        self.responses = {}             # msg_id -> payload
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self.errors = []

    # -- 连接 --------------------------------------------------------------

    def connect(self, timeout=10):
        full = f"{self.url}?room={self.room}"
        self.ws = websocket.create_connection(full, timeout=timeout)
        self.eph_priv, self.eph_pub = C.gen_ephemeral()
        self.hs = os.urandom(C.HS_LEN)

        hello = P.hello_frame(self.room, self.role, dev=self.dev_id,
                              ts=int(time.time() * 1000))
        hello["eph"] = C.b64e(self.eph_pub)
        hello["hs"] = C.b64e(self.hs)
        self.ws.send(json.dumps(hello))
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.ws.settimeout(0.5)
                raw = self.ws.recv()
            except Exception:
                if self._stop.is_set():
                    break
                continue
            if not raw:
                continue
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            try:
                self._handle(frame)
            except Exception as exc:
                self.errors.append(str(exc))

    def _handle(self, frame):
        t = frame.get("t")
        if t == "error":
            with self.lock:
                self.inbox.append(("__error__", frame))
            return
        if t == "hello":
            if frame.get("f") == self.role:
                return
            if self.peer_eph is None and frame.get("eph"):
                self.peer_eph = C.b64d(frame["eph"])
                self.peer_hs = C.b64d(frame["hs"]) if frame.get("hs") else b""
                self._derive()
            return
        if t == "data":
            self._handle_data(frame)
            return
        if t in ("presence", "bye", "pong"):
            with self.lock:
                self.inbox.append((t, frame))
            return

    def _derive(self):
        if self.role == "pc":
            hs_pc, hs_app = self.hs, self.peer_hs
        else:
            hs_pc, hs_app = self.peer_hs, self.hs
        self.key = C.derive_session_key(
            self.eph_priv, self.peer_eph, self.psk, hs_pc, hs_app
        )

    def _handle_data(self, frame):
        payload = C.open_data_frame(self.key, frame)
        if payload.get("ok") is not None:
            with self.lock:
                self.responses[payload.get("id")] = payload
            return
        with self.lock:
            self.inbox.append((payload.get("m"), payload.get("p")))

    # -- 收发 --------------------------------------------------------------

    def call(self, method, params=None, timeout=10):
        """发一个请求并等响应。"""
        msg_id = f"{self.dev_id}-{method}-{time.time()}"
        self.seq += 1
        payload = P.payload(method, params, msg_id)
        frame = C.make_data_frame(self.key, self.room, self.role, self.seq,
                                  msg_id, payload)
        self.ws.send(json.dumps(frame))

        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if msg_id in self.responses:
                    resp = self.responses.pop(msg_id)
                    if resp.get("ok"):
                        return True, resp.get("r")
                    return False, resp.get("e")
            time.sleep(0.05)
        return False, "timeout"

    def wait_event(self, name, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                for i, (n, p) in enumerate(self.inbox):
                    if n == name:
                        return self.inbox.pop(i)[1]
            time.sleep(0.05)
        return None

    def drain(self):
        with self.lock:
            out = list(self.inbox)
            self.inbox.clear()
            return out

    def close(self):
        self._stop.set()
        try:
            self.ws.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def relay():
    r = DevRelay("127.0.0.1", PORT)
    r.start_background()
    yield r
    r.shutdown()


@pytest.fixture
def manager(tmp_path, relay):
    """一台接了本地中继的 PC。用假 service 避免真调 LLM。"""
    from agent.service import MollyPawService

    service = MollyPawService()

    saved = {}

    def saver(cfg):
        saved.update(cfg)

    mgr = RelayManager(
        service,
        config={"url": f"ws://127.0.0.1:{PORT}/server", "psk": PSK},
        config_saver=saver,
    )
    mgr.devices = _FreshDeviceStore(tmp_path)
    mgr.bridge.devices = mgr.devices

    # 伪装成已配对的设备，跳过配对流程直接测业务
    mgr._fake_phone = lambda: None

    mgr.start()
    _wait_until(lambda: mgr.status()["connected"], timeout=10)
    yield mgr
    mgr.stop()


class _FreshDeviceStore:
    """包一层 DeviceStore，强制用临时路径。"""

    def __init__(self, tmp_path):
        from agent.relay.devices import DeviceStore

        self._inner = DeviceStore(path=str(tmp_path / "relay" / "devices.json"))

    def __getattr__(self, item):
        return getattr(self._inner, item)


def _wait_until(pred, timeout=5, interval=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(interval)
    return False


def make_ready_phone(relay, mgr, role="app", dev_id="phone-1"):
    """建一条已完成握手的手机连接，并在 PC 端登记为已认证设备。

    配对模型已改成配对码（MP1.<b64(pair_seed)>.<room>）：
    这里用 store 直接生成码并兑换，模拟手机完成配对后的状态。
    真正的配对流程测试在 tests/test_phone_cli.py。
    """
    room = C.derive_room(PSK)
    phone = FakePhone(f"ws://127.0.0.1:{PORT}/server", room, PSK,
                      role=role, dev_id=dev_id).connect()
    assert _wait_until(lambda: phone.key is not None, timeout=8), "key not derived"

    session = mgr.devices.new_pairing(room, role)
    # 配对码只含 pair_seed 与 room；注册凭据从种子派生
    result, err = mgr.devices.claim_pairing(session.reg_token, dev_id, dev_id, os.urandom(32))
    assert err is None, f"配对失败: {err}"

    # 会话 id 用 dev_id —— 与 manager._on_payload 的口径保持一致
    mgr.bridge.register_session(dev_id, dev_id, role, dev_id)
    # 让 PC 端认得这条连接的临时密钥（正常流程由 hello 交换自动完成）
    mgr.link._peers[dev_id] = {
        "eph": phone.eph_pub, "hs": phone.hs, "role": role,
        "key": phone.key,
    }
    return phone


# --------------------------------------------------------------------------
# 握手与加密
# --------------------------------------------------------------------------


def test_handshake_derives_shared_key(relay, manager):
    phone = make_ready_phone(relay, manager)
    try:
        assert manager.link.session_key is not None
        # 两端算出来的密钥必须一致（否则后面什么都收不到）
        assert phone.key == manager.link.session_key
    finally:
        phone.close()


def test_psk_room_is_shared(relay, manager):
    assert manager.room() == C.derive_room(PSK)


# --------------------------------------------------------------------------
# 设备管理方法
# --------------------------------------------------------------------------


def test_device_list_requires_app_role(relay, manager):
    phone = make_ready_phone(relay, manager, role="observer", dev_id="obs-1")
    try:
        ok, err = phone.call("device.list")
        assert not ok
        assert err == "forbidden"
    finally:
        phone.close()


def test_config_get_never_leaks_api_key(relay, manager):
    """最关键的安全断言：手机拉配置拿到的是 ***，不是真 key。"""
    manager.service._ensure_agent().config["api_key"] = "sk-TOP-SECRET-KEY"
    phone = make_ready_phone(relay, manager)
    try:
        ok, cfg = phone.call("config.get")
        assert ok, cfg
        assert cfg["api_key"] == "***"
        assert "sk-TOP-SECRET-KEY" not in json.dumps(cfg)
        assert cfg["api_key_set"] is True
    finally:
        phone.close()


def test_observer_config_redacts_connection(relay, manager):
    manager.service._ensure_agent().config["api_key"] = "sk-x"
    manager.service._ensure_agent().config["base_url"] = "https://secret.internal/v1"
    phone = make_ready_phone(relay, manager, role="observer", dev_id="obs-2")
    try:
        ok, cfg = phone.call("config.get")
        assert ok, cfg
        assert cfg["base_url"] == "***"
        assert "secret.internal" not in json.dumps(cfg)
    finally:
        phone.close()


def test_config_save_strips_api_key(relay, manager):
    agent = manager.service._ensure_agent()
    agent.config["api_key"] = "sk-original"
    phone = make_ready_phone(relay, manager)
    try:
        ok, res = phone.call("config.save", {"api_key": "sk-evil", "max_tokens": 1234})
        assert ok, res
        assert "api_key" in res.get("ignored_fields", [])
        assert agent.config["api_key"] == "sk-original"
        assert agent.config["max_tokens"] == 1234
    finally:
        phone.close()


def test_observer_cannot_save_config(relay, manager):
    phone = make_ready_phone(relay, manager, role="observer", dev_id="obs-3")
    try:
        ok, err = phone.call("config.save", {"max_tokens": 999})
        assert not ok
        assert err == "forbidden"
    finally:
        phone.close()


# --------------------------------------------------------------------------
# 会话
# --------------------------------------------------------------------------


def test_conversation_lifecycle(relay, manager):
    phone = make_ready_phone(relay, manager)
    try:
        ok, created = phone.call("conv.new")
        assert ok, created
        conv_id = created["id"]

        ok, listed = phone.call("conv.list")
        assert ok
        assert any(c["id"] == conv_id for c in listed["conversations"])

        ok, loaded = phone.call("conv.load", {"id": conv_id})
        assert ok, loaded
        assert loaded["id"] == conv_id

        ok, _ = phone.call("conv.delete", {"id": conv_id})
        assert ok

        ok, listed2 = phone.call("conv.list")
        assert not any(c["id"] == conv_id for c in listed2["conversations"])
    finally:
        phone.close()


def test_observer_can_list_but_not_delete(relay, manager):
    phone = make_ready_phone(relay, manager, role="observer", dev_id="obs-4")
    try:
        ok, _ = phone.call("conv.list")
        assert ok, "observer should be able to list"
        ok, err = phone.call("conv.delete", {"id": "whatever"})
        assert not ok
        assert err == "forbidden"
    finally:
        phone.close()


def test_unknown_method_rejected(relay, manager):
    phone = make_ready_phone(relay, manager)
    try:
        ok, err = phone.call("system.shutdown_everything")
        assert not ok
        assert err == "forbidden"
    finally:
        phone.close()


# --------------------------------------------------------------------------
# 文件
# --------------------------------------------------------------------------


def test_fs_list_and_read(relay, manager, tmp_path):
    target = tmp_path / "hello.txt"
    target.write_text("远程文件内容", encoding="utf-8")

    phone = make_ready_phone(relay, manager)
    try:
        ok, listing = phone.call("fs.list", {"path": str(tmp_path)})
        assert ok, listing
        assert any(e["name"] == "hello.txt" for e in listing["entries"])

        ok, blob = phone.call("fs.read", {"path": str(target)})
        assert ok, blob
        import base64

        assert base64.b64decode(blob["data_b64"]).decode("utf-8") == "远程文件内容"
        assert blob["eof"] is True
    finally:
        phone.close()


def test_fs_no_blocklist_user_requested_full_access(relay, manager):
    """用户明确要求不限目录 —— 系统目录也必须能列（这是需求不是 bug）。"""
    phone = make_ready_phone(relay, manager)
    try:
        if os.name == "nt":
            target = os.environ.get("SystemRoot", "C:\\Windows")
        else:
            # macOS / Linux 上没有 C:\Windows；挑一个肯定存在的系统目录
            target = next(
                (d for d in ("/usr", "/etc", "/") if os.path.isdir(d)), os.sep
            )
        ok, listing = phone.call("fs.list", {"path": target})
        assert ok, listing
        assert len(listing["entries"]) > 0
    finally:
        phone.close()


def test_fs_audit_log_records_access(relay, manager, tmp_path):
    target = tmp_path / "audited.txt"
    target.write_text("x", encoding="utf-8")
    phone = make_ready_phone(relay, manager)
    try:
        phone.call("fs.list", {"path": str(tmp_path)})
        entries = manager.fs_audit(limit=50)
        assert any(e["action"] == "list" and str(tmp_path) in e["path"]
                   for e in entries), entries
    finally:
        phone.close()


def test_fs_chunked_read(relay, manager, tmp_path):
    """大文件必须分块读，单次不超过 256 KiB。"""
    big = tmp_path / "big.bin"
    payload = os.urandom(700 * 1024)
    big.write_bytes(payload)

    phone = make_ready_phone(relay, manager)
    try:
        collected = b""
        offset = 0
        while True:
            ok, chunk = phone.call("fs.read", {"path": str(big), "offset": offset})
            assert ok, chunk
            import base64

            piece = base64.b64decode(chunk["data_b64"])
            assert len(piece) <= C.FS_CHUNK
            collected += piece
            offset += len(piece)
            if chunk["eof"] or not piece:
                break
        assert collected == payload
    finally:
        phone.close()


def test_observer_cannot_touch_files(relay, manager):
    phone = make_ready_phone(relay, manager, role="observer", dev_id="obs-5")
    try:
        for method in ("fs.list", "fs.read", "fs.roots"):
            ok, err = phone.call(method, {"path": "."})
            assert not ok, f"{method} should be forbidden for observer"
            assert err == "forbidden"
    finally:
        phone.close()


# --------------------------------------------------------------------------
# 状态
# --------------------------------------------------------------------------


def test_status_get(relay, manager):
    phone = make_ready_phone(relay, manager)
    try:
        ok, status = phone.call("status.get")
        assert ok, status
        assert "pet_state" in status
        assert "busy" in status
    finally:
        phone.close()


def test_server_ping(relay, manager):
    phone = make_ready_phone(relay, manager)
    try:
        ok, res = phone.call("server.ping")
        assert ok, res
        assert res["server_ts"] > 0
    finally:
        phone.close()
