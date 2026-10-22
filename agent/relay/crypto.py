"""MollyPaw Relay — 加密层。

本模块是 PROTOCOL.md §4 的 Python 实现，同时是 JS / Kotlin 三个实现的**基准**。
任何改动必须先改 PROTOCOL.md，再改这里，再同步过去。

密码学原语：
  - X25519   密钥交换（RFC 7748）
  - HKDF-SHA256  密钥派生（RFC 5869）
  - AES-256-GCM  认证加密

绝对不要在这份文件里引入「顺手优化」：nonce 复用、悄悄换 salt 顺序、
把 AAD 简化 —— 都会让另外两个实现解不开，或者直接破掉安全性。
"""
import base64
import hashlib
import hmac
import json
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# ---------------------------------------------------------------------------
# 常量（与 PROTOCOL.md 严格一致）
# ---------------------------------------------------------------------------

PROTOCOL_VERSION = 1

INFO_ROOM = b"mollypaw/v1/room"
INFO_SESSION = b"mollypaw/v1/session"
INFO_PAIR = b"mollypaw/v1/pair"
AAD_PREFIX = "mollypaw/v1|"

NONCE_LEN = 12
TAG_LEN = 16
KEY_LEN = 32
HS_LEN = 16
PIN_LEN = 6
PIN_TTL = 300  # 秒

# 配对改为"一键导入"：PC 生成一个配对码，用户扫码/粘贴到手机。
#
# 设计演变（三次，每次原因都留在这）：
#
#   第一版：MP1.<b64(reg_token)>.<room>
#     问题：会话密钥由主 PSK 派生，而配对码里没有 PSK。
#     手机扫码后仍然算不出会话密钥 —— "扫码就行"是假的。
#
#   第二版：MP1.<b64(pair_key)>.<b64(reg_token)>.<room>
#     功能对了（手机用 pair_key 派会话密钥），但**长度 126 字节**，
#     超过本仓库自写二维码编码器的容量上限（版本 6 = 106 字节），
#     二维码压根生成不出来。
#
#   第三版（当前）：MP1.<b64(pair_seed)>.<room>
#     pair_seed 32 字节随机；两把派生钥匙都从它算出来：
#         pair_key  = HKDF(pair_seed, info="mollypaw/v1/pair-key")
#         reg_token = HKDF(pair_seed, info="mollypaw/v1/reg-token")
#     长度 = 4 + 44 + 1 + 32 = 81 字节，稳稳落在二维码容量内。
#
#   安全边界（别自己骗自己）：
#     - 配对码 15 分钟有效、一次性；
#     - 中继看得到 room，但看不到 pair_seed，所以解不开任何 data 帧；
#     - 拿到配对码的人可以配对成设备 —— 这是"一键"的必然代价，
#       但与泄露主 PSK 不同：影响只限这一次配对，主 PSK 仍可继续用。
PAIR_SEED_LEN = 32
REG_TOKEN_LEN = 32
REG_TTL = 900  # 15 分钟
PAIRING_CODE_PREFIX = "MP1."
INFO_PAIR_KEY = b"mollypaw/v1/pair-key"
INFO_REG_TOKEN = b"mollypaw/v1/reg-token"


def derive_pair_key(pair_seed: bytes) -> bytes:
    """从配对种子派生「配对会话密钥材料」（手机用它代替 PSK 派生会话密钥）。"""
    if len(pair_seed) != PAIR_SEED_LEN:
        raise ValueError(f"pair seed must be {PAIR_SEED_LEN} bytes")
    return hkdf(pair_seed, INFO_PAIR_KEY, length=32, salt=b"")


def derive_reg_token(pair_seed: bytes) -> bytes:
    """从配对种子派生「一次性注册凭据」。"""
    if len(pair_seed) != PAIR_SEED_LEN:
        raise ValueError(f"pair seed must be {PAIR_SEED_LEN} bytes")
    return hkdf(pair_seed, INFO_REG_TOKEN, length=REG_TOKEN_LEN, salt=b"")

PSK_MIN_LEN = 16
MAX_DEVICES = 16

REKEY_FRAMES = 1000
REKEY_SECONDS = 3600
REKEY_GRACE_SECONDS = 3.0

WS_MAX_FRAME = 1024 * 1024  # 1 MiB
RATE_WINDOW_SECONDS = 10
RATE_MAX_FRAMES = 120

