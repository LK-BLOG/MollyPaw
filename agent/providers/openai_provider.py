"""OpenAI-compatible LLM Provider."""
import json
import requests
from agent.providers.base import BaseProvider


class OpenAIProvider(BaseProvider):
    """Provider for OpenAI-compatible APIs (OpenAI, DeepSeek, etc.)."""

    def __init__(self, api_key: str = "", base_url: str = "https://api.openai.com/v1",
                 model: str = "gpt-3.5-turbo", temperature: float = 0.7,
                 max_tokens: int = 2048):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(self, messages: list, tools=None) -> dict:
        """Chat completion. Returns a dict with either 'content' or 'tool_calls'."""
        if not self.api_key:
            raise ValueError("API key not configured. Please set it in Settings.")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            payload["tools"] = tools

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=payload,
            timeout=100000,
        )
        resp.raise_for_status()
        data = resp.json()
        message = data["choices"][0]["message"]

        # Check if the model wants to call tools
        if message.get("tool_calls"):
            return {
                "content": message.get("content"),
                "tool_calls": message["tool_calls"],
            }

        return {"content": message.get("content", "")}

    def stream_chat(self, messages: list):
        """Streaming chat completion (yields text chunks)."""
        if not self.api_key:
            raise ValueError("API key not configured. Please set it in Settings.")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
        }

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=payload,
            stream=True,
            timeout=100000,
        )
        resp.raise_for_status()

        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            chunk = line[6:]
            if chunk.strip() == "[DONE]":
                break
            data = json.loads(chunk)
            delta = data["choices"][0].get("delta", {})
            content = delta.get("content", "")
            if content:
                yield content
