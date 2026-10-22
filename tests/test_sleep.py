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


if __name__ == "__main__":
    unittest.main()
