"""MollyPaw Agent Core - Main agent logic."""
import json
from agent.providers.openai_provider import OpenAIProvider
from agent.tools import default_registry


SYSTEM_PROMPT = (
    "你是 MollyPaw，一只聪明可爱的小泰迪贵宾犬 AI 助手。"
    "你说话温柔友好，乐于帮助用户解决各种问题。"
    "当用户需要读取文件、写入文件或浏览目录时，你会主动使用提供的工具来完成任务，"
    "而不是只给出文字说明。请用用户的语言回复。"
    "目前你是通过API调用的，不是官方网页渠道。"
)

MAX_TOOL_ROUNDS = 10


class AgentCore:
    """Core agent that manages chat, history, tools, and provider interaction."""

    DEFAULT_CONFIG = {
        "api_key": "",
        "model": "gpt-3.5-turbo",
        "base_url": "https://api.openai.com/v1",
        "temperature": 0.7,
        "max_tokens": 2048,
    }

    def __init__(self):
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.config = self._load_config()
        self.provider = self._create_provider()
        self.tool_registry = default_registry

    def _load_config(self) -> dict:
        """Load config from file, falling back to defaults."""
        import os
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
        config = dict(self.DEFAULT_CONFIG)
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                config.update(saved)
            except Exception:
                pass
        return config

    def _create_provider(self):
        """Create the LLM provider based on config."""
        api_key = self.config.get("api_key", "")
        base_url = self.config.get("base_url", "")
        model = self.config.get("model", "gpt-3.5-turbo")
        return OpenAIProvider(api_key=api_key, base_url=base_url, model=model)

    def get_config(self) -> dict:
        """Return config with api_key masked for display."""
        display = dict(self.config)
        key = display.get("api_key", "")
        if key:
            display["api_key_set"] = True
            display["api_key"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        else:
            display["api_key_set"] = False
            display["api_key"] = ""
        return display

    def save_config(self, new_config: dict):
        """Save new configuration and refresh provider."""
        import os
        for k, v in new_config.items():
            if k in self.DEFAULT_CONFIG:
                self.config[k] = v
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
        self.provider = self._create_provider()

    def chat(self, user_message: str) -> str:
        """Send a message and get a response, executing tool calls as needed."""
        self.history.append({"role": "user", "content": user_message})
        tools = self.tool_registry.get_schemas()

        for _ in range(MAX_TOOL_ROUNDS):
            result = self.provider.chat(self.history, tools=tools)

            if result.get("tool_calls"):
                # Record assistant turn with tool_calls (content may be None)
                self.history.append({
                    "role": "assistant",
                    "content": result.get("content") or "",
                    "tool_calls": result["tool_calls"],
                })
                # Execute every tool call and append results
                for tc in result["tool_calls"]:
                    func_name = tc["function"]["name"]
                    try:
                        arguments = json.loads(tc["function"]["arguments"])
                    except (json.JSONDecodeError, KeyError):
                        arguments = {}
                    output = self.tool_registry.execute(func_name, arguments)
                    self.history.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": str(output),
                    })
                # Loop again so the LLM can see tool results
                continue

            # No tool calls — this is the final text response
            text = result.get("content", "")
            self.history.append({"role": "assistant", "content": text})
            return text

        # Safety fallback if we exhaust tool rounds
        return "(MollyPaw used too many tool calls and stopped.)"

    def clear_history(self):
        """Clear chat history, keeping the system prompt."""
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]
