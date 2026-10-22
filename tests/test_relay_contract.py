"""MollyPaw Relay — 中继契约测试。

同一组断言跑 Python 本地中继，用于验证 PROTOCOL.md §9。
（JS 版 RelayRoom 的等价断言放在 D:\\MollyPaw-Relay\\worker\\test\\relay-room.test.js，
两边测试内容一一对应 —— 改一边必须改另一边。）
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "MollyPaw-Relay"))

from relay.dev_server import DevRelay, PROTOCOL_VERSION  # noqa: E402

import websockets.sync.client as ws_client  # noqa: E402

ROOM_A = "a" * 32
ROOM_B = "b" * 32


@pytest.fixture(scope="module")
def relay():
    r = DevRelay("127.0.0.1", 18999)
    r.start_background()
    yield r
    r.shutdown()


def url(room, base="127.0.0.1:18999"):
    return f"ws://{base}/server?room={room}"


def hello(role, room=ROOM_A, dev="dev-1", **extra):
    frame = {"v": PROTOCOL_VERSION, "t": "hello", "r": room, "f": role, "dev": dev}
    frame.update(extra)
    return json.dumps(frame)


def data_frame(text="payload", seq=1, role="app", room=ROOM_A, msg_id="m1"):
    return json.dumps({
        "v": PROTOCOL_VERSION, "t": "data", "r": room, "f": role,
        "seq": seq, "id": msg_id, "n": "AAAA", "c": "BBBB",
    })


def recv(ws, timeout=3.0):
    """收一帧。websockets 17 的同步客户端把 timeout 放在 recv() 上。"""
    return json.loads(ws.recv(timeout=timeout))


def drain(ws, timeout=0.4):
    """收干净当前缓冲的所有帧；超时即认为收完。"""
    out = []
    while True:
        try:
            out.append(json.loads(ws.recv(timeout=timeout)))
        except Exception:
            return out


# --------------------------------------------------------------------------
# 握手
# --------------------------------------------------------------------------


def test_first_frame_must_be_hello(relay):
    with ws_client.connect(url(ROOM_A)) as ws:
        ws.send(data_frame())
        frame = recv(ws)
        assert frame["t"] == "error"
        assert frame["code"] == "bad_frame"


def test_hello_requires_valid_room(relay):
    with ws_client.connect(url(ROOM_A)) as ws:
        ws.send(hello("app", room="zzz"))
        frame = recv(ws)
        assert frame["t"] == "error"
        assert frame["code"] == "bad_room"


def test_hello_room_must_match_url(relay):
    with ws_client.connect(url(ROOM_B)) as ws:
        ws.send(hello("app", room=ROOM_A))
        frame = recv(ws)
        assert frame["code"] == "bad_room"


def test_hello_rejects_bad_role(relay):
    with ws_client.connect(url(ROOM_A)) as ws:
        ws.send(hello("admin"))
        frame = recv(ws)
        assert frame["code"] == "bad_role"


def test_bad_room_query_param_rejected(relay):
    """非法 room 在握手阶段就被 400 拒掉，连 WS 都建不起来。"""
    with pytest.raises(Exception) as excinfo:
        with ws_client.connect("ws://127.0.0.1:18999/server?room=nope"):
            pass
    assert "400" in str(excinfo.value) or "InvalidStatus" in type(excinfo.value).__name__


def test_version_mismatch_rejected(relay):
    with ws_client.connect(url(ROOM_A)) as ws:
        ws.send(json.dumps({"v": 99, "t": "hello", "r": ROOM_A, "f": "app"}))
        frame = recv(ws)
        assert frame["code"] == "version"


def test_binary_frame_rejected(relay):
    with ws_client.connect(url(ROOM_A)) as ws:
        ws.send(b"\x00\x01\x02")
        frame = recv(ws)
        assert frame["code"] == "bad_frame"


# --------------------------------------------------------------------------
# 转发
# --------------------------------------------------------------------------


def test_pc_to_app_and_observer(relay):
    with ws_client.connect(url(ROOM_A)) as pc, \
         ws_client.connect(url(ROOM_A)) as app, \
         ws_client.connect(url(ROOM_A)) as obs:
        pc.send(hello("pc"))
        app.send(hello("app"))
        obs.send(hello("observer"))
        drain(app); drain(obs); drain(pc)

        pc.send(data_frame(role="pc", text="from-pc"))
        got_app = [f for f in drain(app) if f["t"] == "data"]
        got_obs = [f for f in drain(obs) if f["t"] == "data"]
        assert len(got_app) == 1 and got_app[0]["c"] == "BBBB"
        assert len(got_obs) == 1 and got_obs[0]["c"] == "BBBB"


def test_app_to_pc(relay):
    with ws_client.connect(url(ROOM_A)) as pc, \
         ws_client.connect(url(ROOM_A)) as app:
        pc.send(hello("pc"))
        app.send(hello("app"))
        drain(app); drain(pc)

        app.send(data_frame(role="app"))
        got = [f for f in drain(pc) if f["t"] == "data"]
        assert len(got) == 1
        assert got[0]["f"] == "app"


def test_observer_frames_are_relayed_to_pc(relay):
    """observer 的帧必须转发给 pc —— 越权是 PC 端判的，不是中继。

    中继看不到明文，没法区分 conv.list（允许）和 conv.delete（禁止）。
    如果在中间硬拦，观察端连会话列表都拿不到，功能直接废掉。
    所以：中继只保证"谁发的"，PC 保证"能做什么"。
    """
    with ws_client.connect(url(ROOM_A)) as pc, \
         ws_client.connect(url(ROOM_A)) as obs:
        pc.send(hello("pc"))
        obs.send(hello("observer"))
        drain(pc); drain(obs)

        obs.send(data_frame(role="observer", msg_id="obs-1"))
        got = [f for f in drain(pc) if f["t"] == "data"]
        assert len(got) == 1, "observer frame should reach pc"
        assert got[0]["f"] == "observer"
        assert got[0]["id"] == "obs-1"


def test_observer_offline_when_no_pc(relay):
    with ws_client.connect(url(ROOM_B)) as obs:
        obs.send(hello("observer", room=ROOM_B))
        drain(obs)
        obs.send(data_frame(role="observer", room=ROOM_B))
        frame = recv(obs)
        assert frame["code"] == "offline"


def test_offline_error_when_no_pc(relay):
    with ws_client.connect(url(ROOM_B)) as app:
        app.send(hello("app", room=ROOM_B))
        drain(app)
        app.send(data_frame(role="app", room=ROOM_B))
        frame = recv(app)
        assert frame["t"] == "error"
        assert frame["code"] == "offline"
        assert "电脑端已离线" in frame["msg"]


def test_role_spoof_rejected(relay):
    """app 声称自己是 pc —— 必须被拒。"""
    with ws_client.connect(url(ROOM_A)) as app:
        app.send(hello("app"))
        drain(app)
        app.send(data_frame(role="pc"))
        frame = recv(app)
        assert frame["code"] == "bad_role"


# --------------------------------------------------------------------------
# 房间隔离 / pc 唯一 / 心跳
# --------------------------------------------------------------------------


def test_rooms_are_isolated(relay):
    with ws_client.connect(url(ROOM_A)) as pc_a, \
         ws_client.connect(url(ROOM_B)) as app_b:
        pc_a.send(hello("pc", room=ROOM_A))
        app_b.send(hello("app", room=ROOM_B))
        drain(pc_a); drain(app_b)

        pc_a.send(data_frame(role="pc", room=ROOM_A))
        # app_b 在另一个房间，只能收到 offline 错误（因为它的房间没 pc），收不到数据
        got = drain(app_b)
        assert not [f for f in got if f["t"] == "data"]


def test_second_pc_replaces_first(relay):
    with ws_client.connect(url(ROOM_A)) as pc1, \
         ws_client.connect(url(ROOM_A)) as pc2:
        pc1.send(hello("pc", dev="first"))
        drain(pc1)
        pc2.send(hello("pc", dev="second"))
        drain(pc2)

        frames = drain(pc1)
        assert any(f["t"] == "bye" and f.get("reason") == "replaced" for f in frames)


def test_ping_pong(relay):
    with ws_client.connect(url(ROOM_A)) as app:
        app.send(hello("app"))
        drain(app)
        app.send(json.dumps({
            "v": PROTOCOL_VERSION, "t": "ping", "r": ROOM_A, "f": "app", "ts": 1,
        }))
        frame = recv(app)
        assert frame["t"] == "pong"
        assert frame["f"] == "app"


def test_presence_broadcast(relay):
    with ws_client.connect(url(ROOM_A)) as pc, \
         ws_client.connect(url(ROOM_A)) as app:
        pc.send(hello("pc"))
        drain(pc)
        app.send(hello("app"))
        # presence 是异步推送，多轮收集直到看到 pc==1&app==1
        frames = []
        for _ in range(4):
            frames.extend(drain(pc, timeout=0.5))
        presence = [f for f in frames if f["t"] == "presence"]
        assert presence, "expected a presence frame to the pc"
        assert presence[-1]["pc"] == 1
        assert presence[-1]["app"] == 1
