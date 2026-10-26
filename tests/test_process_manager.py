"""停止语义测试 —— 命令转后台 + 模型能看见 / 能杀。

用户的原话：
  「你那个停止应该把正在执行的命令塞进后台进程 然后给Ai展示进程
    让AI杀 没有子进程就杀主进程」

所以这里测四件事：
  1. 点停止时命令**不被杀**，转入后台继续跑（这才是"塞进后台"）。
  2. 后台进程出现在系统提示里（AI 能看见）。
  3. process_kill 有子进程杀整棵树、没子进程杀主进程。
  4. 取消异常不能被 ToolRegistry 吞掉（吞了就永远停不下来）。
"""
import os
import subprocess
import sys
import threading
import time

import pytest

from agent.cancel import CancelToken, CancelledError
from agent.process_manager import ProcessManager, child_pids, manager
from agent.tools.exec_tool import ExecTool
from agent.tools.process_tool import ProcessTool
from agent.tools.registry import ToolRegistry

WINDOWS = os.name == "nt"


def _long_cmd(seconds=60):
    """一条会跑很久的命令（跨平台）。"""
    if WINDOWS:
        return "Start-Sleep -Seconds %d" % seconds
    return "sleep %d" % seconds


def _wait(pred, timeout=8.0, interval=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(interval)
    return False


def _pid_alive(pid):
    if WINDOWS:
        out = subprocess.run(
            ["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="gbk", errors="replace",
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# ProcessManager 基础
# ---------------------------------------------------------------------------

@pytest.fixture
def mgr():
    """每个测试一个干净的托管器，别串味。"""
    manager_ = ProcessManager(autostart_watchdog=False)
    yield manager_
    manager_.kill_all(by="cleanup")
    manager_.clear()


class TestAdopt:
    def test_adopt_visible_and_output_readable(self, mgr):
        proc = subprocess.Popen(
            [sys.executable, "-u", "-c",
             "print('hello-bg'); import time; time.sleep(30)"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        out_chunks, err_chunks = [], []

        def _reader(stream, sink):
            try:
                for line in iter(stream.readline, ""):
                    sink.append(line)
            except Exception:
                pass

        threading.Thread(target=_reader, args=(proc.stdout, out_chunks), daemon=True).start()
        threading.Thread(target=_reader, args=(proc.stderr, err_chunks), daemon=True).start()

        entry = mgr.adopt(proc, "python -c ...", out_chunks, err_chunks)
        try:
            assert entry.alive is True
            assert mgr.get(proc.pid) is entry
            assert _wait(lambda: "hello-bg" in entry.snapshot()[0], timeout=8)
            assert mgr.count() >= 1
        finally:
            mgr.kill(proc.pid)

    def test_finished_process_marked_exited(self, mgr):
        proc = subprocess.Popen(
            [sys.executable, "-u", "-c", "print('done')"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        chunks = []
        threading.Thread(
            target=lambda: [chunks.append(l) for l in iter(proc.stdout.readline, "")],
            daemon=True).start()
        entry = mgr.adopt(proc, "print done", chunks, [])
        try:
            assert _wait(lambda: not entry.alive, timeout=10)
            entry.refresh_exit()
            assert entry.exit_code == 0
        finally:
            mgr.kill(proc.pid)


# ---------------------------------------------------------------------------
# 杀：有子进程杀树，没子进程杀主进程
# ---------------------------------------------------------------------------

class TestKill:
    def test_kill_without_children_kills_main(self, mgr):
        proc = subprocess.Popen(
            [sys.executable, "-u", "-c", "import time; time.sleep(60)"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        entry = mgr.adopt(proc, "sleep 60", [], [])
        try:
            assert proc.poll() is None
            info = mgr.kill(proc.pid, by="user")
            assert info["children"] == [], "这个进程不该有子进程"
            assert info["ok"] is True
            assert _wait(lambda: proc.poll() is not None, timeout=8)
            assert entry.killed_by == "user"
        finally:
            mgr.kill(proc.pid, by="cleanup")

    @pytest.mark.skipif(not WINDOWS, reason="子进程树行为在 Windows 上验证")
    def test_kill_with_children_kills_tree(self, mgr):
        # 起一个父进程，父进程再起一个长命子进程
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "$c = Start-Process -PassThru -WindowStyle Hidden "
             "-FilePath powershell -ArgumentList '-NoProfile','-Command','Start-Sleep -Seconds 60'; "
             "Write-Output ('child=' + $c.Id); Start-Sleep -Seconds 60"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        chunks = []
        threading.Thread(
            target=lambda: [chunks.append(l) for l in iter(proc.stdout.readline, "")],
            daemon=True).start()
        entry = mgr.adopt(proc, "tree", chunks, [])
        try:
            assert _wait(lambda: child_pids(proc.pid), timeout=20), "没抓到子进程"
            kids = child_pids(proc.pid)
            info = mgr.kill(proc.pid, by="user")
            assert info["children"], "应报告出子进程"
            assert _wait(
                lambda: all(not _pid_alive(k) for k in kids), timeout=10
            ), "子进程没被一起杀掉"
        finally:
            mgr.kill(proc.pid, by="cleanup")


# ---------------------------------------------------------------------------
# exec_command：取消 → 转后台，不杀
# ---------------------------------------------------------------------------

class TestExecCancelHandsOff:
    def test_cancel_moves_to_background_not_kill(self):
        token = CancelToken()
        box = {}

        def _run():
            try:
                box["result"] = ExecTool().exec_command(
                    _long_cmd(60), timeout=120, cancel=token)
            except CancelledError as exc:
                box["cancelled"] = str(exc)
            except Exception as exc:  # noqa: BLE001
                box["error"] = repr(exc)

        before = {e.pid for e in manager().list()}
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        time.sleep(2.0)   # 让命令真的跑起来（还没进后台表，因为没取消）

        token.cancel("user")
        thread.join(timeout=10)
        assert not thread.is_alive(), "取消之后 exec_command 没立刻返回 —— UI 会卡在正在停"

        assert "cancelled" in box, box
        assert "background" in box["cancelled"]

        alive = [e for e in manager().list() if e.alive and e.pid not in before]
        assert alive, "命令被杀了——用户要的是'塞进后台'，不是'杀掉'"
        pid = alive[0].pid
        assert _pid_alive(pid), "后台进程已经不在了"
        assert str(pid) in box["cancelled"]

        # 收尾
        manager().kill(pid, by="cleanup")
        assert _wait(lambda: not _pid_alive(pid), timeout=10)

    def test_timeout_hands_off_with_pid(self):
        tool = ExecTool()
        started = time.time()
        out = tool.exec_command(_long_cmd(60), timeout=1)
        elapsed = time.time() - started
        assert elapsed < 15, "超时没有及时把命令推去后台，还是阻塞住了"
        assert "转入后台" in out or "background" in out
        assert "process_kill" in out
        # 清理
        for entry in manager().list():
            manager().kill(entry.pid, by="cleanup")


# ---------------------------------------------------------------------------
# 给模型看 + 给模型杀
# ---------------------------------------------------------------------------

class TestPromptAndTools:
    def test_prompt_block_lists_background_process(self):
        token, _box = _detach_one()
        try:
            block = manager().prompt_block()
            assert "后台进程" in block
            assert "process_list" in block
            assert "process_kill" in block
        finally:
            _cleanup_bg()

    def test_process_list_tool(self):
        token, _box = _detach_one()
        try:
            text = ProcessTool().process_list()
            assert "background process" in text
            assert "running" in text
        finally:
            _cleanup_bg()

    def test_process_kill_tool(self):
        token, _box = _detach_one()
        try:
            entries = [e for e in manager().list() if e.alive]
            assert entries
            pid = entries[0].pid
            text = ProcessTool().process_kill(pid=pid)
            assert "pid=%d" % pid in text
            assert _wait(lambda: not _pid_alive(pid), timeout=10)
        finally:
            _cleanup_bg()

    def test_process_list_unknown_pid(self):
        text = ProcessTool().process_list(pid=999999)
        assert "No background process" in text


def _detach_one():
    """跑一条长命令，取消它，让它进后台表。返回 (取消后的 token, 结果盒)。"""
    token = CancelToken()
    box = {}
    threading.Thread(target=lambda: _swallow(ExecTool(), token, box),
                     daemon=True).start()
    time.sleep(2.0)
    token.cancel("user")
    assert _wait(lambda: any(e.alive for e in manager().list()), timeout=10), \
        "取消后命令没进后台表"
    return token, box


def _cleanup_bg():
    manager().kill_all(by="cleanup")


def _swallow(tool, token, box=None):
    try:
        tool.exec_command(_long_cmd(60), timeout=120, cancel=token)
    except Exception as exc:  # noqa: BLE001
        if box is not None:
            box["exc"] = repr(exc)


# ---------------------------------------------------------------------------
# 取消不能被吞
# ---------------------------------------------------------------------------

class TestRegistryPropagatesCancel:
    def test_registry_does_not_swallow_cancelled_error(self):
        class _Boom:
            TOOLS = [{
                "type": "function",
                "function": {"name": "boom", "parameters": {
                    "type": "object", "properties": {}}},
            }]

            def execute(self, func_name, arguments):
                raise CancelledError("stop")

        registry = ToolRegistry()
        registry.register(_Boom())
        with pytest.raises(CancelledError):
            registry.execute("boom", {})

    def test_registry_still_reports_normal_errors(self):
        class _Boom:
            TOOLS = [{
                "type": "function",
                "function": {"name": "boom2", "parameters": {
                    "type": "object", "properties": {}}},
            }]

            def execute(self, func_name, arguments):
                raise RuntimeError("kaput")

        registry = ToolRegistry()
        registry.register(_Boom())
        out = registry.execute("boom2", {})
        assert out.startswith("Error executing")


# ---------------------------------------------------------------------------
# 停止不再硬杀（controller 层）
# ---------------------------------------------------------------------------

class TestControllerStopDoesNotKill:
    def test_stop_only_cancels(self):
        from agent.service import _FallbackController

        controller = _FallbackController()
        token = controller.acquire("local")
        assert token is not None
        try:
            assert controller.stop(by="local") is True
            assert token.cancelled is True
        finally:
            controller.release()


# ---------------------------------------------------------------------------
# 系统提示里能看见（AI 每轮都拿得到）
# ---------------------------------------------------------------------------

class TestSystemPromptSeesBackground:
    def test_build_system_prompt_includes_block(self):
        from agent.core import AgentCore

        token, _box = _detach_one()
        try:
            prompt = AgentCore()._build_system_prompt()
            assert "后台进程" in prompt
            assert "process_kill" in prompt
        finally:
            _cleanup_bg()

    def test_prompt_clean_when_nothing_running(self):
        _cleanup_bg()
        from agent.core import AgentCore

        prompt = AgentCore()._build_system_prompt()
        assert "后台进程（用户按过停止后留下的）" not in prompt


# ---------------------------------------------------------------------------
# HTTP API：前端和手机用这两条
# ---------------------------------------------------------------------------

class TestProcessesAPI:
    def test_processes_endpoint_reports_items(self):
        import json as _json

        from main import MollyPawAPI

        token, _box = _detach_one()
        try:
            payload = _json.loads(MollyPawAPI().processes())
            assert payload["ok"] is True
            assert payload["count"] >= 1
            assert any(item["alive"] for item in payload["items"])
            assert all("pid" in item for item in payload["items"])
        finally:
            _cleanup_bg()

    def test_processes_kill_endpoint(self):
        import json as _json

        from main import MollyPawAPI

        token, _box = _detach_one()
        try:
            entries = [e for e in manager().list() if e.alive]
            assert entries
            pid = entries[0].pid
            payload = _json.loads(
                MollyPawAPI().processes_kill(_json.dumps({"pid": pid})))
            assert payload["ok"] is True
            assert _wait(lambda: not _pid_alive(pid), timeout=10)
        finally:
            _cleanup_bg()
