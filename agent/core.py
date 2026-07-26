"""MollyPaw Agent Core - Main agent logic."""
from agent.providers.openai_provider import OpenAIProvider


class AgentCore:
    """Core agent that manages chat, history, and provider interaction."""

    DEFAULT_CONFIG = {
        "api_key": "",
        "model": "gpt-3.5-turbo",
        "base_url": "https://api.openai.com/v1",
        "temperature": 0.7,
        "max_tokens": 2048,
    }

    def __init__(self):
        self.history = []
        self.config = self._load_config()
        self.provider = self._create_provider()

    def _load_config(self) -> dict:
        """Load config from file, falling back to defaults."""
        import os
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
        config = dict(self.DEFAULT_CONFIG)
        if os.path.exists(config_path):
            try:
                import json
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
        import os, json
        # Update config
        for k, v in new_config.items():
            if k in self.DEFAULT_CONFIG:
                self.config[k] = v
        # Save to file
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
        # Refresh provider
        self.provider = self._create_provider()

    def chat(self, user_message: str) -> str:
        """Send a message and get a response."""
        self.history.append({"role": "user", "content": user_message})
        response = self.provider.chat(self.history)
        self.history.append({"role": "assistant", "content": response})
        return response

    def clear_history(self):
        """Clear chat history."""
        self.history.clear()
