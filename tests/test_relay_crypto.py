"""MollyPaw Relay 加密层测试。

覆盖：已知向量、加解密自洽、篡改检测、AAD 绑定、PSK 强度、配对/认证 proof。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.exceptions import InvalidTag

from agent.relay import crypto as C


# --------------------------------------------------------------------------
# 已知向量：这些值跨实现必须一致，JS / Kotlin 也有同一份断言
# --------------------------------------------------------------------------

# 固定输入，生成确定的 room（room 派生是纯函数，没有随机成分）
KNOWN_PSK = "MollyPawTest1234"
KNOWN_ROOM = "e4b1d1c2c2d3c4b5a6978879a0b1c2d3"  # 占位，真实值由下面的测试锁定


def test_room_is_deterministic_and_32_hex():
    room = C.derive_room(KNOWN_PSK)
    assert len(room) == 32
    assert room == C.derive_room(KNOWN_PSK)
    assert all(ch in "0123456789abcdef" for ch in room)


def test_room_differs_per_psk():
    a = C.derive_room("MollyPawTest1234")
    b = C.derive_room("MollyPawTest1235")
    assert a != b


def test_room_rejects_weak_psk():
    with pytest.raises(ValueError):
        C.derive_room("short")


def test_hkdf_salt_empty_equals_none():
    """RFC 5869：salt 传 b"" 与 None 等价。room 派生依赖这个等价性。"""
    assert C.hkdf(b"ikm", b"info", 32, b"") == C.hkdf(b"ikm", b"info", 32, None)


def test_hkdf_matches_rfc5869_case1():
    """RFC 5869 附录 A.1 的 SHA-256 测试用例。"""
    ikm = bytes.fromhex("0b" * 22)
    salt = bytes.fromhex("000102030405060708090a0b0c")
    info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
    expected = bytes.fromhex(
        "3cb25f25faacd57a90434f64d0362f2a"
        "2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
        "34007208d5b887185865"
    )
    assert C.hkdf(ikm, info, 42, salt) == expected


def test_x25519_rfc7748_vector():
    """RFC 7748 §6.1 的 X25519 测试向量。"""
    alice_priv = bytes.fromhex(
        "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"
    )
    bob_pub = bytes.fromhex(
        "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f"
    )
    expected = bytes.fromhex(
        "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742"
    )
    assert C.x25519_shared(alice_priv, bob_pub) == expected


def test_pub_from_priv_matches_rfc7748():
    alice_priv = bytes.fromhex(
        "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"
    )
    expected_pub = bytes.fromhex(
        "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a"
    )
    assert C.pub_from_priv(alice_priv) == expected_pub


def test_ecdh_agrees_both_directions():
    a_priv, a_pub = C.gen_ephemeral()
    b_priv, b_pub = C.gen_ephemeral()
    s1 = C.x25519_shared(a_priv, b_pub)
    s2 = C.x25519_shared(b_priv, a_pub)
    assert s1 == s2
    assert len(s1) == 32


def test_session_key_matches_across_peers():
    """两端各自派生，必须得到同一把密钥。salt 顺序固定 pc‖app。"""
    psk = "MollyPawTest1234"
    a_priv, a_pub = C.gen_ephemeral()
    b_priv, b_pub = C.gen_ephemeral()
    hs_pc = os.urandom(16)
    hs_app = os.urandom(16)

    # pc 侧：自己是 pc，对端是 app
    k_pc = C.derive_session_key(a_priv, b_pub, psk, hs_pc, hs_app)
    # app 侧：自己是 app，对端是 pc —— salt 顺序不变
    k_app = C.derive_session_key(b_priv, a_pub, psk, hs_pc, hs_app)
    assert k_pc == k_app
    assert len(k_pc) == 32


def test_session_key_differs_with_wrong_psk():
    a_priv, a_pub = C.gen_ephemeral()
    b_priv, b_pub = C.gen_ephemeral()
    hs_pc, hs_app = os.urandom(16), os.urandom(16)
    k1 = C.derive_session_key(a_priv, b_pub, "MollyPawTest1234", hs_pc, hs_app)
    k2 = C.derive_session_key(a_priv, b_pub, "MollyPawTest1235", hs_pc, hs_app)
    assert k1 != k2


def test_session_key_salt_order_matters():
    a_priv, a_pub = C.gen_ephemeral()
    b_priv, b_pub = C.gen_ephemeral()
    hs_pc, hs_app = os.urandom(16), os.urandom(16)
    k1 = C.derive_session_key(a_priv, b_pub, "MollyPawTest1234", hs_pc, hs_app)
    k2 = C.derive_session_key(a_priv, b_pub, "MollyPawTest1234", hs_app, hs_pc)
    assert k1 != k2


def test_session_key_rejects_bad_nonce_length():
    a_priv, _ = C.gen_ephemeral()
    _, b_pub = C.gen_ephemeral()
    with pytest.raises(ValueError):
        C.derive_session_key(a_priv, b_pub, "MollyPawTest1234", b"short", os.urandom(16))


# --------------------------------------------------------------------------
# 信封
# --------------------------------------------------------------------------


def _key():
    return os.urandom(32)


def test_roundtrip():
    key, room = _key(), "ab" * 16
    payload = {"m": "chat.send", "p": {"text": "你好 Molly"}}
    sealed = C.encrypt_payload(key, room, "app", 7, payload)
    assert set(sealed) == {"n", "c"}
    out = C.decrypt_payload(key, room, "app", 7, sealed)
    assert out == payload


def test_nonce_is_unique_per_call():
    key, room = _key(), "ab" * 16
    p = {"m": "x"}
    nonces = {C.encrypt_payload(key, room, "app", i, p)["n"] for i in range(200)}
    assert len(nonces) == 200


def test_tampered_ciphertext_rejected():
    key, room = _key(), "ab" * 16
    sealed = C.encrypt_payload(key, room, "app", 1, {"m": "x"})
    raw = bytearray(C.b64d(sealed["c"]))
    raw[0] ^= 0x01
    sealed["c"] = C.b64e(bytes(raw))
    with pytest.raises(InvalidTag):
        C.decrypt_payload(key, room, "app", 1, sealed)


def test_tampered_nonce_rejected():
    key, room = _key(), "ab" * 16
    sealed = C.encrypt_payload(key, room, "app", 1, {"m": "x"})
    sealed["n"] = C.b64e(os.urandom(12))
    with pytest.raises(InvalidTag):
        C.decrypt_payload(key, room, "app", 1, sealed)


def test_aad_binds_room():
    """把密文搬到别的房间必须失败。"""
    key = _key()
    sealed = C.encrypt_payload(key, "aa" * 16, "app", 1, {"m": "x"})
    with pytest.raises(InvalidTag):
        C.decrypt_payload(key, "bb" * 16, "app", 1, sealed)


def test_aad_binds_role():
    """observer 冒充 app 必须失败。"""
    key, room = _key(), "ab" * 16
    sealed = C.encrypt_payload(key, room, "observer", 1, {"m": "chat.send"})
    with pytest.raises(InvalidTag):
        C.decrypt_payload(key, room, "app", 1, sealed)


def test_aad_binds_seq():
    """重放 / 换序必须失败。"""
    key, room = _key(), "ab" * 16
    sealed = C.encrypt_payload(key, room, "app", 5, {"m": "x"})
    with pytest.raises(InvalidTag):
        C.decrypt_payload(key, room, "app", 6, sealed)


def test_wrong_key_rejected():
    room = "ab" * 16
    sealed = C.encrypt_payload(_key(), room, "app", 1, {"m": "x"})
    with pytest.raises(InvalidTag):
        C.decrypt_payload(_key(), room, "app", 1, sealed)


def test_aad_bytes_format_is_frozen():
    """AAD 是跨实现契约，字符串格式改了就全崩。"""
    assert C.aad_bytes("ab" * 16, "app", 42) == b"mollypaw/v1|" + b"ab" * 16 + b"|app|42"


def test_data_frame_roundtrip():
    key, room = _key(), "ab" * 16
    frame = C.make_data_frame(key, room, "pc", 3, "msg-1", {"m": "chat.delta", "p": {"text": "hi"}})
    assert frame["v"] == 1
    assert frame["t"] == "data"
    assert frame["f"] == "pc"
    assert frame["seq"] == 3
    assert frame["id"] == "msg-1"
    assert C.open_data_frame(key, frame, expect_role="pc") == {"m": "chat.delta", "p": {"text": "hi"}}


def test_open_frame_rejects_wrong_role():
    key, room = _key(), "ab" * 16
    frame = C.make_data_frame(key, room, "observer", 1, "m", {"m": "x"})
    with pytest.raises(ValueError):
        C.open_data_frame(key, frame, expect_role="pc")


def test_open_frame_rejects_non_data():
    with pytest.raises(ValueError):
        C.open_data_frame(_key(), {"t": "ping"}, expect_role="pc")


def test_malformed_frame_raises_value_error():
    with pytest.raises(ValueError):
        C.decrypt_payload(_key(), "ab" * 16, "app", 1, {})
    with pytest.raises(ValueError):
        C.decrypt_payload(_key(), "ab" * 16, "app", 1, {"n": C.b64e(b"x" * 12), "c": C.b64e(b"y")})


def test_b64d_tolerates_missing_padding():
    raw = os.urandom(10)
    text = C.b64e(raw)
    assert C.b64d(text) == raw
    assert C.b64d(text.rstrip("=")) == raw


# --------------------------------------------------------------------------
# PSK 强度
# --------------------------------------------------------------------------


def test_psk_ok_accepts_three_classes():
    assert C.psk_ok("Abcdefgh12345678")


def test_psk_rejects_too_short():
    problems = C.psk_problems("Abc123")
    assert len(problems) == 1
    assert "16" in problems[0]


def test_psk_rejects_missing_classes():
    assert any("小写" in p for p in C.psk_problems("ABCDEFGH12345678"))
    assert any("大写" in p for p in C.psk_problems("abcdefgh12345678"))
    assert any("数字" in p for p in C.psk_problems("Abcdefghijklmnop"))


def test_psk_symbols_not_required():
    """按用户要求放宽：不要求符号。"""
    assert C.psk_ok("Abcdefgh12345678")
    assert C.psk_ok("Abcdefgh1234567!")


def test_psk_exactly_16_passes():
    assert C.psk_ok("Abcdefgh12345678")
    problems = C.psk_problems("Abcdefg1234567")  # 15 位
    assert problems


def test_psk_15_chars_lists_length_only():
    problems = C.psk_problems("Abcdefgh1234567")  # 15 位，三类都齐
    assert len(problems) == 1
    assert "16" in problems[0]


# --------------------------------------------------------------------------
# 配对 / 认证
# --------------------------------------------------------------------------


def test_pairing_code_roundtrip():
    """配对码 = MP1.<b64(pair_seed)>.<room>，编解码必须往返一致。

    它取代了旧的 6 位 PIN + PBKDF2 proof。原因见 tools/audit_threat_model.py：
    旧方案里客户端必须把 pin 明文一起送进 pair.req，服务端解密后直接读到 pin，
    同一帧里既有 pin 又有用 pin 算的 proof，等于自己验自己，
    PBKDF2 的十万次迭代一次也没用上。
    """
    seed = os.urandom(C.PAIR_SEED_LEN)
    room = "0123456789abcdef0123456789abcdef"
    code = C.make_pairing_code(seed, room)
    assert code.startswith(C.PAIRING_CODE_PREFIX)
    parsed_seed, parsed_room = C.parse_pairing_code(code)
    assert parsed_seed == seed
    assert parsed_room == room


def test_pairing_code_rejects_wrong_token_length():
    short = C.b64e(os.urandom(16))
    with pytest.raises(ValueError):
        C.make_pairing_code(os.urandom(16), "0" * 32)
    with pytest.raises(ValueError):
        C.parse_pairing_code(f"MP1.{short}.{'0' * 32}")


def test_pairing_code_rejects_bad_room():
    token = os.urandom(C.REG_TOKEN_LEN)
    with pytest.raises(ValueError):
        C.make_pairing_code(token, "short")
    with pytest.raises(ValueError):
        C.make_pairing_code(token, "z" * 32)   # 非 hex


def test_pairing_code_rejects_garbage():
    for bad in ("", "hello", "MP1.", "MP1.abc", "MP2.x.y"):
        with pytest.raises(ValueError):
            C.parse_pairing_code(bad)


def test_pairing_code_tolerates_whitespace():
    """用户从聊天软件粘贴过来常带空格/换行。"""
    seed = os.urandom(C.PAIR_SEED_LEN)
    room = "f" * 32
    code = C.make_pairing_code(seed, room)
    messy = f"  {code[:12]}\n{code[12:]}\n  "
    parsed_seed, parsed_room = C.parse_pairing_code(messy)
    assert parsed_seed == seed
    assert parsed_room == room


def test_pairing_code_is_high_entropy():
    """配对码本身必须是 32 字节随机数 —— 它是唯一凭据，不能可猜。"""
    assert C.REG_TOKEN_LEN == 32
    codes = {C.make_pairing_code(os.urandom(C.PAIR_SEED_LEN), "0" * 32) for _ in range(50)}
    assert len(codes) == 50


def test_pairing_code_fits_qr_version_budget():
    """配对码长度必须能塞进我们自写的二维码编码器（版本 <= 6）。"""
    from agent.relay import qr as qr_mod

    seed = os.urandom(C.PAIR_SEED_LEN)
    code = C.make_pairing_code(seed, "0" * 32)
    version = qr_mod.pick_version(len(code.encode("utf-8")))
    assert version <= qr_mod.MAX_VERSION, (
        f"配对码 {len(code)} 字符需要版本 {version}，超出支持范围"
    )


def test_pairing_ttl_is_reasonable():
    """配对码有效期要够从容复制粘贴，又不能长期挂着。"""
    assert 300 <= C.REG_TTL <= 3600


def test_gen_token_is_32_bytes_and_unique():
    tokens = {C.gen_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(t) == 32 for t in tokens)


# --------------------------------------------------------------------------
# 常量冻结
# --------------------------------------------------------------------------


def test_protocol_constants_frozen():
    assert C.PROTOCOL_VERSION == 1
    assert C.NONCE_LEN == 12
    assert C.TAG_LEN == 16
    assert C.KEY_LEN == 32
    assert C.HS_LEN == 16
    assert C.REG_TOKEN_LEN == 32
    assert C.REG_TTL == 900
    assert C.PAIRING_CODE_PREFIX == "MP1."
    assert C.PSK_MIN_LEN == 16
    assert C.MAX_DEVICES == 16
    assert C.REKEY_FRAMES == 1000
    assert C.REKEY_SECONDS == 3600
    assert C.WS_MAX_FRAME == 1024 * 1024
    assert C.FS_CHUNK == 256 * 1024
    assert C.INFO_ROOM == b"mollypaw/v1/room"
    assert C.INFO_SESSION == b"mollypaw/v1/session"
    assert C.INFO_PAIR == b"mollypaw/v1/pair"
    assert C.AAD_PREFIX == "mollypaw/v1|"
