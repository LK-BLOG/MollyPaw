"""MollyPaw Relay — 帧 / 方法 / 角色能力定义。

PROTOCOL.md §3 / §6 的可执行版本。三个实现共用同一份方法表，
手机端和 JS 中继的对应常量必须从这里抄（保持名字一致，方便交叉排查）。
"""

PROTOCOL_VERSION = 1

# -- 帧类型 ----------------------------------------------------------------

T_HELLO = "hello"
T_DATA = "data"
T_PING = "ping"
T_PONG = "pong"
T_BYE = "bye"
T_ERROR = "error"
T_PRESENCE = "presence"

FRAME_TYPES = {T_HELLO, T_DATA, T_PING, T_PONG, T_BYE, T_ERROR, T_PRESENCE}

# -- 角色 ------------------------------------------------------------------

ROLE_PC = "pc"
ROLE_APP = "app"
ROLE_OBSERVER = "observer"

ROLES = {ROLE_PC, ROLE_APP, ROLE_OBSERVER}

# -- 错误码 ----------------------------------------------------------------

E_VERSION = "version"
E_BAD_FRAME = "bad_frame"
E_BAD_ROOM = "bad_room"
E_BAD_ROLE = "bad_role"
E_ROLE_TAKEN = "role_taken"
E_OFFLINE = "offline"
E_FORBIDDEN = "forbidden"
E_NOT_FOUND = "not_found"
E_INTERNAL = "internal"
E_TOO_LARGE = "too_large"
E_RATE_LIMITED = "rate_limited"

# -- 方法表 ----------------------------------------------------------------
# method -> 允许调用的角色集合。PC 专属方法（PC 本地调用）不在表里。
# 事件（pc->app 单向推送）也列在这里，但客户端不会主动调用。

METHODS = {
    # 聊天
    "chat.send": {ROLE_APP},
    "chat.stop": {ROLE_APP},
    "chat.delta": set(),          # 事件，pc 推给 app
    "chat.tool_call": set(),      # 事件
    "chat.tool_result": set(),    # 事件
    # 审批
    "approval.list": {ROLE_APP},
    "approval.reply": {ROLE_APP},
    "approval.request": set(),    # 事件
    # 会话
    "conv.list": {ROLE_APP, ROLE_OBSERVER},
    "conv.new": {ROLE_APP},
    "conv.load": {ROLE_APP, ROLE_OBSERVER},
    "conv.delete": {ROLE_APP},
    # 配置
    "config.get": {ROLE_APP, ROLE_OBSERVER},
    "config.save": {ROLE_APP},
    # 文件
    "fs.list": {ROLE_APP},
    "fs.read": {ROLE_APP},
    "fs.stat": {ROLE_APP},
    "fs.write": {ROLE_APP},
    "fs.mkdir": {ROLE_APP},
    "fs.delete": {ROLE_APP},
    "fs.roots": {ROLE_APP},
    # 状态 / 设备
    "status.get": {ROLE_APP, ROLE_OBSERVER},
    "status.event": set(),        # 事件
    "device.list": {ROLE_APP},
    "device.revoke": {ROLE_APP},
    "server.ping": {ROLE_APP, ROLE_OBSERVER},
    "server.pong": set(),         # 事件/响应
    # 配对与握手（只在 WS 会话建立阶段用）
    "pair.req": {ROLE_APP},
    "pair.hs": set(),             # pc -> app 事件
    "pair.ok": set(),             # pc -> app 事件
    "pair.err": set(),            # pc -> app 事件
    "auth.req": {ROLE_APP, ROLE_OBSERVER},
    "auth.ok": set(),             # pc -> app 事件
    # rekey
    "rekey.offer": set(),         # pc -> app
    "rekey.accept": {ROLE_APP},
}


def can_call(role: str, method: str) -> bool:
    """角色是否有权调用某方法。

    未知方法一律拒绝（白名单语义），避免 PC 端将来加了方法但忘了登记权限。
    """
    allowed = METHODS.get(method)
    if allowed is None:
        return False
    return role in allowed


def is_event(method: str) -> bool:
    return method in METHODS and not METHODS[method]


# -- 帧构造助手 ------------------------------------------------------------


def hello_frame(room, role, dev=None, mode=None, pin_proof=None, auth_proof=None, ts=0):
    frame = {
        "v": PROTOCOL_VERSION,
        "t": T_HELLO,
        "r": room,
        "f": role,
        "ts": int(ts),
    }
    if dev is not None:
        frame["dev"] = dev
    if mode is not None:
        frame["mode"] = mode
    if pin_proof is not None:
        frame["pin_proof"] = pin_proof
    if auth_proof is not None:
        frame["auth_proof"] = auth_proof
    return frame


def error_frame(code, msg=""):
    return {"v": PROTOCOL_VERSION, "t": T_ERROR, "code": code, "msg": msg}


def ping_frame(room, role, ts=0):
    return {"v": PROTOCOL_VERSION, "t": T_PING, "r": room, "f": role, "ts": int(ts)}


def pong_frame(room, role, ts=0):
    return {"v": PROTOCOL_VERSION, "t": T_PONG, "r": room, "f": role, "ts": int(ts)}


def bye_frame(room, role, reason=""):
    return {"v": PROTOCOL_VERSION, "t": T_BYE, "r": room, "f": role, "reason": reason}


def payload(method, params=None, msg_id=None, is_response=False, ok=None, error=None, result=None):
    """构造加密前内层载荷。

    请求：  payload("chat.send", {"text": "hi"})
    成功响应：payload("chat.send", msg_id="...", is_response=True, ok=True, result={...})
    失败响应：payload("chat.send", msg_id="...", is_response=True, ok=False, error="busy")
    """
    out = {"m": method}
    if msg_id is not None:
        out["id"] = msg_id
    if not is_response:
        out["p"] = params or {}
        return out
    out["ok"] = bool(ok)
    if ok:
        out["r"] = result if result is not None else {}
    else:
        out["e"] = error or E_INTERNAL
    return out


def validate_frame(frame) -> str:
    """返回错误码；返回 None 表示帧结构合法。中继用，不做深度校验。"""
    if not isinstance(frame, dict):
        return E_BAD_FRAME
    if frame.get("v") != PROTOCOL_VERSION:
        return E_VERSION
    t = frame.get("t")
    if t not in FRAME_TYPES:
        return E_BAD_FRAME
    if t in (T_HELLO, T_DATA, T_PING, T_PONG, T_BYE):
        room = frame.get("r")
        if not isinstance(room, str) or len(room) != 32:
            return E_BAD_ROOM
        if frame.get("f") not in ROLES:
            return E_BAD_ROLE
    return None
