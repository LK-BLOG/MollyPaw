"""MollyPaw Relay — 设备注册表 + 配对码。

PROTOCOL.md §5 的实现。

配对模型（改自实测结论，见 tools/audit_threat_model.py）：
  - 早先：6 位 PIN + PBKDF2 派 proof。实测证明白加 —— 客户端要把 pin
    明文送进 pair.req，同一帧里既有 pin 又有用 pin 算的 proof，
    服务端解密后直接读到 pin。于是 PBKDF2 的十万次迭代一次没用上。
  - 现在：PC 生成 32 字节随机配对码，用户复制粘贴到手机。
    配对码 = MP1.<b64(reg_token)>.<b64(room)>，一次性、15 分钟有效。
    它本身就是高熵随机数，没有爆破空间，不需要人为拉高迭代次数。

存储：`<data_dir>/relay/devices.json`
  - token 只存 sha256，明文只在配对响应里出现一次
  - 配对码只在内存，进程重启即失效
"""
import json
import os
import threading
import time

from agent.relay import crypto as C


class PairingSession:
    """一次待认领的配对（一键导入）。"""

    __slots__ = ("pair_seed", "room", "role", "created_at", "claimed")

    def __init__(self, pair_seed, room, role):
        self.pair_seed = pair_seed
        self.room = room
        self.role = role
        self.created_at = time.time()
        self.claimed = False

    @property
    def reg_token(self):
        """一次性注册凭据（从种子派生，不单独存）。"""
        return C.derive_reg_token(self.pair_seed)

    @property
    def pair_key(self):
        """配对密钥（从种子派生）。"""
        return C.derive_pair_key(self.pair_seed)

    @property
    def expired(self):
        return (time.time() - self.created_at) > C.REG_TTL

    @property
    def usable(self):
        return not self.claimed and not self.expired

    def ttl_left(self):
        return max(0, int(C.REG_TTL - (time.time() - self.created_at)))

    def code(self):
        """给用户扫/复制的那串。

        含两段：pair_seed（手机从它派生配对密钥 + 注册凭据）、room（连哪间房）。
        手机扫码后**不需要知道主 PSK** 就能连上。
        """
        return C.make_pairing_code(self.pair_seed, self.room)


