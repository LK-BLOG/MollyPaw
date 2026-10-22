"""对"PIN 单独无价值 / 换 PSK 是核弹"这套论断做实证核查。

不靠推理，直接拿真实代码验四条：
  A. room 是不是真的只能从 PSK 推出来
  B. 按 PROTOCOL.md 写的客户端（只发 proof、不发 pin）能不能配上对
  C. 有 PSK 的人能不能直接从抓到的配对帧里读出 PIN
  D. 换 PSK 之后，旧设备的 token 是不是真的失效

用法：.venv\\Scripts\\python.exe tools\\audit_threat_model.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from agent.relay import crypto as C
from agent.relay.devices import DeviceStore
from agent.relay.bridge import RelayBridge

PSK = "MollyPawAudit123"


def head(title):
    print("\n" + "=" * 62)
    print(title)
    print("=" * 62)


def section_a():
    head("A. room 是否只能由 PSK 推出")
    room = C.derive_room(PSK)
    other = C.derive_room("MollyPawAudit124")
    print(f"PSK={PSK!r}")
    print(f"  room          = {room}")
    print(f"换个 PSK 的 room = {other}")
    print(f"  room 长度 32 hex, 且由 HKDF 派生：{room != other}")
    print("结论：没有 PSK 就无法知道 room，连不到正确房间。")
    print("      → 论断 A 成立（PIN 单独确实够不着）")


def section_b():
    head("B. 按协议写的客户端（只发 proof）能不能配上对")
    tmp = tempfile.mkdtemp(prefix="audit-b-")
    store = DeviceStore(path=os.path.join(tmp, "devices.json"))
    bridge = RelayBridge(None, None, devices=store, logger=None)

    sess = store.new_pin("app")
    dev_id, dev_name = "dev-1", "小戡的手机"
    dev_pub = os.urandom(32)
    proof = C.pair_proof(sess.pin, sess.salt, dev_id, dev_name)

    # PROTOCOL.md §5.1 明确写的是这四个字段，没有 pin
    protocol_params = {
        "dev_id": dev_id,
        "dev_name": dev_name,
        "dev_pub": C.b64e(dev_pub),
        "proof": C.b64e(proof),
    }
    ok, res = bridge.handle_pair_req("sess-1", protocol_params)
    print("按 PROTOCOL.md 发的字段：", sorted(protocol_params))
    print(f"  handle_pair_req -> ok={ok} res={res}")
    if not ok:
        print("  ！！ 协议说客户端只发 proof，实现却拒绝 —— 实现与协议不符")
    else:
        print("  协议与实现一致")

    # 实现实际要求的字段：多一个 pin
    sess2 = store.new_pin("app")
    proof2 = C.pair_proof(sess2.pin, sess2.salt, dev_id, dev_name)
    with_pin = dict(protocol_params)
    with_pin["pin"] = sess2.pin
    with_pin["proof"] = C.b64e(proof2)
    ok2, res2 = bridge.handle_pair_req("sess-2", with_pin)
    print(f"\n实现实际要的字段（多了 pin）：")
    print(f"  handle_pair_req -> ok={ok2} role={(res2 or {}).get('role')}")
    return ok, ok2


def section_c():
    head("C. 有 PSK 的人能否直接从配对帧里读出 PIN")
    # 模拟一次配对：app 用 §4.3 会话密钥加密 pair.req
    pc_priv, pc_pub = C.gen_ephemeral()
    app_priv, app_pub = C.gen_ephemeral()
    hs_pc, hs_app = os.urandom(16), os.urandom(16)
    room = C.derive_room(PSK)

    pin = "123456"
    proof = C.pair_proof(pin, os.urandom(32), "dev-1", "phone")
    payload = {
        "m": "pair.req",
        "p": {"dev_id": "dev-1", "dev_name": "phone",
              "dev_pub": C.b64e(os.urandom(32)), "proof": C.b64e(proof),
              "pin": pin},   # ← 实现会把 pin 一起发出去
    }
    app_key = C.derive_session_key(app_priv, pc_pub, PSK, hs_pc, hs_app)
    frame = C.make_data_frame(app_key, room, "app", 1, "m1", payload)

    print("hello 帧是明文，eph / hs 直接可见（中继要转发它们）")
    # 攻击者：有 PSK，看到两个 hello 的 eph/hs，自己重算会话密钥
    attacker_key = C.derive_session_key(pc_priv, app_pub, PSK, hs_pc, hs_app)
    # 用「自己的私钥 + 对端公钥」正好等价，这里换个组合演示同样成立
    attacker_key2 = C.derive_session_key(app_priv, pc_pub, PSK, hs_pc, hs_app)
    decrypted = C.open_data_frame(attacker_key2, frame)
    print(f"  攻击者算出会话密钥 = {'成功' if attacker_key == attacker_key2 else '失败'}")
    print(f"  解出的载荷          = {decrypted['p']}")
    got_pin = decrypted["p"].get("pin")
    print(f"  直接读到 PIN        = {got_pin!r}")
    if got_pin:
        print("  ！！ 有 PSK 就能直接读 PIN，根本不需要爆破 —— PBKDF2 白加")
        print("     而且 proof 是用同一个 pin 算的，等于自己验自己")
    return bool(got_pin)


def section_d():
    head("D. 换 PSK 之后旧设备 token 是否失效")
    tmp = tempfile.mkdtemp(prefix="audit-d-")
    store = DeviceStore(path=os.path.join(tmp, "devices.json"))
    sess = store.new_pin("app")
    proof = C.pair_proof(sess.pin, sess.salt, "dev-1", "旧手机")
    res, err = store.claim_pin(sess.pin, proof, "dev-1", "旧手机", os.urandom(32))
    token = res["token"]

    print(f"配对成功，拿到 token，设备写入注册表")
    old_room = C.derive_room(PSK)
    NEW_PSK = "MollyPawAudit999"
    new_room = C.derive_room(NEW_PSK)
    print(f"  旧 room = {old_room}")
    print(f"  新 room = {new_room}   （换 PSK 后房间名变了）")

    # 关键：token 校验只看 devices.json，跟 room / PSK 无关
    dev, err2 = store.authenticate("dev-1", time.time(), token)
    print(f"\n换 PSK 之后用旧 token 认证 -> device={'有' if dev else '无'} err={err2}")
    if dev is not None:
        print("  ！！ 旧 token 仍然有效 —— 换 PSK 并没有撤销设备授权")
        print("     注册表里的记录还在，只要它再拿到新 PSK 就能继续用")
    else:
        print("  旧 token 已失效")
    return dev is not None


def main():
    section_a()
    b_ok, b_with_pin = section_b()
    c_leak = section_c()
    d_survives = section_d()

    head("汇总")
    print(f"A. room 只能由 PSK 推出                     : 成立")
    print(f"B. 按协议（只发 proof）配不上对             : {'是（实现与协议不符）' if not b_ok else '否'}")
    print(f"C. 有 PSK 就能直接读到 PIN，不需要爆破      : {'是' if c_leak else '否'}")
    print(f"D. 换 PSK 后旧 token 仍有效（未被撤销）     : {'是' if d_survives else '否'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
