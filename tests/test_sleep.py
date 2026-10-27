import os
import tempfile
import unittest
from unittest.mock import patch

from agent.sleep import SleepCycle


class DummyProvider:
    def chat(self, messages, tools=None):
        return {"content": "ok", "tool_calls": []}


class SleepTests(unittest.TestCase):
    def make_cycle(self, mode):
        return SleepCycle(
            DummyProvider(),
            {"sleep": {"mode": mode, "tasks": ["memory", "review", "dream"], "idle_minutes": 30, "max_llm_calls": 3}},
            lambda state: None,
            lambda: False,
        )

    def test_off_does_not_start_thread(self):
        with tempfile.TemporaryDirectory() as tmp, patch("agent.sleep.data_dir", return_value=tmp):
            cycle = self.make_cycle("off")
            cycle.start()
            self.assertIsNone(cycle._monitor_thread)

    def test_display_only_makes_no_llm_calls(self):
        class CountingProvider:
            def __init__(self):
                self.calls = 0

            def chat(self, messages, tools=None):
                self.calls += 1
                return {"content": "unexpected", "tool_calls": []}

        with tempfile.TemporaryDirectory() as tmp, patch("agent.sleep.data_dir", return_value=tmp):
            states = []
            provider = CountingProvider()
            cycle = SleepCycle(provider, {"sleep": {"mode": "display_only", "tasks": ["memory"], "idle_minutes": 1, "max_llm_calls": 3}}, states.append, lambda: False)
            cycle._enter_sleep()
            self.assertEqual(provider.calls, 0)
            self.assertIn("sleep", states)

    def test_memory_only_does_not_write_dream(self):
        with tempfile.TemporaryDirectory() as tmp, patch("agent.sleep.data_dir", return_value=tmp), patch("agent.sleep.conversations_dir", return_value=tmp):
            cycle = SleepCycle(DummyProvider(), {"sleep": {"mode": "full", "tasks": ["memory"], "idle_minutes": 1, "max_llm_calls": 3}}, lambda state: None, lambda: False)
            cycle._enter_sleep()
            self.assertEqual(os.listdir(os.path.join(tmp, "dreams")), [])

    def test_sensitive_memory_is_rejected(self):
        self.assertTrue(SleepCycle._contains_sensitive("api_key: sk-test-12345678"))

    def test_dream_write_path_is_restricted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "dreams")
            os.makedirs(root)
            self.assertTrue(SleepCycle._is_safe_write_path(os.path.join(root, "dream_2026_09_14_1.md"), root))
            self.assertFalse(SleepCycle._is_safe_write_path(os.path.join(tmp, "evil.md"), root))

    def test_sleep_registry_only_exposes_safe_tools(self):
        with tempfile.TemporaryDirectory() as tmp, patch("agent.sleep.data_dir", return_value=tmp):
            cycle = self.make_cycle("full")
            _, schemas = cycle._sleep_registry(cycle.MEMORY_TOOLS | cycle.FILE_TOOLS)
            names = {schema["function"]["name"] for schema in schemas}
            self.assertEqual(names, cycle.MEMORY_TOOLS | cycle.FILE_TOOLS)
            self.assertNotIn("exec_command", names)
            self.assertNotIn("web_search", names)
            self.assertNotIn("fetch", names)


# ---------------------------------------------------------------------------
# 修过的睡眠 bug —— 每个都是一次真实踩坑
# ---------------------------------------------------------------------------

class TestIdleMinutesHonoured:
    """以前 idle_minutes 被硬编码 30 秒覆盖掉，用户配置永远不生效。"""

    def _cycle(self, sleep_cfg):
        return SleepCycle(
            DummyProvider(),
            {"sleep": sleep_cfg},
            lambda state: None,
            lambda: False,
        )

    def test_configured_idle_minutes_is_used(self):
        with tempfile.TemporaryDirectory() as tmp, patch("agent.sleep.data_dir", return_value=tmp):
            cycle = self._cycle({"mode": "full", "idle_minutes": 30})
            assert cycle.get_status()["idle_minutes"] == 30
            assert cycle._sleep_config["idle_minutes"] == 30

    def test_fractional_idle_minutes_survives(self):
        with tempfile.TemporaryDirectory() as tmp, patch("agent.sleep.data_dir", return_value=tmp):
            cycle = self._cycle({"mode": "full", "idle_minutes": 2.5})
            assert cycle.get_status()["idle_minutes"] == 2.5

    def test_absurd_value_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as tmp, patch("agent.sleep.data_dir", return_value=tmp):
            for bad in (0, -5, "abc", None):
                cycle = self._cycle({"mode": "full", "idle_minutes": bad})
                assert cycle.get_status()["idle_minutes"] == SleepCycle.DEFAULT_IDLE_MINUTES

    def test_too_small_value_is_clamped(self):
        with tempfile.TemporaryDirectory() as tmp, patch("agent.sleep.data_dir", return_value=tmp):
            cycle = self._cycle({"mode": "full", "idle_minutes": 0.01})
            assert cycle.get_status()["idle_minutes"] == SleepCycle.MIN_IDLE_MINUTES

    def test_max_llm_calls_no_longer_in_status(self):
        # 用户要求把睡眠的调用上限也删掉，配置里不该再冒出来
        with tempfile.TemporaryDirectory() as tmp, patch("agent.sleep.data_dir", return_value=tmp):
            cycle = self._cycle({"mode": "full", "max_llm_calls": 3})
            assert "max_llm_calls" not in cycle.get_status()