class DeviceStore:
    """设备注册表 + 待认领配对码。线程安全。"""

    def __init__(self, path=None):
        if path is None:
            from agent.paths import data_dir

            base = os.path.join(data_dir(), "relay")
            os.makedirs(base, exist_ok=True)
            path = os.path.join(base, "devices.json")
        self.path = path
        self._lock = threading.RLock()
        self._pairings = []          # [PairingSession]
        self._data = self._load()

    # -- 持久化 ------------------------------------------------------------

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("devices"), list):
                    return data
            except Exception:
                pass
        return {"devices": []}

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # -- 配对码 ------------------------------------------------------------

    def new_pairing(self, room, role="app"):
        """生成一个新的配对码会话。返回 PairingSession。

        旧的未使用配对码会被清掉 —— 用户可能反复点"添加设备"，
        留一堆有效码等于留一堆临时钥匙。
        """
        if role not in ("app", "observer"):
            raise ValueError("role must be 'app' or 'observer'")
        if not isinstance(room, str) or len(room) != 32:
            raise ValueError("room must be 32 hex chars")
        with self._lock:
            self._pairings = [p for p in self._pairings if p.usable]
            session = PairingSession(
                os.urandom(C.PAIR_SEED_LEN),
                room,
                role,
            )
            self._pairings.append(session)
            return session

    def current_pairing(self):
        """当前还有效的配对码（供 UI 显示），没有则 None。"""
        with self._lock:
            for session in self._pairings:
                if session.usable:
                    return session
        return None

    def cancel_pairings(self):
        with self._lock:
            self._pairings.clear()

    def claim_pairing(self, reg_token, dev_id, dev_name, dev_pub):
        """用配对码里的 reg_token 换取设备身份。

        返回 (device_dict_含token, None) 或 (None, error_code)。
        error_code ∈ {bad_code, expired, full}
        """
        with self._lock:
            if not reg_token:
                return None, "bad_code"

            session = None
            for candidate in self._pairings:
                # 常数时间比较，避免按比较耗时推断 token 前缀
                import hmac as _hmac

                if _hmac.compare_digest(candidate.reg_token, reg_token):
                    session = candidate
                    break
            if session is None:
                return None, "bad_code"
            if session.expired:
                return None, "expired"
            if session.claimed:
                return None, "bad_code"
            if len(self._data["devices"]) >= C.MAX_DEVICES:
                return None, "full"

            token = C.gen_token()
            now = time.time()
            device = {
                "dev_id": dev_id,
                "name": dev_name or "未命名设备",
                "role": session.role,
                "pub": C.b64e(dev_pub) if isinstance(dev_pub, (bytes, bytearray)) else str(dev_pub),
                "token_hash": C.token_hash(token),
                "added_at": now,
                "last_seen": now,
                "revoked": False,
            }
            # 同一 dev_id 重新配对就替换旧的，避免重复条目
            self._data["devices"] = [
                d for d in self._data["devices"] if d.get("dev_id") != dev_id
            ]
            self._data["devices"].append(device)
            session.claimed = True          # 一次性
            self._pairings = [p for p in self._pairings if not p.claimed]
            self._save()
            return {"device": device, "token": C.b64e(token)}, None

    # -- 设备 --------------------------------------------------------------

    def devices(self):
        with self._lock:
            return [dict(d) for d in self._data["devices"]]

    def get(self, dev_id):
        with self._lock:
            for d in self._data["devices"]:
                if d.get("dev_id") == dev_id:
                    return dict(d)
        return None

    def authenticate(self, dev_id, ts, token, now=None):
        """校验设备凭据。

        返回 (device, None) 或 (None, error_code)。
        error_code ∈ {unknown, revoked, stale_ts, bad_token}
        """
        now = time.time() if now is None else now
        with self._lock:
            device = None
            for d in self._data["devices"]:
                if d.get("dev_id") == dev_id:
                    device = d
                    break
            if device is None:
                return None, "unknown"
            if device.get("revoked"):
                return None, "revoked"
            try:
                if abs(now - float(ts)) > C.AUTH_TS_SKEW:
                    return None, "stale_ts"
            except (TypeError, ValueError):
                return None, "stale_ts"
            if not self.verify_token(device, token):
                return None, "bad_token"
            return device, None

    def verify_token(self, device, token):
        """用上送来的 token 明文比对存储的 hash。常数时间比较。"""
        if not device or not token:
            return False
        import hmac as _hmac

        expected = (device.get("token_hash") or "").strip()
        if not expected:
            return False
        try:
            raw = C.b64d(token) if isinstance(token, str) else bytes(token)
        except Exception:
            return False
        return _hmac.compare_digest(expected, C.token_hash(raw))

    def touch(self, dev_id):
        with self._lock:
            for d in self._data["devices"]:
                if d.get("dev_id") == dev_id:
                    d["last_seen"] = time.time()
                    self._save()
                    return

    def revoke(self, dev_id):
        with self._lock:
            for d in self._data["devices"]:
                if d.get("dev_id") == dev_id:
                    d["revoked"] = True
                    self._save()
                    return True
        return False

    def remove(self, dev_id):
        with self._lock:
            before = len(self._data["devices"])
            self._data["devices"] = [
                d for d in self._data["devices"] if d.get("dev_id") != dev_id
            ]
            if len(self._data["devices"]) != before:
                self._save()
                return True
        return False

    def revoke_all(self):
        """把全部设备标为已吊销。

        换 PSK 时由用户决定是否调用（默认不调）。
        为什么需要它：换 PSK 只改房间号，老设备是"连不上"而不是"被吊销" ——
        授权记录还在磁盘上，它一旦拿到新 PSK 就照用不误。
        真要清退，必须走这个。
        """
        with self._lock:
            count = 0
            for d in self._data["devices"]:
                if not d.get("revoked"):
                    d["revoked"] = True
                    count += 1
            if count:
                self._save()
            return count

    def clear_all(self):
        """删掉全部设备记录。"""
        with self._lock:
            count = len(self._data["devices"])
            self._data["devices"] = []
            if count:
                self._save()
            return count

    def public_list(self):
        """给 UI / 手机看的列表，绝不含 token_hash。"""
        return [
            {
                "dev_id": d.get("dev_id"),
                "name": d.get("name"),
                "role": d.get("role"),
                "added_at": d.get("added_at"),
                "last_seen": d.get("last_seen"),
                "revoked": bool(d.get("revoked")),
            }
            for d in self.devices()
        ]
