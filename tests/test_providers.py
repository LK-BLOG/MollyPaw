import json
import unittest
from unittest.mock import Mock, patch

from agent.providers.openai_provider import OpenAIProvider


class ProviderTests(unittest.TestCase):
    def response(self, data):
        response = Mock()
        response.json.return_value = data
        response.raise_for_status.return_value = None
        return response

    @patch("agent.providers.openai_provider.requests.post")
    def test_responses_text_and_tool_call(self, post):
        post.return_value = self.response({
            "output_text": "ok",
            "output": [{"type": "function_call", "call_id": "c1", "name": "read_file", "arguments": "{}"}],
        })
        provider = OpenAIProvider("key", "https://example/v1", "model", protocol="responses")
        result = provider.chat([{"role": "user", "content": "hi"}], tools=[])
        self.assertEqual(result["content"], "ok")
        self.assertEqual(result["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(post.call_args.args[0], "https://example/v1/responses")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["max_output_tokens"], 2048)
        self.assertEqual(payload["input"][0]["role"], "user")

    @patch("agent.providers.openai_provider.requests.post")
    def test_kimi_omits_temperature(self, post):
        post.return_value = self.response({"choices": [{"message": {"content": "ok"}}]})
        provider = OpenAIProvider("key", "https://example/v1", "model", supports_temperature=False)
        provider.chat([], tools=None)
        self.assertNotIn("temperature", post.call_args.kwargs["json"])

    @patch("agent.providers.openai_provider.requests.post")
    def test_chat_returns_usage_and_explicit_cost(self, post):
        post.return_value = self.response({
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0012},
        })
        provider = OpenAIProvider("key", "https://example/v1", "model")
        result = provider.chat([{"role": "user", "content": "hi"}], tools=None)
        self.assertEqual(result["usage"]["prompt_tokens"], 10)
        self.assertEqual(result["cost"], 0.0012)

    @patch("agent.providers.openai_provider.requests.post")
    def test_reasoning_level_is_mapped(self, post):
        post.return_value = self.response({"choices": [{"message": {"content": "ok"}}]})
        provider = OpenAIProvider("key", "https://example/v1", "model",
                                  thinking_level="max", thinking_mode="openai")
        provider.chat([], tools=None)
        self.assertEqual(post.call_args.kwargs["json"]["reasoning_effort"], "high")

    @patch("agent.providers.openai_provider.requests.post")
    def test_deepseek_thinking_passes_reasoning_content(self, post):
        post.return_value = self.response({
            "choices": [{"message": {"content": "final", "reasoning_content": "thought"}}],
            "usage": {},
        })
        provider = OpenAIProvider("key", "https://api.deepseek.com/v1", "deepseek-flash",
                                  thinking_level="low", thinking_mode="deepseek")
        result = provider.chat([
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "read_file", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        ], tools=None)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["messages"][0]["reasoning_content"], "")
        self.assertEqual(result["reasoning_content"], "thought")

    @patch("agent.providers.openai_provider.requests.get")
    def test_deepseek_balance(self, get):
        response = self.response({
            "is_available": True,
            "balance_infos": [
                {"currency": "USD", "total_balance": "1.23"},
                {"currency": "CNY", "total_balance": "12.34"},
            ],
        })
        response.status_code = 200
        get.return_value = response
        provider = OpenAIProvider("key", "https://api.deepseek.com/v1", "deepseek-chat")
        result = provider.get_balance("/user/balance", "deepseek", "https://api.deepseek.com")
        self.assertTrue(result["supported"])
        self.assertEqual(result["balance"], "1.23")
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(len(result["balances"]), 2)
        self.assertEqual(result["balances"][1]["currency"], "CNY")
        self.assertEqual(get.call_args.args[0], "https://api.deepseek.com/user/balance")
    @patch("agent.providers.openai_provider.requests.get")
    def test_list_models(self, get):
        get.return_value = self.response({"data": [{"id": "qwen-2.5"}, {"id": "gpt-5"}]})
        provider = OpenAIProvider("key", "https://example/v1")
        self.assertEqual(provider.list_models(), ["qwen-2.5", "gpt-5"])
        self.assertEqual(get.call_args.args[0], "https://example/v1/models")


if __name__ == "__main__":
    unittest.main()
