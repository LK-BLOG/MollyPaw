"""MollyPaw - AI Agent Desktop Client + Desktop Pet"""
import os
import sys

# 单实例锁：必须在 import webview 之前跑完（否则先起 GUI 再退出）。
# 实现放在 agent/single_instance.py，只依赖标准库。
from agent.single_instance import check_single_instance

if not check_single_instance():
    # 以前这里是**静默** sys.exit(0)：用户看到的现象就是
    # 「python main.py 什么都不输出」「双击图标没反应」，像程序坏了。
    # 其实只是已经开着一个。至少把原因说出来，能捞回窗口就捞回来。
    print("MollyPaw 已经在运行了（单实例）。", flush=True)
    print("要再开一个请先关掉托盘里的那个，或者用托盘菜单退出。", flush=True)
    try:
        from agent.single_instance import focus_existing_window

        focus_existing_window()
    except Exception:
        pass
    sys.exit(0)

import io
import json
import random
import subprocess
import threading
import time
import uuid

import webview
import http.server

try:
    import pystray
    from PIL import Image
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

from agent.core import AgentCore
from agent.providers.catalog import public_providers, get_provider
from agent.providers.openai_provider import OpenAIProvider
from agent.sleep import SleepCycle
from agent.service import MollyPawService

# 远程互联是可选功能：cryptography / websocket-client 缺了就不启用，
# 不能让整个应用打不开。用户装一次 requirements.txt 就有了。
try:
    from agent.relay.manager import RelayManager, DEFAULT_RELAY_URL
    from agent.version import APP_VERSION
    from agent.relay import crypto as relay_crypto
    HAS_RELAY = True
    RELAY_IMPORT_ERROR = ""
except Exception as _relay_exc:  # pragma: no cover - 取决于环境
    RelayManager = None
    relay_crypto = None
    DEFAULT_RELAY_URL = "wss://mollypaw-online.pages.dev/server"
    HAS_RELAY = False
    RELAY_IMPORT_ERROR = str(_relay_exc)


def _load_json_payload(payload, default=None):
    """把 HTTP body / JSON 字符串 / dict 统一成 dict。

    `_read_body()` 给的是 bytes，`json.loads` 也吃 bytes，
    但曾经有代码直接把 bytes 当 dict 用 `**` 展开，炸出
    "argument after ** must be a mapping, not bytes"。
    统一走这个函数，避免每个接口各写一遍。
    """
    if payload is None or payload == "":
        return {} if default is None else default
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return {} if default is None else default
        value = json.loads(text)
    else:
        value = payload
    if not isinstance(value, dict):
        raise ValueError("payload must be a JSON object")
    return value