HEARTBEAT_SECONDS = 20
HEARTBEAT_TIMEOUT = 40
AUTH_TS_SKEW = 120  # 秒

FS_CHUNK = 256 * 1024  # 256 KiB


# ---------------------------------------------------------------------------
# 编解码助手
# ---------------------------------------------------------------------------


def b64e(raw: bytes) -> str:
    """bytes -> 标准 base64 字符串（带 padding）。三方统一用标准表，不用 urlsafe。"""
    return base64.b64encode(raw).decode("ascii")


def b64d(text: str) -> bytes:
    """base64 字符串 -> bytes。容忍缺 padding（手机端可能省略）。"""
    if not isinstance(text, str):
        raise ValueError("expected base64 string")
    pad = (-len(text)) % 4
    return base64.b64decode(text + "=" * pad, validate=True)


def canonical_json(obj) -> bytes:
    """紧凑、键有序、非 ASCII 原样输出的 JSON。

    加密载荷用它序列化，保证同一对象在任何实现里字节一致 —— 虽然密文本身
    不需要跨实现一致，但**签名/校验类场景**（如 proof）需要可预测的字节。
    """
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# HKDF
# ---------------------------------------------------------------------------


def hkdf(ikm: bytes, info: bytes, length: int = KEY_LEN, salt: bytes = None) -> bytes:
    """HKDF-SHA256。

    salt=None 与 salt=b"" 在 RFC 5869 下等价（HMAC 对承载不足 block size 的
    密钥一律右侧补零），所以 room 派生两种写法都可以。
    """
    return HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=salt,
        info=info,
    ).derive(ikm)


# ---------------------------------------------------------------------------
# PSK 校验
# ---------------------------------------------------------------------------


def psk_problems(psk: str):
    """返回 PSK 不满足强度要求的**中文原因列表**；空列表表示通过。

    规则（PROTOCOL.md §4.4）：长度 >= 16，且含小写 / 大写 / 数字。
    不要求符号，不做字典词检查。
    """
    problems = []
    if not isinstance(psk, str):
        return ["密钥必须是文本"]
    if len(psk) < PSK_MIN_LEN:
        problems.append(f"密钥太短：至少 {PSK_MIN_LEN} 位，现在 {len(psk)} 位")
    if not any(c.islower() for c in psk):
        problems.append("密钥需要至少一个小写字母")
    if not any(c.isupper() for c in psk):
        problems.append("密钥需要至少一个大写字母")
    if not any(c.isdigit() for c in psk):
        problems.append("密钥需要至少一个数字")
    return problems


def psk_ok(psk: str) -> bool:
    return not psk_problems(psk)


def derive_room(psk: str) -> str:
    """PSK -> room 名（32 位小写 hex）。

    room 是公开信息（会出现在 WS URL 和 hello 帧里），但由 PSK 派生，
    所以别人猜不到你用的是哪间房。它**不是**认证手段，认证是 PSK 本身。
    """
    if not psk_ok(psk):
        raise ValueError("PSK too weak; " + "; ".join(psk_problems(psk)))
    digest = hkdf(psk.encode("utf-8"), INFO_ROOM, length=16, salt=b"")
    return digest.hex()


# ---------------------------------------------------------------------------
# 临时密钥对
# ---------------------------------------------------------------------------


def gen_ephemeral():
    """生成临时 X25519 密钥对，返回 (priv_bytes_32, pub_bytes_32)。"""
    priv = X25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv_raw, pub_raw


def pub_from_priv(priv_raw: bytes) -> bytes:
    """从 32 字节裸私钥推出 32 字节裸公钥。"""
    if len(priv_raw) != 32:
        raise ValueError("X25519 private key must be 32 bytes")
    priv = X25519PrivateKey.from_private_bytes(priv_raw)
    return priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def x25519_shared(priv_raw: bytes, peer_pub_raw: bytes) -> bytes:
    """X25519 标量乘，返回 32 字节共享秘密。

    cryptography 在结果为全零（低阶点）时会抛 ValueError，正好当作攻击检测，
    不要把异常吞掉。
    """
    if len(priv_raw) != 32:
        raise ValueError("X25519 private key must be 32 bytes")
    if len(peer_pub_raw) != 32:
        raise ValueError("X25519 public key must be 32 bytes")
    priv = X25519PrivateKey.from_private_bytes(priv_raw)
    peer = X25519PublicKey.from_public_bytes(peer_pub_raw)
    return priv.exchange(peer)


