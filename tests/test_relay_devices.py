"""MollyPaw Relay — 设备注册表与配对流程测试。

配对模型已经改过（见 tools/audit_threat_model.py 的实测结论）：
  - 旧：6 位 PIN + PBKDF2 proof。客户端必须把 pin 明文送进 pair.req，
    服务端解密后直接读到 pin，PBKDF2 十万次迭代一次没用上。
  - 新：32 字节随机种子的配对码（MP1.<b64(pair_seed)>.<room>），
    一次性、15 分钟有效，本身就是高熵随机数不需要拉高迭代成本。
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.relay import crypto as C
from agent.relay.devices import DeviceStore


@pytest.fixture
def store(tmp_path):
    return DeviceStore(path=str(tmp_path / "relay" / "devices.json"))


ROOM = "0123456789abcdef0123456789abcdef"
ROOM2 = "fedcba9876543210fedcba9876543210"


def pair(store, role="app", dev_id="dev-1", name="小戡的手机", room=ROOM):
    """走一遍配对，返回 (result, err, session)。"""
    session = store.new_pairing(room, role)
    # 配对码只含 pair_seed 与 room；注册凭据由种子派生（session.reg_token 属性）
    result, err = store.claim_pairing(session.reg_token, dev_id, name, os.urandom(32))
    return result, err, session


# --------------------------------------------------------------------------
# 配对码
# --------------------------------------------------------------------------


def test_new_pairing_makes_code(store):
    session = store.new_pairing(ROOM, "app")
    assert session.role == "app"
    assert session.code().startswith("MP1.")
    assert len(session.reg_token) == C.REG_TOKEN_LEN


def test_pairing_code_contains_room(store):
    session = store.new_pairing(ROOM, "app")
    pair_seed, room = C.parse_pairing_code(session.code())
    assert room == ROOM


def test_new_pairing_rejects_bad_role(store):
    with pytest.raises(ValueError):
        store.new_pairing(ROOM, "admin")


def test_new_pairing_rejects_bad_room(store):
    with pytest.raises(ValueError):
        store.new_pairing("short", "app")


def test_observer_role_is_remembered(store):
    session = store.new_pairing(ROOM, "observer")
    assert session.role == "observer"


def test_current_pairing(store):
    session = store.new_pairing(ROOM)
    current = store.current_pairing()
    assert current is not None
    assert current.reg_token == session.reg_token


def test_new_pairing_replaces_dead_ones(store):
    old = store.new_pairing(ROOM)
    old.claimed = True
    new = store.new_pairing(ROOM)
    assert store.current_pairing().reg_token == new.reg_token


def test_pairing_expires(store, monkeypatch):
    session = store.new_pairing(ROOM)
    session.created_at = time.time() - (C.REG_TTL + 1)
    assert session.expired
    assert not session.usable
    assert store.current_pairing() is None


def test_cancel_pairings(store):
    store.new_pairing(ROOM)
    store.cancel_pairings()
    assert store.current_pairing() is None


# --------------------------------------------------------------------------
# 配对
# --------------------------------------------------------------------------


def test_pair_success_returns_token_and_device(store):
    result, err, _session = pair(store)
    assert err is None
    assert result is not None
    token = C.b64d(result["token"])
    assert len(token) == C.REG_TOKEN_LEN
    assert result["device"]["role"] == "app"
    assert result["device"]["dev_id"] == "dev-1"


def test_pair_token_is_not_stored_in_plaintext(store):
    result, _err, _session = pair(store)
    token = C.b64d(result["token"])
    stored = store.get("dev-1")
    assert "token" not in stored
    assert stored["token_hash"] == C.token_hash(token)
    assert C.b64e(token) not in str(stored)


def test_pair_wrong_token_fails(store):
    store.new_pairing(ROOM)
    _result, err = store.claim_pairing(os.urandom(C.REG_TOKEN_LEN), "dev-1", "p", os.urandom(32))
    assert err == "bad_code"


def test_pair_empty_token_fails(store):
    store.new_pairing(ROOM)
    _result, err = store.claim_pairing(b"", "dev-1", "p", os.urandom(32))
    assert err == "bad_code"


def test_pair_code_is_single_use(store):
    session = store.new_pairing(ROOM)
    pair_seed, _room = C.parse_pairing_code(session.code())
    result, err = store.claim_pairing(session.reg_token, "dev-1", "p", os.urandom(32))
    assert err is None
    # 同一个凭据不能再用第二次
    _result2, err2 = store.claim_pairing(session.reg_token, "dev-2", "p2", os.urandom(32))
    assert err2 == "bad_code"


def test_pair_expired_code(store):
    session = store.new_pairing(ROOM)
    pair_seed, _room = C.parse_pairing_code(session.code())
    session.created_at = time.time() - (C.REG_TTL + 1)
    _result, err = store.claim_pairing(session.reg_token, "dev-1", "p", os.urandom(32))
    assert err == "expired"


def test_pair_replaces_same_device(store):
    for i in range(3):
        result, err, _ = pair(store, dev_id="dev-x", name=f"name-{i}")
        assert err is None
    assert len(store.devices()) == 1
    assert store.get("dev-x")["name"] == "name-2"


def test_pair_device_limit(store):
    for i in range(C.MAX_DEVICES):
        _result, err, _ = pair(store, dev_id=f"dev-{i}", name="n")
        assert err is None, f"device {i}"
    _result, err, _ = pair(store, dev_id="dev-over", name="n")
    assert err == "full"


def test_pairing_code_length_within_qr_limit(store):
    """配对码必须能塞进我们支持的二维码版本。"""
    from agent.relay import qr as qr_mod

    session = store.new_pairing(ROOM)
    version = qr_mod.pick_version(len(session.code().encode("utf-8")))
    assert version <= qr_mod.MAX_VERSION


# --------------------------------------------------------------------------
# 认证
# --------------------------------------------------------------------------


def test_auth_with_valid_token(store):
    result, _err, _ = pair(store)
    token = result["token"]
    dev, err = store.authenticate("dev-1", time.time(), token)
    assert err is None
    assert dev["dev_id"] == "dev-1"


def test_auth_unknown_device(store):
    _dev, err = store.authenticate("nope", time.time(), C.b64e(C.gen_token()))
    assert err == "unknown"


def test_auth_bad_token(store):
    pair(store)
    _dev, err = store.authenticate("dev-1", time.time(), C.b64e(C.gen_token()))
    assert err == "bad_token"


def test_auth_stale_timestamp(store):
    result, _err, _ = pair(store)
    old = time.time() - (C.AUTH_TS_SKEW + 60)
    _dev, err = store.authenticate("dev-1", old, result["token"])
    assert err == "stale_ts"


def test_auth_future_timestamp_rejected(store):
    result, _err, _ = pair(store)
    future = time.time() + (C.AUTH_TS_SKEW + 60)
    _dev, err = store.authenticate("dev-1", future, result["token"])
    assert err == "stale_ts"


def test_auth_revoked_device(store):
    result, _err, _ = pair(store)
    store.revoke("dev-1")
    _dev, err = store.authenticate("dev-1", time.time(), result["token"])
    assert err == "revoked"


def test_auth_malformed_token(store):
    pair(store)
    _dev, err = store.authenticate("dev-1", time.time(), "not-base64!!")
    assert err == "bad_token"


# --------------------------------------------------------------------------
# 管理
# --------------------------------------------------------------------------


def test_revoke_and_remove(store):
    pair(store)
    assert store.revoke("dev-1")
    assert store.get("dev-1")["revoked"] is True
    assert store.remove("dev-1")
    assert store.get("dev-1") is None
    assert not store.revoke("nope")
    assert not store.remove("nope")


def test_revoke_all(store):
    """换 PSK 时用户可以选择清退全部设备。

    为什么需要：换 PSK 只改房间号，老设备是「连不上」而不是「被吊销」——
    授权记录还在磁盘上，它一旦拿到新 PSK 就照用不误。
    """
    pair(store, dev_id="dev-1")
    pair(store, dev_id="dev-2")
    assert len(store.devices()) == 2
    count = store.revoke_all()
    assert count == 2
    assert all(d["revoked"] for d in store.public_list())
    # 再调一次没有可吊销的
    assert store.revoke_all() == 0


def test_clear_all(store):
    pair(store, dev_id="dev-1")
    pair(store, dev_id="dev-2")
    assert store.clear_all() == 2
    assert store.devices() == []


def test_public_list_hides_token_hash(store):
    pair(store)
    listed = store.public_list()
    assert len(listed) == 1
    assert "token_hash" not in listed[0]
    assert listed[0]["dev_id"] == "dev-1"


def test_touch_updates_last_seen(store):
    pair(store)
    before = store.get("dev-1")["last_seen"]
    time.sleep(0.01)
    store.touch("dev-1")
    assert store.get("dev-1")["last_seen"] > before


def test_persistence_roundtrip(store):
    result, _err, _ = pair(store)
    token = result["token"]
    assert os.path.exists(store.path)

    reopened = DeviceStore(path=store.path)
    assert len(reopened.devices()) == 1
    _dev, err = reopened.authenticate("dev-1", time.time(), token)
    assert err is None


def test_pairing_code_not_persisted(store):
    """配对码只在内存 —— 重启后旧码必须失效。"""
    store.new_pairing(ROOM)
    reopened = DeviceStore(path=store.path)
    assert reopened.current_pairing() is None


def test_corrupt_store_recovers(tmp_path):
    path = tmp_path / "devices.json"
    path.write_text("{ this is not json", encoding="utf-8")
    store = DeviceStore(path=str(path))
    assert store.devices() == []


# --------------------------------------------------------------------------
# 换 PSK 的真实语义（实测结论，别写错）
# --------------------------------------------------------------------------


def test_changing_psk_does_not_revoke_devices(store):
    """换 PSK ≠ 吊销设备。

    换 PSK 只是让房间号变了、老设备连不上；
    devices.json 里的授权记录一条没动，它拿到新 PSK 就照用不误。
    所以「清退」必须显式调 revoke_all / clear_all。
    """
    result, _err, _ = pair(store)
    token = result["token"]

    # 换 PSK（房间号随之改变）
    old_room = C.derive_room("MollyPawOld12345")
    new_room = C.derive_room("MollyPawNew12345")
    assert old_room != new_room

    # 但设备授权不受影响
    dev, err = store.authenticate("dev-1", time.time(), token)
    assert err is None, "换 PSK 不该影响已配对设备的 token 校验"
    assert dev is not None

    # 显式清退才真的失效
    store.revoke_all()
    _dev2, err2 = store.authenticate("dev-1", time.time(), token)
    assert err2 == "revoked"
