import unittest

from agent.core import AgentCore
from agent.tools.exec_tool import ExecTool
from agent.tools.registry import ToolRegistry


class RegistryTests(unittest.TestCase):
    def test_missing_required_argument_returns_error(self):
        registry = ToolRegistry()
        registry.register(ExecTool())
        result = registry.execute("exec_command", {})
        self.assertIn("missing required argument", result)
        self.assertIn("cmd", result)

    def test_repair_tool_history_adds_missing_result(self):
        core = AgentCore.__new__(AgentCore)
        core.history = [
            {"role": "system", "content": "system"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "exec_command", "arguments": "{}"}}]},
            {"role": "user", "content": "next"},
        ]
        core._repair_tool_history()
        self.assertEqual(core.history[2]["role"], "tool")
        self.assertEqual(core.history[2]["tool_call_id"], "c1")
        self.assertEqual(core.history[3]["role"], "user")


if __name__ == "__main__":
    unittest.main()