class TestFailureDoesNotStickAsleep:
    """整理任务抛异常时，状态不能卡在 sleeping —— 那会让宠物永久睡觉。"""

    def test_provider_error_leaves_pet_awake(self):
        class BoomProvider:
            def chat(self, messages, tools=None, cancel=None):
                raise RuntimeError("model exploded")

        with tempfile.TemporaryDirectory() as tmp, patch("agent.sleep.data_dir", return_value=tmp), \
                patch("agent.sleep.conversations_dir", return_value=tmp):
            os.makedirs(os.path.join(tmp, "dreams"), exist_ok=True)
            states = []
            with open(os.path.join(tmp, "c1.json"), "w", encoding="utf-8") as f:
                import json as _json
                _json.dump({"updated_at": 1, "messages": [
                    {"role": "user", "content": "你好"}]}, f)
            cycle = SleepCycle(
                BoomProvider(),
                {"sleep": {"mode": "full", "tasks": ["memory"]}},
                states.append, lambda: False,
            )
            cycle._enter_sleep()
            assert cycle.state != "sleeping", "异常后状态卡在 sleeping，宠物会永久睡觉"
            assert cycle.state in ("awake", "deepsleep")
            # 关键：还能被用户活动叫醒（以前 monitor 线程死了就再也醒不过来）
            cycle.mark_activity()
            assert cycle.state == "awake"
            assert states[-1] == "idle"

    def test_missing_conversations_dir_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp, patch("agent.sleep.data_dir", return_value=tmp):
            cycle = SleepCycle(
                DummyProvider(),
                {"sleep": {"mode": "full", "tasks": ["memory"]}},
                lambda state: None, lambda: False,
            )
            missing = os.path.join(tmp, "nope")
            with patch("agent.sleep.conversations_dir", return_value=missing):
                text, watermark = cycle._load_transcript(0)
            assert text == ""

    def test_watermark_advances_to_latest_update_not_start_time(self):
        import json as _json

        with tempfile.TemporaryDirectory() as tmp, patch("agent.sleep.data_dir", return_value=tmp), \
                patch("agent.sleep.conversations_dir", return_value=tmp):
            path = os.path.join(tmp, "c1.json")
            with open(path, "w", encoding="utf-8") as f:
                _json.dump({"updated_at": 111.0, "messages": [
                    {"role": "user", "content": "整理我"}]}, f)
            cycle = SleepCycle(
                DummyProvider(),
                {"sleep": {"mode": "full", "tasks": ["memory"]}},
                lambda state: None, lambda: False,
            )
            text, latest = cycle._load_transcript(1000.0)
            assert "整理我" in text
            assert latest == 111.0, "水位线应该是会话更新时间，不是整理开始时间"


class TestWakeInterruptsBlockedCall:
    """用户回来了必须能立刻打断睡眠里的模型调用。"""

    def test_wake_cancels_in_flight_llm_call(self):
        import threading as _threading
        import time as _time

        started = _threading.Event()
        finished = _threading.Event()

        class BlockingProvider:
            def chat(self, messages, tools=None, cancel=None):
                started.set()
                if cancel is None:
                    _time.sleep(5)
                    return {"content": "late", "tool_calls": []}
                done = _threading.Event()
                cancel.on_cancel(done.set)
                done.wait(10)
                cancel.raise_if_cancelled()
                return {"content": "late", "tool_calls": []}

        with tempfile.TemporaryDirectory() as tmp, patch("agent.sleep.data_dir", return_value=tmp), \
                patch("agent.sleep.conversations_dir", return_value=tmp):
            os.makedirs(os.path.join(tmp, "dreams"), exist_ok=True)
            import json as _json
            with open(os.path.join(tmp, "c1.json"), "w", encoding="utf-8") as f:
                _json.dump({"updated_at": 1, "messages": [
                    {"role": "user", "content": "你好"}]}, f)
            cycle = SleepCycle(
                BlockingProvider(),
                {"sleep": {"mode": "full", "tasks": ["memory"]}},
                lambda state: None, lambda: False,
            )

            def _run():
                cycle._enter_sleep()
                finished.set()

            thread = _threading.Thread(target=_run, daemon=True)
            thread.start()
            assert started.wait(5), "模型调用没开始"
            assert cycle.state == "sleeping"

            began = _time.time()
            cycle.wake()
            assert finished.wait(5), "wake 之后阻塞调用没被打断 —— 用户要一直等"
            assert _time.time() - began < 5
            assert cycle.state == "awake"


