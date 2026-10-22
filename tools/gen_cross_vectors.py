"""生成跨实现测试向量，给 Android 端的 CryptoTest.kt 用。

Android 端的加密实现必须和 Python 端**逐字节一致**，
光"自己加解密自己解得开"毫无意义（两边一起写错也自洽）。
所以这里把 Python 端算出的值导出来，硬编码进 Kotlin 测试当锚点。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from agent.relay import crypto as C


def main():
    psk = "MollyPawTest1234"
    room = C.derive_room(psk)

    # 固定输入，用于验证会话密钥派生（避免随机导致无法对比）
    seed = bytes(range(32))
    hs_pc = bytes([1] * 16)
    hs_app = bytes([2] * 16)

    # 用确定性私钥（RFC 7748 的 alice/bob 私钥）
    alice_priv = bytes.fromhex(
        "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"
    )
    bob_priv = bytes.fromhex(
        "5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb"
    )
    alice_pub = C.pub_from_priv(alice_priv)
    bob_pub = C.pub_from_priv(bob_priv)

    pair_key = C.derive_pair_key(seed)
    reg_token = C.derive_reg_token(seed)
    session_key = C.derive_session_key(alice_priv, bob_pub, psk, hs_pc, hs_app)

    print("=" * 66)
    print("跨实现测试向量（复制到 Android 的 CryptoTest.kt）")
    print("=" * 66)
    print(f"PSK                = {psk!r}")
    print(f"room               = {room}")
    print(f"pair_seed          = {seed.hex()}")
    print(f"pair_key           = {pair_key.hex()}")
    print(f"reg_token          = {reg_token.hex()}")
    print(f"alice_priv         = {alice_priv.hex()}")
    print(f"alice_pub          = {alice_pub.hex()}")
    print(f"bob_priv           = {bob_priv.hex()}")
    print(f"bob_pub            = {bob_pub.hex()}")
    print(f"hs_pc              = {hs_pc.hex()}")
    print(f"hs_app             = {hs_app.hex()}")
    print(f"session_key        = {session_key.hex()}")

    # 也生成配对码，验证 parse 一致
    code = C.make_pairing_code(seed, room)
    print(f"pairing_code       = {code}")

    print()
    print("-" * 66)
    print("Kotlin 常量（直接替换 CryptoTest.kt 里的对应项）")
    print("-" * 66)
    print(f'private const val PYTHON_ROOM = "{room}"')
    print(f'private const val PYTHON_PAIR_KEY = "{pair_key.hex()}"')
    print(f'private const val PYTHON_REG_TOKEN = "{reg_token.hex()}"')
    print(f'private const val PYTHON_SESSION_KEY = "{session_key.hex()}"')
    print(f'private const val ALICE_PRIV = "{alice_priv.hex()}"')
    print(f'private const val BOB_PUB = "{bob_pub.hex()}"')

    # 自查：确保这些值能自洽
    assert len(room) == 32, "room 长度不对"
    assert C.derive_session_key(bob_priv, alice_pub, psk, hs_pc, hs_app) == session_key, \
        "两端会话密钥不一致"
    print("\n[自检] 两端会话密钥一致 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
