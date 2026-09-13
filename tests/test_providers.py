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

    @patch("agent.providers.openai_provider.requests.get")
    def test_list_models(self, get):
        get.return_value = self.response({"data": [{"id": "qwen-2.5"}, {"id": "gpt-5"}]})
        provider = OpenAIProvider("key", "https://example/v1")
        self.assertEqual(provider.list_models(), ["qwen-2.5", "gpt-5"])
        self.assertEqual(get.call_args.args[0], "https://example/v1/models")


if __name__ == "__main__":
    unittest.main()