class TestNoCallLimit:
    """用户明确要求：睡眠的 LLM 调用也不许设上限，活才干得完。"""

    def test_runs_until_model_stops_asking_for_tools(self):
        class LoopProvider:
            def __init__(self):
                self.calls = 0

            def chat(self, messages, tools=None, cancel=None):
                self.calls += 1
                if self.calls >= 120:
                    return {"content": "done", "tool_calls": []}
                return {
                    "content": "",
                    "tool_calls": [{
                        "id": "c%d" % self.calls,
                        "function": {"name": "list_memories",
                                     "arguments": "{}"},
                    }],
                }

        with tempfile.TemporaryDirectory() as tmp, patch("agent.sleep.data_dir", return_value=tmp):
            cycle = SleepCycle(
                LoopProvider(),
                {"sleep": {"mode": "full", "tasks": ["memory"]}},
                lambda state: None, lambda: False,
            )
            ok = cycle._run_prompt("sleep now", cycle.MEMORY_TOOLS)
            assert ok is True
            assert cycle.provider.calls == 120, \
                "在第 %d 次就停了，说明还有调用上限" % cycle.provider.calls


class TestPetStateShowsSleep:
    """宠物得真的显示"在睡觉"。

    睡眠周期直接改 service.pet_state（不能走 set_pet_state，会递归回
    mark_activity → wake），而 main 那份 pet_state 拷贝只在启动时同步一次。
    结果就是：睡着了，界面还显示待命。
    """

    def test_main_reads_service_pet_state(self):
        from main import MollyPawAPI

        api = MollyPawAPI()

        class FakeService:
            pet_state = "sleep"

        api.service = FakeService()
        assert api.current_pet_state() == "sleep"
        assert '"sleep"' in api.get_pet_state()

    def test_falls_back_when_no_service(self):
        from main import MollyPawAPI

        api = MollyPawAPI()
        assert api.current_pet_state() == api.pet_state


class TestOldConfigMigration:
    """老用户的 config.json 里 sleep 段还是 0.0.0.2.0 的硬编码值。

    不迁移的话：升级到 0.0.0.2.1 之后 `idle_minutes` 仍然是 0.5（30 秒），
    界面上改了也不一定生效，等于这个修复对老用户完全没用。
    """

    def _write_config(self, tmp, sleep_cfg):
        import json as _json

        from agent.paths import config_path

        with open(config_path(), "w", encoding="utf-8") as f:
            _json.dump({"api_key": "k", "model": "m", "sleep": sleep_cfg}, f)

    def _read_config(self):
        import json as _json

        from agent.paths import config_path

        with open(config_path(), encoding="utf-8") as f:
            return _json.load(f)

    def test_hardcoded_half_minute_migrates_to_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLLYPAW_DATA_DIR", str(tmp_path))
        self._write_config(tmp_path, {
            "mode": "full", "tasks": ["memory"],
            "idle_minutes": 0.5, "max_llm_calls": 100,
        })
        from agent.core import AgentCore

        agent = AgentCore()
        assert agent.config["sleep"]["idle_minutes"] == SleepCycle.DEFAULT_IDLE_MINUTES
        assert "max_llm_calls" not in agent.config["sleep"]
        # 迁移要落盘
        on_disk = self._read_config()
        assert on_disk["sleep"]["idle_minutes"] == SleepCycle.DEFAULT_IDLE_MINUTES
        assert "max_llm_calls" not in on_disk["sleep"]
        # 其他字段不能丢
        assert on_disk["sleep"]["mode"] == "full"

    def test_user_chosen_idle_minutes_is_kept(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLLYPAW_DATA_DIR", str(tmp_path))
        self._write_config(tmp_path, {
            "mode": "full", "tasks": ["memory"],
            "idle_minutes": 45, "max_llm_calls": 100,
        })
        from agent.core import AgentCore

        agent = AgentCore()
        assert agent.config["sleep"]["idle_minutes"] == 45

    def test_missing_max_llm_calls_means_already_migrated(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLLYPAW_DATA_DIR", str(tmp_path))
        self._write_config(tmp_path, {
            "mode": "full", "tasks": ["memory"], "idle_minutes": 20,
        })
        from agent.core import AgentCore

        agent = AgentCore()
        assert agent.config["sleep"]["idle_minutes"] == 20

    def test_default_config_is_not_polluted_by_loaded_config(self, tmp_path, monkeypatch):
        """dict(DEFAULT_CONFIG) 是浅拷贝，曾经会把类级默认值改掉。"""
        monkeypatch.setenv("MOLLYPAW_DATA_DIR", str(tmp_path))
        self._write_config(tmp_path, {
            "mode": "display_only", "tasks": [],
            "idle_minutes": 0.5, "max_llm_calls": 7,
        })
        from agent.core import AgentCore

        AgentCore()
        assert AgentCore.DEFAULT_CONFIG["sleep"]["idle_minutes"] == 10
        assert "max_llm_calls" not in AgentCore.DEFAULT_CONFIG["sleep"]


if __name__ == "__main__":
    unittest.main()