class MollyPawAPI:
    """API exposed to the frontend via pywebview.

    业务逻辑都在 agent/service.py 的 MollyPawService 里 ——
    本地 UI（HTTP）和远程手机（中继）共用同一份实现，
    这样单飞锁 / 取消 / 审批只有一处，不会出现两边打架。
    """

    def __init__(self):
        self.agent = None
        self.pet_state = "idle"  # idle | work | cry | sleep
        self._last_activity = time.time()
        self.sleep_cycle = None
        # Approval system
        self._pending_approvals = {}  # request_id -> {"event": threading.Event, "approved": bool}
        self._events = []
        self._events_lock = threading.Lock()
        self._approval_mode = "prompt_dangerous"

        # 业务服务（单飞锁 / 取消 / 审批的唯一真源）
        self.service = MollyPawService(
            logger=lambda m: print(f"[MollyPaw] {m}")
        )
        self.service._approval_mode = self._approval_mode
        # 远程互联
        self.relay = None
        self._relay_lock = threading.RLock()
        # 本地聊天线程当前用的取消令牌（供停止按钮）
        self._local_token = None

    # -- 业务转发（保持旧签名，前端不用改）---------------------------------

    def _sync_pet(self):
        self.pet_state = self.service.pet_state

    # -- Tool call & approval callbacks ------------------------------------

    def _tool_call_callback(self, info):
        """Queue a tool-call event for the HTTP client."""
        self._queue_event("_onToolCall", info)

    def _tool_result_callback(self, info):
        """Queue a tool-result event for the HTTP client."""
        self._queue_event("_onToolResult", info)

    def _approval_request_callback(self, info):
        """Called by AgentCore when approval is needed. Blocks until user decides.

        走 service 的控制器：**不再有 120 秒超时**。
        理由：手机不在跟前时超时自动拒绝会让工具调用莫名失败，
        用户回头根本不知道发生过什么。
        """
        result = self.service._approval_request_callback(info)
        return result

    def approve_tool(self, request_json):
        """Called by frontend to approve/reject a tool call."""
        try:
            data = _load_json_payload(request_json)
            request_id = data.get("request_id", "")
            approved = data.get("approved", False)
            ok = self.service.approve_tool(request_id, approved)
            # 兼容旧的本地 pending 表
            pending = self._pending_approvals.get(request_id)
            if pending:
                pending["approved"] = approved
                pending["event"].set()
            return json.dumps({"ok": True, "resolved": ok}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    # -- 停止按钮 ----------------------------------------------------------

    def stop_chat(self, payload_json="{}"):
        """停止当前这一轮 agent。

        本地 UI 和手机共用同一个 controller，所以任何一边点停止都立刻生效。
        """
        try:
            data = _load_json_payload(payload_json)
            by = data.get("by", "local")
        except Exception:
            by = "local"
        stopped = self.service.stop_chat(by=by)
        self.pet_state = "idle"
        self._queue_event("_onChatStopped", {"by": by, "stopped": bool(stopped)})
        return json.dumps({"ok": True, "stopped": bool(stopped)}, ensure_ascii=False)

    # -- 远程互联 ----------------------------------------------------------

    def _ensure_relay(self):
        """懒加载远程互联。缺依赖时抛一个带指引的错误，而不是崩掉。"""
        if not HAS_RELAY:
            raise RuntimeError(
                "远程互联需要额外依赖，请运行：pip install -r requirements.txt"
                + (f"（{RELAY_IMPORT_ERROR}）" if RELAY_IMPORT_ERROR else "")
            )
        with self._relay_lock:
            if self.relay is None:
                relay_cfg = {}
                try:
                    agent = self.service._ensure_agent()
                    relay_cfg = dict(agent.config.get("relay") or {})
                except Exception:
                    pass
                self.relay = RelayManager(
                    self.service,
                    config=relay_cfg,
                    logger=lambda m: print(f"[MollyPaw] {m}"),
                    config_saver=self._save_relay_config,
                )
            return self.relay

    def _save_relay_config(self, cfg):
        """把中继配置写进 config.json 的 relay 字段。"""
        from agent.paths import config_path as _cfg

        path = _cfg()
        data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data["relay"] = cfg
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def relay_start(self):
        try:
            st = self._ensure_relay().start()
            return json.dumps({"ok": True, **st}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "running": False, "state": "error",
                               "error": str(e)}, ensure_ascii=False)

    def relay_stop(self):
        try:
            mgr = self._ensure_relay()
            st = mgr.stop()
            return json.dumps({"ok": True, **st}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def relay_status(self):
        """返回扁平的状态对象，前端 renderRelayStatus 直接吃这些字段。"""
        try:
            st = self._ensure_relay().status()
            return json.dumps({"ok": True, **st}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "running": False, "state": "error",
                               "error": str(e)}, ensure_ascii=False)

    def relay_settings(self, payload_json="{}"):
        """读取/更新中继设置（url / psk / auto_start）。

        注意：psk 太弱**不算接口错误** —— 设置确实存下来了，
        问题以 psk_problems 的形式回给前端显示。

        payload 可能是 str、bytes（HTTP body 原样）或 dict，
        所以这里统一解码，不要直接 ** 展开。
        """
        try:
            mgr = self._ensure_relay()
            data = _load_json_payload(payload_json)
            if data:
                mgr.set_config(**data)
            psk = mgr.config.get("psk") or ""
            return json.dumps({
                "ok": True,
                "url": mgr.config.get("url") or DEFAULT_RELAY_URL,
                # 回传明文 PSK：本地 UI 本来就能读 config.json（里面还有 api_key），
                # 不回传的结果是"保存后用户再也看不到自己的密钥"，
                # 而这串密钥是要手动抄到手机上的。
                # 注意：这个 HTTP 服务只监听 127.0.0.1，不对外。
                "psk": psk,
                "psk_set": bool(psk),
                "psk_problems": relay_crypto.psk_problems(psk) if psk else [],
                "auto_start": bool(mgr.config.get("auto_start")),
                "room": mgr.room(),
                **mgr.status(),
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def relay_pin(self, payload_json="{}"):
        """生成配对码（一键导入）。可带 role=app|observer。

        返回里带 qr_png（base64 PNG），前端可直接显示二维码。

        **必须先连上中继才允许生成配对码。**
        早先没有这道检查：中继没开也能点「添加设备」拿到一个看起来正常的
        二维码，用户拿去扫，手机一直等不到响应 —— 界面在骗人。
        """
        try:
            mgr = self._ensure_relay()
            st = mgr.status()
            if not st.get("running"):
                return json.dumps({
                    "ok": False,
                    "need_start": True,
                    "error": "远程互联还没开启。先点「开启远程互联」，"
                             "等状态变成「已连接」再添加设备。",
                }, ensure_ascii=False)
            if not st.get("connected"):
                return json.dumps({
                    "ok": False,
                    "need_start": True,
                    "error": "中继还没连上（当前状态：%s）。"
                             "网络不稳时它会自己重试，等显示「已连接」再添加设备。"
                             % (st.get("state") or "未知"),
                }, ensure_ascii=False)
            try:
                data = _load_json_payload(payload_json)
            except Exception:
                data = {}
            role = data.get("role", "app")
            session = mgr.new_pairing(role)
            if not session.get("ok"):
                return json.dumps(session, ensure_ascii=False)
            self._attach_qr(session, mgr)
            return json.dumps(session, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    @staticmethod
    def _attach_qr(session, mgr):
        """把配对码渲染成二维码塞进响应（失败也不影响配对本身）。"""
        try:
            import base64 as _b64

            png = mgr.pairing_qr_png(session["code"], scale=7)
            session["qr_png"] = _b64.b64encode(png).decode("ascii")
        except Exception as exc:
            session["qr_error"] = str(exc)

    def relay_pin_current(self):
        """当前还有效的配对码（供 UI 恢复显示）。"""
        try:
            mgr = self._ensure_relay()
            session = mgr.current_pairing()
            if not session:
                return json.dumps({"ok": True, "pin": None}, ensure_ascii=False)
            self._attach_qr(session, mgr)
            return json.dumps({"ok": True, "pin": session}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    # -- 自动更新 ----------------------------------------------------------

    def version(self):
        try:
            from agent.version import APP_VERSION
        except Exception:
            APP_VERSION = "0.0.0"
        return json.dumps({"ok": True, "version": APP_VERSION}, ensure_ascii=False)

    def update_check(self):
        """查有没有新版本（含更新说明，给弹窗用）。"""
        try:
            from agent import updater
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": "更新模块不可用：%s" % exc},
                              ensure_ascii=False)
        return json.dumps(updater.check(), ensure_ascii=False)

    def update_download(self, payload_json="{}"):
        """后台下载新版本，进度通过事件队列推给前端。"""
        try:
            from agent import updater
            data = _load_json_payload(payload_json)
            url = (data.get("url") or "").strip()
            name = (data.get("name") or "MollyPaw.exe").strip()
            if not url:
                info = updater.check()
                asset = (info or {}).get("asset") or {}
                url = asset.get("url") or ""
                name = asset.get("name") or name
            if not url:
                return json.dumps({"ok": False, "error": "没有可下载的安装包地址"},
                                  ensure_ascii=False)

            def on_progress(pct, done, total):
                self._queue_event("_onUpdateProgress", {
                    "percent": pct, "done": done, "total": total,
                })

            def on_done(path, exc):
                if exc is not None:
                    self._queue_event("_onUpdateFailed", {"error": str(exc)})
                else:
                    self._queue_event("_onUpdateReady", {
                        "path": path,
                        "frozen": updater.is_frozen(),
                    })

            updater.start_download_async(url, name, on_progress, on_done)
            return json.dumps({"ok": True, "started": True}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    def update_apply(self):
        """替换自身并重启（仅打包版可用）。"""
        try:
            from agent import updater
            ok, err = updater.apply_update()
            if not ok:
                return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
            self._queue_event("_onUpdateApplying", {"ok": True})
            # 给前端 300ms 把提示画出来再退出
            threading.Timer(0.4, lambda: os._exit(0)).start()
            return json.dumps({"ok": True, "restarting": True}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    def relay_pin_cancel(self):
        try:
            self._ensure_relay().cancel_pairings()
            return json.dumps({"ok": True}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def relay_devices_purge(self, payload_json="{}"):
        """清退设备。

        mode=revoke（默认）: 全部标记为已吊销 —— 设备即便拿到新 PSK 也进不来
        mode=clear         : 直接删掉全部记录

        换 PSK 时由用户决定要不要调这个。为什么需要：
        换 PSK 只让老设备「连不上」（房间号变了），
        devices.json 里的授权记录一条没动，它拿到新密钥照样能连进来。
        这是实测结论，见 tools/audit_psk_room.py。
        """
        try:
            mgr = self._ensure_relay()
            try:
                data = _load_json_payload(payload_json)
            except Exception:
                data = {}
            mode = data.get("mode", "revoke")
            if mode == "clear":
                count = mgr.clear_devices()
            else:
                count = mgr.revoke_all_devices()
            return json.dumps({"ok": True, "mode": mode, "count": count},
                              ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def relay_devices(self):
        try:
            mgr = self._ensure_relay()
            return json.dumps({"ok": True, "devices": mgr.list_devices()},
                              ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def relay_device_revoke(self, payload_json):
        try:
            data = _load_json_payload(payload_json)
            mgr = self._ensure_relay()
            dev_id = data.get("dev_id", "")
            if data.get("remove"):
                ok = mgr.remove_device(dev_id)
            else:
                ok = mgr.revoke_device(dev_id)
            return json.dumps({"ok": bool(ok)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def relay_audit(self, limit_json="{}"):
        try:
            limit = 200
            try:
                data = _load_json_payload(limit_json)
                limit = int(data.get("limit", 200))
            except Exception:
                pass
            return json.dumps({"ok": True, "entries": self._ensure_relay().fs_audit(limit)},
                              ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def set_approval_mode(self, mode_json):
        """Set the approval mode: 'full_access', 'prompt_all', or 'prompt_dangerous'."""
        try:
            data = _load_json_payload(mode_json)
            mode = data.get("mode", "prompt_dangerous")
            if mode not in ("full_access", "prompt_all", "prompt_dangerous"):
                return json.dumps({"ok": False, "error": "Invalid mode"}, ensure_ascii=False)
            self._approval_mode = mode
            if self.agent:
                self.agent.approval_mode = mode
                self.agent.config["approval_mode"] = mode
                # Persist to config
                import os
                from agent.paths import config_path as _apicfg_path
                config_path = _apicfg_path()
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                cfg["approval_mode"] = mode
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
            return json.dumps({"ok": True, "mode": mode}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def get_approval_mode(self):
        """Get the current approval mode."""
        return json.dumps({"mode": self._approval_mode}, ensure_ascii=False)

    def set_thinking_level(self, level_json):
        try:
            data = _load_json_payload(level_json)
            level = data.get("level", "none")
            if level not in ("none", "low", "medium", "high", "max"):
                return json.dumps({"ok": False, "error": "Invalid thinking level"}, ensure_ascii=False)
            agent = self._ensure_agent()
            agent.save_config({"thinking_level": level})
            if self.sleep_cycle:
                self.sleep_cycle.provider = agent.provider
            return json.dumps({"ok": True, "level": level}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    def _mark_activity(self):
        if self.sleep_cycle:
            self.sleep_cycle.mark_activity()

    def get_sleep_settings(self):
        try:
            agent = self._ensure_agent()
            return json.dumps({
                "ok": True,
                "sleep": agent.config.get("sleep", {}),
                "status": self.sleep_cycle.get_status() if self.sleep_cycle else {},
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def save_sleep_settings(self, settings_json):
        try:
            data = _load_json_payload(settings_json)
            if not isinstance(data, dict):
                raise ValueError("Invalid sleep settings")
            mode = data.get("mode", "off")
            if mode not in ("off", "display_only", "full"):
                raise ValueError("Invalid sleep mode")
            tasks = data.get("tasks", ["memory", "review", "dream"])
            if not isinstance(tasks, list):
                raise ValueError("Invalid sleep tasks")
            tasks = [task for task in ("memory", "review", "dream") if task in tasks]
            try:
                max_llm_calls = max(0, int(data.get("max_llm_calls", 100)))
            except (TypeError, ValueError):
                raise ValueError("Invalid max llm calls")
            sleep = {"mode": mode, "tasks": tasks, "idle_minutes": 0.5, "max_llm_calls": max_llm_calls}
            agent = self._ensure_agent()
            agent.save_config({"sleep": sleep})
            if self.sleep_cycle:
                self.sleep_cycle.provider = agent.provider
                self.sleep_cycle.reload_config()
            self._mark_activity()
            return json.dumps({"ok": True, "sleep": sleep, "status": self.sleep_cycle.get_status() if self.sleep_cycle else {}}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def _ensure_agent(self):
        """Ensure AgentCore exists with callbacks attached.

        实际由 service 持有；这里返回同一个实例，
        保证 HTTP 层和远程中继操作的是同一个 agent（同一个 history / 同一个单飞锁）。
        """
        agent = self.service._ensure_agent()
        self.agent = agent
        self.sleep_cycle = self.service.sleep_cycle
        return agent

    # -- Pet server --------------------------------------------------------

    def start_pet_server(self, host="127.0.0.1", port=18765):
        """Start a local HTTP server to serve pet assets + state API.

        port 可传 0 让系统分配（测试用），避免和已运行的实例抢端口。
        """
        pet_dir = os.path.join(_base_dir(), "assets", "pet")
        api_ref = self

        class PetHandler(http.server.BaseHTTPRequestHandler):
            # 客户端在响应写完之前就断开时会抛这几个异常。
            # 它们是**正常现象**（浏览器关页、前端轮询被打断），
            # 不该在控制台刷 traceback —— 用户看到满屏红字会以为程序坏了。
            CLIENT_GONE = (
                ConnectionAbortedError,
                BrokenPipeError,
                ConnectionResetError,
            )

            def _send_json(self, data):
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Expires", "0")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except self.CLIENT_GONE:
                    # 对方先挂了，这条响应没人在等 —— 静默丢掉
                    pass

            def _read_body(self):
                length = int(self.headers.get("Content-Length", 0))
                return self.rfile.read(length) if length else b""

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def _serve_file(self, fpath, ctype):
                with open(fpath, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                try:
                    if self.path == "/state":
                        self._send_json({"state": api_ref.pet_state})
                    elif self.path == "/api/providers":
                        self._send_json({"ok": True, "providers": public_providers()})
                    elif self.path == "/api/events":
                        self._send_json(api_ref.get_events())
                    elif self.path == "/api/balance":
                        def _balance():
                            try:
                                agent = api_ref._ensure_agent()
                                preset = get_provider(agent.config.get("provider_id")) or {}
                                result = agent.provider.get_balance(preset.get("balance_path", agent.config.get("balance_path", "")), preset.get("balance_parser", ""), preset.get("balance_base_url", ""))
                            except Exception as e:
                                result = {"ok": False, "supported": False, "error": str(e)}
                            api_ref._push_result("_onBalanceResult", result)
                        threading.Thread(target=_balance, daemon=True).start()
                        self._send_json({"ok": True, "pending": True})
                    elif self.path == "/api/config":
                        def _work():
                            try:
                                agent = api_ref._ensure_agent()
                                config = agent.get_config()
                                api_ref._push_result("_onConfigResult", json.dumps({"ok": True, "config": config}, ensure_ascii=False))
                            except Exception as e:
                                api_ref._push_result("_onConfigResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                        threading.Thread(target=_work, daemon=True).start()
                        self._send_json({"ok": True, "pending": True})
                    elif self.path == "/api/approval_mode":
                        self._send_json({"mode": api_ref._approval_mode})
                    elif self.path == "/api/sleep":
                        self._send_json(json.loads(api_ref.get_sleep_settings()))
                    elif self.path == "/api/skills":
                        def _work():
                            try:
                                agent = api_ref._ensure_agent()
                                result = agent.tool_registry.execute("list_skills", {})
                                api_ref._push_result("_onSkillsResult", json.dumps({"ok": True, "skills": result}, ensure_ascii=False))
                            except Exception as e:
                                api_ref._push_result("_onSkillsResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                        threading.Thread(target=_work, daemon=True).start()
                        self._send_json({"ok": True, "pending": True})
                    elif self.path == "/api/conversations":
                        def _work():
                            try:
                                agent = api_ref._ensure_agent()
                                convs = agent.list_conversations()
                                api_ref._push_result("_onConversationsResult", json.dumps({"ok": True, "conversations": convs}, ensure_ascii=False))
                            except Exception as e:
                                api_ref._push_result("_onConversationsResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                        threading.Thread(target=_work, daemon=True).start()
                        self._send_json({"ok": True, "pending": True})
                    # -- 远程互联（GET：只读查询，直接同步返回，不走事件队列）
                    # 这些必须在 do_GET 里 —— 放在 do_POST 会让前端拿 404。
                    elif self.path == "/api/relay/status":
                        self._send_json(json.loads(api_ref.relay_status()))
                    elif self.path == "/api/relay/settings":
                        self._send_json(json.loads(api_ref.relay_settings("{}")))
                    elif self.path == "/api/relay/devices":
                        self._send_json(json.loads(api_ref.relay_devices()))
                    elif self.path == "/api/relay/pin":
                        self._send_json(json.loads(api_ref.relay_pin_current()))
                    elif self.path == "/api/relay/audit":
                        self._send_json(json.loads(api_ref.relay_audit("{}")))
                    elif self.path == "/api/version":
                        self._send_json(json.loads(api_ref.version()))
                    elif self.path == "/api/update/check":
                        self._send_json(json.loads(api_ref.update_check()))
                    elif self.path == "/api/relay/available":
                        self._send_json({"ok": True, "available": HAS_RELAY,
                                         "error": RELAY_IMPORT_ERROR})
                    elif self.path == "/api/busy":
                        # controller 只有在 service 初始化完成后才有；
                        # 没起来时如实回 false，不要 AttributeError 把连接打断。
                        ctrl = getattr(api_ref.service, "controller", None)
                        self._send_json({
                            "ok": True,
                            "busy": bool(ctrl.busy) if ctrl else False,
                            "owner": ctrl.owner if ctrl else None,
                        })
                    elif self.path == "/" or self.path == "/index.html":
                        frontend_dir = os.path.join(_base_dir(), "frontend")
                        self._serve_file(os.path.join(frontend_dir, "index.html"), "text/html; charset=utf-8")
                    elif self.path in ("/style.css", "/app.js", "/marked.min.js"):
                        frontend_dir = os.path.join(_base_dir(), "frontend")
                        fpath = os.path.join(frontend_dir, self.path.lstrip("/"))
                        ctype = "text/css" if self.path.endswith(".css") else "application/javascript"
                        self._serve_file(fpath, ctype)
                    else:
                        fname = self.path.lstrip("/")
                        fpath = os.path.join(pet_dir, fname)
                        if os.path.isfile(fpath):
                            with open(fpath, "rb") as f:
                                data = f.read()
                            ext = os.path.splitext(fname)[1].lower()
                            ctype = {
                                ".png": "image/png",
                                ".jpg": "image/jpeg",
                                ".gif": "image/gif",
                            }.get(ext, "application/octet-stream")
                            self.send_response(200)
                            self.send_header("Content-Type", ctype)
                            self.send_header("Content-Length", str(len(data)))
                            self.end_headers()
                            self.wfile.write(data)
                        else:
                            self.send_error(404)
                except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                    pass

            def do_POST(self):
                try:
                    body = self._read_body()
                    api_ref._mark_activity()
                    if self.path == "/api/chat":
                        request = json.loads(body)
                        msg = request.get("message", "")
                        thinking_level = request.get("thinking_level", "none")
                        api_ref.pet_state = "work"
                        api_ref._mark_activity()

                        service = api_ref.service

                        # 单飞：本地 UI 和手机共用一把锁
                        token = service.controller.acquire("local")
                        if token is None:
                            owner = service.controller.owner or "未知"
                            api_ref.pet_state = "work"
                            self._send_json({
                                "ok": False,
                                "error": f"正有一轮在跑（{owner}），先停止再发。",
                                "busy": True,
                            })
                            return
                        api_ref._local_token = token

                        def on_delta(piece, kind):
                            """真流式：逐片推给前端。"""
                            api_ref._queue_event("_onChatDelta", {
                                "text": piece if kind == "content" else "",
                                "reasoning": piece if kind == "reasoning" else "",
                                "kind": kind,
                            })

                        def _chat():
                            try:
                                agent = api_ref._ensure_agent()
                                agent.config["thinking_level"] = thinking_level
                                agent.provider.thinking_level = thinking_level
                                if not agent.conversation_id:
                                    agent.new_conversation()
                                response = agent.chat(
                                    msg, on_delta=on_delta, cancel=token
                                )
                                api_ref.pet_state = "idle"
                                api_ref._start_sleep_timer()
                                payload = response if isinstance(response, dict) else {"response": response}
                                payload["ok"] = True
                                api_ref._push_result("_onChatResult", json.dumps(payload, ensure_ascii=False))
                                api_ref._refresh_balance()
                            except Exception as e:
                                from agent.cancel import CancelledError

                                if isinstance(e, CancelledError):
                                    api_ref.pet_state = "idle"
                                    api_ref._start_sleep_timer()
                                    api_ref._push_result("_onChatResult", json.dumps({
                                        "ok": True, "cancelled": True,
                                        "response": "已停止。",
                                    }, ensure_ascii=False))
                                else:
                                    api_ref.pet_state = "cry"
                                    api_ref._start_sleep_timer()
                                    api_ref._push_result("_onChatResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                                    api_ref._refresh_balance()
                            finally:
                                service.controller.release()
                                service.controller.cancel_all_approvals()
                                api_ref._local_token = None

                        threading.Thread(target=_chat, daemon=True).start()
                        self._send_json({"ok": True, "pending": True})
                    elif self.path == "/api/models":
                        def _models():
                            try:
                                agent = api_ref._ensure_agent()
                                request = json.loads(body)
                                provider_id = request.get("provider_id", "custom")
                                preset = get_provider(provider_id)
                                if preset:
                                    base_url = preset["base_url"]
                                    protocol = preset["protocol"]
                                    models_path = preset.get("models_path", "/models")
                                    auth_mode = preset.get("auth_mode", "bearer")
                                    supports_temperature = preset.get("supports_temperature", True)
                                else:
                                    base_url = request.get("base_url", "")
                                    protocol = request.get("protocol", "chat")
                                    models_path = "/models"
                                    auth_mode = "bearer"
                                    supports_temperature = True
                                provider = OpenAIProvider(
                                    api_key=request.get("api_key", "") or agent.config.get("api_key", ""),
                                    base_url=base_url,
                                    protocol=protocol,
                                    models_path=models_path,
                                    auth_mode=auth_mode,
                                    supports_temperature=supports_temperature,
                                )
                                models = provider.list_models()
                                api_ref._push_result("_onModelsResult", json.dumps({"ok": True, "models": models}, ensure_ascii=False))
                            except Exception as e:
                                api_ref._push_result("_onModelsResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                        threading.Thread(target=_models, daemon=True).start()
                        self._send_json({"ok": True, "pending": True})
                    elif self.path == "/api/config":
                        def _save():
                            try:
                                agent = api_ref._ensure_agent()
                                config = json.loads(body)
                                agent.save_config(config)
                                if api_ref.sleep_cycle:
                                    api_ref.sleep_cycle.provider = agent.provider
                                    api_ref.sleep_cycle.reload_config()
                                api_ref._push_result("_onSaveConfigResult", json.dumps({"ok": True}, ensure_ascii=False))
                            except Exception as e:
                                api_ref._push_result("_onSaveConfigResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                        threading.Thread(target=_save, daemon=True).start()
                        self._send_json({"ok": True, "pending": True})
                    elif self.path == "/api/clear":
                        def _clear():
                            try:
                                agent = api_ref._ensure_agent()
                                agent.clear_history()
                                api_ref._push_result("_onClearHistoryResult", json.dumps({"ok": True}, ensure_ascii=False))
                            except Exception as e:
                                api_ref._push_result("_onClearHistoryResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                        threading.Thread(target=_clear, daemon=True).start()
                        self._send_json({"ok": True, "pending": True})
                    elif self.path == "/api/approve_tool":
                        result = api_ref.approve_tool(json.loads(body))
                        self._send_json(json.loads(result))
                    # -- 自动更新（POST）
                    elif self.path == "/api/update/download":
                        self._send_json(json.loads(api_ref.update_download(body or "{}")))
                    elif self.path == "/api/update/apply":
                        self._send_json(json.loads(api_ref.update_apply()))
                    # -- 远程互联（POST：写操作）
                    elif self.path == "/api/relay/start":
                        self._send_json(json.loads(api_ref.relay_start()))
                    elif self.path == "/api/relay/stop":
                        self._send_json(json.loads(api_ref.relay_stop()))
                    elif self.path == "/api/relay/settings":
                        self._send_json(json.loads(api_ref.relay_settings(body or "{}")))
                    elif self.path == "/api/relay/pin":
                        self._send_json(json.loads(api_ref.relay_pin(body or "{}")))
                    elif self.path == "/api/relay/pin/cancel":
                        self._send_json(json.loads(api_ref.relay_pin_cancel()))
                    elif self.path == "/api/relay/device_revoke":
                        self._send_json(json.loads(api_ref.relay_device_revoke(body)))
                    elif self.path == "/api/relay/device_revoke_all":
                        self._send_json(json.loads(api_ref.relay_devices_purge(body or "{}")))
                    # -- 停止按钮 ------------------------------------------
                    elif self.path == "/api/stop":
                        result = api_ref.stop_chat(json.dumps(json.loads(body) if body else {}))
                        self._send_json(json.loads(result))
                    elif self.path == "/api/approval_mode":
                        result = api_ref.set_approval_mode(json.loads(body))
                        self._send_json(json.loads(result))
                    elif self.path == "/api/thinking_level":
                        result = api_ref.set_thinking_level(json.loads(body))
                        self._send_json(json.loads(result))
                    elif self.path == "/api/sleep":
                        result = api_ref.save_sleep_settings(json.loads(body))
                        self._send_json(json.loads(result))
                    elif self.path == "/api/activity":
                        self._send_json({"ok": True})
                    elif self.path == "/api/conversations/new":
                        def _work():
                            try:
                                agent = api_ref._ensure_agent()
                                conv_id = agent.new_conversation()
                                api_ref._push_result("_onNewConversationResult", json.dumps({"ok": True, "id": conv_id}, ensure_ascii=False))
                            except Exception as e:
                                api_ref._push_result("_onNewConversationResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                        threading.Thread(target=_work, daemon=True).start()
                        self._send_json({"ok": True, "pending": True})
                    elif self.path == "/api/conversations/load":
                        data = json.loads(body)
                        conv_id = data.get("id", "")
                        def _work():
                            try:
                                agent = api_ref._ensure_agent()
                                conv = agent.load_conversation(conv_id)
                                if conv:
                                    api_ref._push_result("_onLoadConversationResult", json.dumps({"ok": True, "conversation": conv}, ensure_ascii=False))
                                else:
                                    api_ref._push_result("_onLoadConversationResult", json.dumps({"ok": False, "error": "Not found"}, ensure_ascii=False))
                            except Exception as e:
                                api_ref._push_result("_onLoadConversationResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                        threading.Thread(target=_work, daemon=True).start()
                        self._send_json({"ok": True, "pending": True})
                    elif self.path == "/api/conversations/delete":
                        data = json.loads(body)
                        conv_id = data.get("id", "")
                        def _work():
                            try:
                                agent = api_ref._ensure_agent()
                                agent.delete_conversation(conv_id)
                                convs = agent.list_conversations()
                                api_ref._push_result("_onConversationsResult", json.dumps({"ok": True, "conversations": convs}, ensure_ascii=False))
                            except Exception as e:
                                api_ref._push_result("_onConversationsResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                        threading.Thread(target=_work, daemon=True).start()
                        self._send_json({"ok": True, "pending": True})
                    else:
                        self.send_error(404)
                except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, fmt, *a):
                pass

            def handle_one_request(self):
                """兜住"客户端提前断开"这一类异常。

                为什么必须在这一层兜：BaseHTTPRequestHandler 的
                handle_one_request 里发生的异常会一路冒到 socketserver，
                由它打印一整段 traceback（用户实测看到满屏红字）。
                在 do_GET/do_POST 里 try 只能挡住一部分 ——
                写响应头、flush、send_error 都可能在中途炸。
                这里统一吞掉，语义上也正确：对方不等了，没什么可做的。
                """
                try:
                    return super().handle_one_request()
                except self.CLIENT_GONE:
                    self.close_connection = True
                except OSError as exc:
                    # 套接字层面的断开（含 Windows 的 WSAECONNRESET）
                    import errno as _errno

                    if exc.errno in (
                        _errno.ECONNRESET, _errno.EPIPE, _errno.ECONNABORTED,
                        getattr(_errno, "WSAECONNRESET", -1),
                        getattr(_errno, "WSAECONNABORTED", -1),
                    ):
                        self.close_connection = True
                    else:
                        raise

        try:
            httpd = http.server.ThreadingHTTPServer((host, port), PetHandler)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            actual = httpd.server_address[1]
            api_ref.server_port = actual
            print(f"[MollyPaw] Pet server started on http://{host}:{actual}/")
        except Exception as e:
            print("[MollyPaw] Pet server failed: " + str(e))

    # -- Chat --------------------------------------------------------------

    def send_message(self, message):
        """Send a user message to the agent and get a response."""
        self.pet_state = "work"
        self._mark_activity()

        def _do_chat():
            try:
                agent = self._ensure_agent()
                response = agent.chat(message)
                self.pet_state = "idle"
                self._start_sleep_timer()
                result = json.dumps({"ok": True, **(response if isinstance(response, dict) else {"response": response})}, ensure_ascii=False)
                self._refresh_balance()
            except Exception as e:
                self.pet_state = "cry"
                self._start_sleep_timer()
                result = json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
            self._queue_event("_onChatResult", json.loads(result))

        threading.Thread(target=_do_chat, daemon=True).start()
        return json.dumps({"ok": True, "pending": True}, ensure_ascii=False)

    # -- Pet state ---------------------------------------------------------

    def get_pet_state(self):
        return json.dumps({"state": self.pet_state}, ensure_ascii=False)

    def set_pet_state(self, state):
        if state in ("idle", "work", "cry", "sleep"):
            self.pet_state = state
            if state != "sleep":
                self._mark_activity()
            return json.dumps({"ok": True}, ensure_ascii=False)
        return json.dumps({"ok": False, "error": "Invalid state"}, ensure_ascii=False)

    def _start_sleep_timer(self):
        self._mark_activity()

    def open_url(self, url_json):
        """Open a URL in the system default browser."""
        import webbrowser
        try:
            data = _load_json_payload(url_json)
            url = data.get("url", "")
            if url and (url.startswith("http://") or url.startswith("https://")):
                webbrowser.open(url)
                return json.dumps({"ok": True}, ensure_ascii=False)
            return json.dumps({"ok": False, "error": "Invalid URL"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    # -- Config & utils ----------------------------------------------------

    def _queue_event(self, name, payload):
        with self._events_lock:
            self._events.append({"name": name, "payload": payload})

    def _push_result(self, callback, result):
        """推一个事件结果。

        这里**不能**用 _load_json_payload：event payload 可以是数组、
        字符串等任意 JSON 值（比如 skills 返回 list），不一定是 object。
        """
        try:
            payload = json.loads(result) if isinstance(result, str) else result
        except (TypeError, json.JSONDecodeError):
            payload = result
        self._queue_event(callback, payload)

    def get_events(self):
        with self._events_lock:
            events = self._events
            self._events = []
        return {"ok": True, "events": events}

    def _refresh_balance(self):
        def _work():
            try:
                agent = self._ensure_agent()
                preset = get_provider(agent.config.get("provider_id")) or {}
                result = agent.provider.get_balance(preset.get("balance_path", agent.config.get("balance_path", "")), preset.get("balance_parser", ""), preset.get("balance_base_url", ""))
            except Exception as e:
                result = {"ok": False, "supported": False, "error": str(e)}
            self._queue_event("_onBalanceResult", result)
        threading.Thread(target=_work, daemon=True).start()

    def get_config(self):
        def _work():
            try:
                agent = self._ensure_agent()
                config = agent.get_config()
                self._push_result("_onConfigResult", json.dumps({"ok": True, "config": config}, ensure_ascii=False))
            except Exception as e:
                self._push_result("_onConfigResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        threading.Thread(target=_work, daemon=True).start()
        return json.dumps({"ok": True, "pending": True}, ensure_ascii=False)

    def save_config(self, config_json):
        def _work():
            try:
                agent = self._ensure_agent()
                config = json.loads(config_json)
                agent.save_config(config)
                if self.sleep_cycle:
                    self.sleep_cycle.provider = agent.provider
                    self.sleep_cycle.reload_config()
                self._push_result("_onSaveConfigResult", json.dumps({"ok": True}, ensure_ascii=False))
            except Exception as e:
                self._push_result("_onSaveConfigResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        threading.Thread(target=_work, daemon=True).start()
        return json.dumps({"ok": True, "pending": True}, ensure_ascii=False)

    def clear_history(self):
        def _work():
            try:
                agent = self._ensure_agent()
                agent.clear_history()
                self._push_result("_onClearHistoryResult", json.dumps({"ok": True}, ensure_ascii=False))
            except Exception as e:
                self._push_result("_onClearHistoryResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        threading.Thread(target=_work, daemon=True).start()
        return json.dumps({"ok": True, "pending": True}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _base_dir():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def get_frontend_path():
    return "http://127.0.0.1:18765/"


# ---------------------------------------------------------------------------
# System tray
# ---------------------------------------------------------------------------

def get_tray_icon_image():
    icon_path = os.path.join(_base_dir(), "assets", "logo.png")
    if os.path.exists(icon_path):
        return Image.open(icon_path).convert("RGBA").resize((64, 64), Image.LANCZOS)
    return Image.new("RGBA", (64, 64), (139, 94, 60, 255))


def create_tray_icon(window):
    icon_image = get_tray_icon_image()

    def on_show(icon, item):
        """托盘点「显示」：把窗口带回来并置前。

        pywebview 的 Window **没有 focus() 方法**（focus 相关的是 bool 属性
        focused，不能调用）。以前这里写 window.focus()，于是每次点托盘都会
        抛 TypeError: 'bool' object is not callable。

        注意实际表现：窗口**照样会回来**（window.show() 已经先执行完了），
        异常被 pystray 自己打印后吞掉 —— 所以用户看到的是"功能正常、日志里
        多一段 traceback"，很容易被忽略。但日志被污染、restore 也没生效。
        正确的是 restore()：把窗口从最小化/隐藏状态恢复并激活。
        """
        try:
            window.show()
        except Exception:
            pass
        try:
            window.restore()
        except Exception:
            # 某些后端没有 restore，退回到 show 就够了
            pass

    def on_quit(icon, item):
        global _pet_process
        if _pet_process and _pet_process.poll() is None:
            try:
                _pet_process.terminate()
                _pet_process.wait(timeout=3)
            except Exception:
                try:
                    _pet_process.kill()
                except Exception:
                    pass
        icon.stop()
        try:
            window.destroy()
        except Exception:
            pass
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Show MollyPaw", on_show, default=True),
        pystray.MenuItem("Quit", on_quit),
    )
    return pystray.Icon("MollyPaw", icon_image, "MollyPaw Agent", menu)


# ---------------------------------------------------------------------------
# Pet subprocess
# ---------------------------------------------------------------------------

_pet_process = None
_tray_icon = None


class PetWindow:
    """Desktop pet tkinter window - polls pet state from HTTP server."""

    PET_SERVER = "http://127.0.0.1:18765"
    WIN_W, WIN_H = 300, 340
    IMG_SIZE = 220

    def __init__(self):
        import tkinter as tk
        from PIL import Image, ImageTk
        import urllib.request
        self._tk = tk
        self._ImageTk = ImageTk
        self._urlopen = urllib.request.urlopen

        self.root = tk.Tk()
        self.root.title("MollyPaw Pet")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        if sys.platform == "win32":
            self.root.attributes("-transparentcolor", "#FF00FF")
        self.root.configure(bg="#FF00FF")

        sx = self.root.winfo_screenwidth()
        sy = self.root.winfo_screenheight()
        self.root.geometry(
            f"{self.WIN_W}x{self.WIN_H}+{sx - self.WIN_W - 30}+{sy - self.WIN_H - 60}"
        )

        self.canvas = tk.Canvas(
            self.root, width=self.WIN_W, height=self.WIN_H,
            bg="#FF00FF", highlightthickness=0,
        )
        self.canvas.pack()

        self.images = {}
        self.current_state = None
        self.anim_jobs = []
        self.zzz_items = []
        self.tear_items = []

        self._load_images()

        self._drag_x = 0
        self._drag_y = 0
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)

        self.canvas.bind("<Button-3>", self._on_right_click)
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Close", command=self.root.destroy)

        self._poll()
        self.root.mainloop()

    def _load_images(self):
        import collections
        from PIL import Image
        loaded = True
        for state in ("idle", "work", "cry", "sleep"):
            url = f"{self.PET_SERVER}/pet_{state}.png"
            try:
                data = self._urlopen(url, timeout=5).read()
                img = Image.open(io.BytesIO(data)).convert("RGBA")
                img = img.resize((self.IMG_SIZE, self.IMG_SIZE), Image.NEAREST)
                sentinel = (255, 0, 255, 255)
                bg = img.getpixel((0, 0))[:3]
                pixels = img.load()
                w, h = img.size
                visited = set()
                queue = collections.deque()
                for start in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
                    queue.append(start)
                while queue:
                    px, py = queue.popleft()
                    if (px, py) in visited:
                        continue
                    if px < 0 or px >= w or py < 0 or py >= h:
                        continue
                    r, g, b = pixels[px, py][:3]
                    if abs(r - bg[0]) < 15 and abs(g - bg[1]) < 15 and abs(b - bg[2]) < 15:
                        visited.add((px, py))
                        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                            queue.append((px + dx, py + dy))
                for px, py in visited:
                    pixels[px, py] = sentinel
                self.images[state] = self._ImageTk.PhotoImage(img)
            except Exception as e:
                print(f"[Pet] Load failed {state}: {e}")
                loaded = False
        if not loaded:
            self.root.after(2000, self._load_images)

    def _set_state(self, state):
        if state == self.current_state:
            return
        if state not in self.images:
            return
        self.current_state = state
        self._cancel_anims()
        self.canvas.delete("all")
        self.canvas.create_image(
            self.WIN_W // 2, self.WIN_H // 2 + 15,
            image=self.images[state], anchor="center",
        )
        if state == "sleep":
            self._show_bubble("zzZ...")
            self._start_zzz()
        elif state == "cry":
            self._show_bubble("API连不上了...呜呜")
            self._start_tears()
        elif state == "work":
            self._show_bubble("认真翻书中~")

    def _cancel_anims(self):
        for jid in self.anim_jobs:
            try:
                self.root.after_cancel(jid)
            except Exception:
                pass
        self.anim_jobs.clear()
        self.zzz_items.clear()
        self.tear_items.clear()

    def _show_bubble(self, text):
        x, y = self.WIN_W // 2, 18
        w = max(len(text) * 10 + 24, 80)
        self.canvas.create_rectangle(
            x - w // 2, y - 14, x + w // 2, y + 14,
            fill="#FFFFFF", outline="#D2B48C", width=2, tags="overlay",
        )
        self.canvas.create_text(
            x, y, text=text, font=("Microsoft YaHei", 9),
            fill="#6B4226", tags="overlay",
        )

    def _start_zzz(self):
        self._tick_zzz(0)

    def _tick_zzz(self, idx):
        if self.current_state != "sleep":
            return
        for item in self.zzz_items:
            self.canvas.delete(item)
        self.zzz_items.clear()
        chars = [("z", 12), ("z", 16), ("Z", 20)]
        for i, (ch, sz) in enumerate(chars):
            off = ((idx + i) % 4) * 4
            item = self.canvas.create_text(
                160 + i * 16, 40 - off,
                text=ch, font=("Courier", sz, "bold"), fill="#7BA4C8",
            )
            self.zzz_items.append(item)
        jid = self.root.after(500, self._tick_zzz, idx + 1)
        self.anim_jobs.append(jid)

    def _start_tears(self):
        self._tick_tears()

    def _tick_tears(self):
        if self.current_state != "cry":
            return
        for item in self.tear_items:
            self.canvas.delete(item)
        self.tear_items.clear()
        for x_off in [75, 145]:
            y = random.randint(80, 115)
            item = self.canvas.create_oval(
                x_off - 3, y, x_off + 3, y + 8,
                fill="#5BADE5", outline="",
            )
            self.tear_items.append(item)
        jid = self.root.after(400, self._tick_tears)
        self.anim_jobs.append(jid)

    def _poll(self):
        try:
            data = self._urlopen(f"{self.PET_SERVER}/state", timeout=2).read()
            result = json.loads(data)
            self._set_state(result.get("state", "idle"))
        except Exception:
            pass
        self.root.after(1000, self._poll)

    def _on_press(self, event):
        self._drag_x = event.x_root
        self._drag_y = event.y_root

    def _on_drag(self, event):
        dx = event.x_root - self._drag_x
        dy = event.y_root - self._drag_y
        self._drag_x = event.x_root
        self._drag_y = event.y_root
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")

    def _on_right_click(self, event):
        self.menu.post(event.x_root, event.y_root)


def start_pet():
    """Launch pet: subprocess in dev, thread in frozen (PyInstaller) build."""
    global _pet_process
    if getattr(sys, 'frozen', False):
        # Frozen build: can't subprocess python script, run in thread instead.
        # The tray keeps the main process alive, so the pet thread survives.
        try:
            PetWindow()
        except Exception as e:
            print("[MollyPaw] Pet failed: " + str(e))
    else:
        # Dev mode: run pet.py as a real subprocess (survives window close).
        pet_script = os.path.join(_base_dir(), 'pet.py')
        try:
            _pet_process = subprocess.Popen(
                [sys.executable, pet_script],
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            print("[MollyPaw] Pet subprocess started (pid=" + str(_pet_process.pid) + ")")
        except Exception as e:
            print("[MollyPaw] Pet subprocess failed: " + str(e))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global _tray_icon
    api = MollyPawAPI()
    api.start_pet_server()

    # Main chat window
    window = webview.create_window(
        "MollyPaw",
        get_frontend_path(),
        width=1280,
        height=900,
        min_size=(1100, 800),
        text_select=True,
    )
    # Launch pet as a real subprocess (survives window close)
    threading.Thread(target=start_pet, daemon=True).start()

    # Initialize the sleep cycle. Mode "off" creates no worker thread.
    api._ensure_agent()

    # --- Tray: non-daemon thread started BEFORE webview ---
    tray_thread = None
    if HAS_TRAY:
        def on_closing():
            window.hide()
            return False

        window.events.closing += on_closing

        def start_tray():
            global _tray_icon
            try:
                _tray_icon = create_tray_icon(window)
                _tray_icon.run()  # blocking
            except Exception as e:
                print("[MollyPaw] Tray error: " + str(e))

        tray_thread = threading.Thread(target=start_tray, daemon=False)
        tray_thread.start()

    # webview.start() MUST run on main thread (Windows requirement)
    try:
        webview.start(debug=("--debug" in sys.argv))
    except Exception as e:
        print("[MollyPaw] Webview error: " + str(e))

    # webview returned -> window destroyed. Clean up.
    if _pet_process and _pet_process.poll() is None:
        try:
            _pet_process.terminate()
            _pet_process.wait(timeout=3)
        except Exception:
            try:
                _pet_process.kill()
            except Exception:
                pass

    # If tray is still running, wait for it (user may still be using tray)
    if tray_thread and tray_thread.is_alive():
        tray_thread.join(timeout=5)

    os._exit(0)


if __name__ == "__main__":
    import atexit
    atexit.register(lambda: os.remove(_LOCK_PATH) if os.path.exists(_LOCK_PATH) else None)
    main()