# ---------------------------------------------------------------------------
# 会话密钥
# ---------------------------------------------------------------------------


def derive_session_key(
    my_priv: bytes,
    peer_pub: bytes,
    psk: str,
    hs_pc: bytes,
    hs_app: bytes,
) -> bytes:
    """按 PROTOCOL.md §4.3 派生 32 字节会话密钥。

    salt 顺序固定 hs_pc ‖ hs_app，与谁发送无关 —— 两端必须都按 pc 在前。
    """
    if len(hs_pc) != HS_LEN or len(hs_app) != HS_LEN:
        raise ValueError(f"handshake nonce must be {HS_LEN} bytes")
    shared = x25519_shared(my_priv, peer_pub)
    ikm = shared + psk.encode("utf-8")
    salt = hs_pc + hs_app
    return hkdf(ikm, INFO_SESSION, length=KEY_LEN, salt=salt)


# ---------------------------------------------------------------------------
# 信封加解密
# ---------------------------------------------------------------------------


def aad_bytes(room: str, sender_role: str, seq: int) -> bytes:
    """构造 AAD：锁定房间 / 发送方角色 / 序号。"""
    return f"{AAD_PREFIX}{room}|{sender_role}|{seq}".encode("utf-8")


def encrypt_payload(key: bytes, room: str, sender_role: str, seq: int, payload) -> dict:
    """把明文载荷加密成 data 帧的三个字段 {n, c}。

    payload 可以是 dict（走 canonical_json）或已序列化的 bytes。
    """
    if len(key) != KEY_LEN:
        raise ValueError("session key must be 32 bytes")
    if isinstance(payload, (bytes, bytearray)):
        plaintext = bytes(payload)
    else:
        plaintext = canonical_json(payload)
    nonce = os.urandom(NONCE_LEN)
    aad = aad_bytes(room, sender_role, seq)
    blob = AESGCM(key).encrypt(nonce, plaintext, aad)
    return {"n": b64e(nonce), "c": b64e(blob)}


