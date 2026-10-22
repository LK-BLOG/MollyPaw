import unittest

from agent.core import AgentCore


class FakeProvider:
    def __init__(self):
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append(messages)
        return {"content": "旧对话摘要"}


class ContextTests(unittest.TestCase):
    def test_masked_api_key_is_rejected(self):
        self.assertTrue(AgentCore._is_masked_api_key("sk-123456...abcd"))
        self.assertFalse(AgentCore._is_masked_api_key("sk-1234567890abcdef"))
    def test_context_uses_summary_when_over_budget(self):
        core = AgentCore.__new__(AgentCore)
        core.config = {"context_window": 8000, "provider_id": "custom"}
        core.provider = FakeProvider()
        core.history = [{"role": "system", "content": "system"}]
        for index in range(1, 23):
            core.history.append({"role": "user", "content": f"user-{index}-" + ("x" * 300)})
            core.history.append({"role": "assistant", "content": f"assistant-{index}-" + ("y" * 300)})

        result = core._context_history()
        summaries = [m for m in result if m.get("role") == "system" and "[历史摘要]" in str(m.get("content"))]
        self.assertEqual(result[0]["content"], "system")
        self.assertEqual(len(summaries), 1)
        self.assertTrue(any(str(m.get("content", "")).startswith("user-1-") for m in result))
        self.assertTrue(any(str(m.get("content", "")).startswith("user-22-") for m in result))
        self.assertFalse(any(str(m.get("content", "")).startswith("user-12-") for m in result))
        self.assertEqual(len(core.provider.calls), 1)

    def test_empty_tool_phase_gets_final_text_retry(self):
        class EmptyThenFinalProvider:
            def __init__(self):
                self.calls = 0

            def chat(self, messages, tools=None):
                self.calls += 1
                if self.calls == 1:
                    return {"content": "", "tool_calls": []}
                return {"content": "最终回答", "tool_calls": []}

        class Registry:
            def get_schemas(self):
                return None

            def get_danger_level(self, name, arguments):
                return "safe"

        core = AgentCore.__new__(AgentCore)
        core.config = {"context_window": 200000, "provider_id": "custom"}
        core.provider = EmptyThenFinalProvider()
        core.tool_registry = Registry()
        core.history = [{"role": "system", "content": "system"}]
        core.conversation_id = None
        core.approval_mode = "full_access"
        core._tool_call_callback = None
        core._tool_result_callback = None
        core._approval_callback = None
        core._auto_title_if_needed = lambda: None
        core.save_conversation = lambda: None

        result = core.chat("hello")
        self.assertEqual(result["response"], "最终回答")
        self.assertEqual(core.provider.calls, 2)

    def test_tool_result_is_passed_to_next_model_round(self):
        class Registry:
            def get_schemas(self):
                return [{"type": "function", "function": {"name": "read_file"}}]

            def get_danger_level(self, name, arguments):
                return "safe"

            def execute(self, name, arguments):
                return "file-content"

        class ToolProvider:
            def __init__(self):
                self.calls = []

            def chat(self, messages, tools=None):
                self.calls.append(messages)
                if len(self.calls) == 1:
                    return {"content": "", "tool_calls": [{
                        "id": "c1", "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }]}
                return {"content": "done"}

        core = AgentCore.__new__(AgentCore)
        core.config = {"context_window": 32768, "context_reserve": 4096}
        core.provider = ToolProvider()
        core.tool_registry = Registry()
        core.history = [{"role": "system", "content": "system"}]
        core.conversation_id = None
        core.approval_mode = "full_access"
        core._tool_call_callback = None
        core._tool_result_callback = None
        core._approval_callback = None
        core._auto_title_if_needed = lambda: None
        core.save_conversation = lambda: None

        result = core.chat("read it")
        self.assertEqual(result["response"], "done")
        second_round = core.provider.calls[1]
        self.assertTrue(any(m.get("role") == "tool" and m.get("content") == "file-content" for m in second_round))
if __name__ == "__main__":
    unittest.main()