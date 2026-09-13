"""OpenAI-compatible Chat Completions and Responses provider."""
import json
import requests
from agent.providers.base import BaseProvider


class OpenAIProvider(BaseProvider):
    def __init__(self, api_key="", base_url="https://api.openai.com/v1", model="",
                 temperature=0.7, max_tokens=2048, protocol="chat",
                 models_path="/models", auth_mode="bearer",
                 supports_temperature=True):
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.protocol = protocol if protocol in ("chat", "responses") else "chat"
        self.models_path = models_path or "/models"
        self.auth_mode = auth_mode or "bearer"
        self.supports_temperature = supports_temperature

    def _headers(self):
        header = "api-key" if self.auth_mode == "api_key" else "Authorization"
        value = self.api_key if header == "api-key" else f"Bearer {self.api_key}"
        return {header: value, "Content-Type": "application/json"}

    def _url(self, path):
        return f"{self.base_url}/{path.lstrip('/')}"

    @staticmethod
    def _response_tools(tools):
        result = []
        for tool in tools or []:
            fn = tool.get("function", tool)
            result.append({
                "type": "function",
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return result

    @staticmethod
    def _response_input(messages):
        result = []
        for message in messages:
            role = message.get("role")
            if role in ("system", "user"):
                result.append({"role": role, "content": message.get("content", "")})
            elif role == "assistant":
                content = message.get("content") or ""
                if content:
                    result.append({"role": "assistant", "content": content})
                for call in message.get("tool_calls", []):
                    fn = call.get("function", {})
                    result.append({"type": "function_call", "call_id": call.get("id", ""),
                                   "name": fn.get("name", ""), "arguments": fn.get("arguments", "{}")})
            elif role == "tool":
                result.append({"type": "function_call_output",
                               "call_id": message.get("tool_call_id", ""),
                               "output": str(message.get("content", ""))})
        return result

    @staticmethod
    def _extract_text(data):
        if data.get("output_text"):
            return data["output_text"]
        chunks = []
        for item in data.get("output", []):
            for content in item.get("content", []) or []:
                if content.get("type") in ("output_text", "text") and content.get("text"):
                    chunks.append(content["text"])
        return "".join(chunks)

    @staticmethod
    def _extract_tool_calls(data):
        calls = []
        for item in data.get("output", []):
            if item.get("type") != "function_call":
                continue
            calls.append({"id": item.get("call_id") or item.get("id", ""),
                          "type": "function",
                          "function": {"name": item.get("name", ""),
                                       "arguments": item.get("arguments", "{}")} })
        return calls

    def chat(self, messages, tools=None):
        if not self.api_key:
            raise ValueError("API key not configured. Please set it in Settings.")
        if not self.model:
            raise ValueError("Model not configured. Please select or enter a model in Settings.")
        if self.protocol == "responses":
            payload = {"model": self.model, "input": self._response_input(messages),
                       "max_output_tokens": self.max_tokens}
            if tools:
                payload["tools"] = self._response_tools(tools)
            if self.supports_temperature:
                payload["temperature"] = self.temperature
            data = self._post("/responses", payload).json()
            calls = self._extract_tool_calls(data)
            result = {"content": self._extract_text(data)}
            if calls:
                result["tool_calls"] = calls
            return result

        payload = {"model": self.model, "messages": messages, "max_tokens": self.max_tokens}
        if self.supports_temperature:
            payload["temperature"] = self.temperature
        if tools:
            payload["tools"] = tools
        message = self._post("/chat/completions", payload).json()["choices"][0]["message"]
        result = {"content": message.get("content", "")}
        if message.get("tool_calls"):
            result["tool_calls"] = message["tool_calls"]
        return result

    def list_models(self):
        if not self.api_key:
            raise ValueError("API key not configured. Please enter an API key first.")
        response = requests.get(self._url(self.models_path), headers=self._headers(), timeout=30)
        response.raise_for_status()
        data = response.json()
        raw = data.get("data", data.get("models", data)) if isinstance(data, dict) else data
        if not isinstance(raw, list):
            raise ValueError("Model list response has an unsupported format.")
        models = []
        for item in raw:
            model_id = item if isinstance(item, str) else item.get("id")
            if model_id:
                models.append(str(model_id))
        return models

    def _post(self, path, payload):
        response = requests.post(self._url(path), headers=self._headers(), json=payload, timeout=100000)
        response.raise_for_status()
        return response

    def stream_chat(self, messages):
        raise NotImplementedError("Streaming is not enabled for this provider yet.")