def decrypt_payload(key: bytes, room: str, sender_role: str, seq: int, frame: dict):
    """data 帧 -> 明文 dict。

    任何认证失败（改过密文、AAD 不对、角色冒充、序号错位）都会抛
    cryptography.exceptions.InvalidTag —— 调用方**必须**当成硬错误处理，
    不要退回明文，也不要重试。
    """
    try:
        nonce = b64d(frame["n"])
        blob = b64d(frame["c"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"malformed data frame: {exc}") from exc
    if len(nonce) != NONCE_LEN:
        raise ValueError(f"nonce must be {NONCE_LEN} bytes")
    if len(blob) < TAG_LEN:
        raise ValueError("ciphertext shorter than GCM tag")
    aad = aad_bytes(room, sender_role, seq)
    plaintext = AESGCM(key).decrypt(nonce, blob, aad)
    return json.loads(plaintext.decode("utf-8"))


def make_data_frame(
    key: bytes, room: str, role: str, seq: int, msg_id: str, payload
) -> dict:
    """组装完整 data 帧（含 v/t/r/f/seq/id）。"""
    sealed = encrypt_payload(key, room, role, seq, payload)
    return {
        "v": PROTOCOL_VERSION,
        "t": "data",
        "r": room,
        "f": role,
        "seq": seq,
        "id": msg_id,
        "n": sealed["n"],
        "c": sealed["c"],
    }


def open_data_frame(key: bytes, frame: dict, expect_role: str = None) -> dict:
    """解出 data 帧载荷；可选强校验发送方角色。"""
    if frame.get("t") != "data":
        raise ValueError("not a data frame")
    role = frame.get("f")
    if expect_role is not None and role != expect_role:
        raise ValueError(f"expected sender role {expect_role!r}, got {role!r}")
    return decrypt_payload(key, frame["r"], role, frame["seq"], frame)


# ---------------------------------------------------------------------------
# 配对 proof 与设备 token
# ---------------------------------------------------------------------------


def auth_proof(token: bytes, dev_id: str, ts: int) -> bytes:
    """PROTOCOL.md §5.2：HMAC-SHA256(token, dev_id|ts)。"""
    msg = f"{dev_id}|{int(ts)}".encode("utf-8")
    return hmac.new(token, msg, hashlib.sha256).digest()


def verify_auth_proof(token: bytes, dev_id: str, ts: int, proof: bytes) -> bool:
    """常数时间比较，防时序侧信道。"""
    expected = auth_proof(token, dev_id, ts)
    return hmac.compare_digest(expected, proof)


def token_hash(token: bytes) -> str:
    """设备 token 只存 sha256，明文永不落盘。"""
    return hashlib.sha256(token).hexdigest()


def gen_token() -> bytes:
    return os.urandom(32)


# ---------------------------------------------------------------------------
# 配对码（一键导入）
# ---------------------------------------------------------------------------
#
# 设计取舍（实测得出的结论，见 tools/audit_threat_model.py）：
#
#   早先用「6 位 PIN + PBKDF2 十万次」防爆破。实测证明那套是自欺：
#   客户端要把 pin 明文塞进 pair.req 送出，而中继看不到明文、服务端
#   在解密后能直接读到 pin —— 同一帧里既有 pin 又有用 pin 算的 proof，
#   等于自己验自己。PBKDF2 的十万次迭代一次也没用上。
#
#   改成一键导入：PC 生成一段随机配对码，用户手动复制到手机。
#   配对码本身就是 32 字节随机数，没有「6 位数字」那种爆破空间，
#   也就不需要人为拉高单次尝试成本。
#
#   配对码的构成：
#       MP1.<b64(reg_token)>.<b64(room)>
#   前半是注册凭据，后半是房间号（从 PSK 派生）。
#   连房间号一起带上，手机端就不需要先知道 PSK 也能找到房间 ——
#   这正是"PIN 只用它就能连接"的意思，只是这里用随机码而不是 6 位数字。


def make_pairing_code(pair_seed: bytes, room: str) -> str:
    """组装配对码：MP1.<b64(pair_seed)>.<room>

    两段就够（见文件顶部设计说明）：pair_seed 派生出配对密钥与注册凭据。
    长度 81 字节，能塞进版本 6 的二维码。
    """
    if len(pair_seed) != PAIR_SEED_LEN:
        raise ValueError(f"pair seed must be {PAIR_SEED_LEN} bytes")
    if not isinstance(room, str) or len(room) != 32:
        raise ValueError("room must be 32 hex chars")
    if any(c not in "0123456789abcdef" for c in room.lower()):
        raise ValueError("room must contain only hex characters")
    return f"{PAIRING_CODE_PREFIX}{b64e(pair_seed)}.{room.lower()}"


def parse_pairing_code(code: str):
    """解析配对码，返回 (pair_seed, room)；非法则抛 ValueError。

    对空白和换行宽容（用户从聊天软件粘贴常带这些），
    但两段内容本身必须是严格的 base64 / hex。
    """
    if not isinstance(code, str):
        raise ValueError("pairing code must be a string")
    text = code.strip().replace("\n", "").replace("\r", "").replace(" ", "")
    if not text.startswith(PAIRING_CODE_PREFIX):
        raise ValueError("配对码格式不对（应以 MP1. 开头）")

    body = text[len(PAIRING_CODE_PREFIX):]
    parts = body.split(".")
    if len(parts) != 2:
        raise ValueError(f"配对码应该有两段（pair_seed.room），实际 {len(parts)} 段")
    seed_part, room = parts

    try:
        pair_seed = b64d(seed_part)
    except Exception as exc:
        raise ValueError(f"配对码里的种子不是合法 base64：{exc}") from exc
    if len(pair_seed) != PAIR_SEED_LEN:
        raise ValueError(f"配对码里的种子长度不对（{len(pair_seed)} 字节）")

    room = room.lower()
    if len(room) != 32 or any(c not in "0123456789abcdef" for c in room):
        raise ValueError("配对码里的房间号不是 32 位 hex")

    return pair_seed, room


# ---------------------------------------------------------------------------
# 自检：常量自洽性
# ---------------------------------------------------------------------------

assert len(hkdf(b"x", b"y", length=32)) == 32
assert len(derive_room("Abcdefgh12345678")) == 32
_p, _u = gen_ephemeral()
assert len(_p) == 32 and len(_u) == 32
assert pub_from_priv(_p) == _u
