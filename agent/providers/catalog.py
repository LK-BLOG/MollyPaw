"""Built-in provider presets for OpenAI-compatible APIs."""

PROVIDERS = [
    {"id": "openai", "display_name": "OpenAI", "base_url": "https://api.openai.com/v1", "protocol": "responses", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "deepseek", "display_name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "protocol": "responses", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "mimo", "display_name": "Xiaomi MiMo", "base_url": "https://api.xiaomimimo.com/v1", "protocol": "responses", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "doubao", "display_name": "豆包 / 火山方舟", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "kimi", "display_name": "Kimi / Moonshot", "base_url": "https://api.moonshot.cn/v1", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": False},
    {"id": "qwen", "display_name": "Qwen / DashScope", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "glm", "display_name": "GLM / 智谱", "base_url": "https://open.bigmodel.cn/api/paas/v4", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "minimax", "display_name": "MiniMax", "base_url": "https://api.minimax.io/v1", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "gemini", "display_name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "openrouter", "display_name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "siliconflow", "display_name": "SiliconFlow", "base_url": "https://api.siliconflow.cn/v1", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "xai", "display_name": "xAI", "base_url": "https://api.x.ai/v1", "protocol": "responses", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "mistral", "display_name": "Mistral", "base_url": "https://api.mistral.ai/v1", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "groq", "display_name": "Groq", "base_url": "https://api.groq.com/openai/v1", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "together", "display_name": "Together AI", "base_url": "https://api.together.xyz/v1", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "fireworks", "display_name": "Fireworks AI", "base_url": "https://api.fireworks.ai/inference/v1", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "cerebras", "display_name": "Cerebras", "base_url": "https://api.cerebras.ai/v1", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "nvidia", "display_name": "NVIDIA NIM", "base_url": "https://integrate.api.nvidia.com/v1", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "deepinfra", "display_name": "DeepInfra", "base_url": "https://api.deepinfra.com/v1/openai", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
    {"id": "perplexity", "display_name": "Perplexity", "base_url": "https://api.perplexity.ai", "protocol": "chat", "models_path": "/models", "auth_mode": "bearer", "supports_temperature": True},
]

PROVIDER_MAP = {item["id"]: item for item in PROVIDERS}

def get_provider(provider_id):
    return PROVIDER_MAP.get(provider_id)

def public_providers():
    return [{k: v for k, v in item.items() if k != "auth_mode"} for item in PROVIDERS] + [{"id": "custom", "display_name": "Custom", "base_url": "", "protocol": "chat", "models_path": "/models", "supports_temperature": True}]

def find_by_base_url(base_url):
    value = (base_url or "").rstrip("/")
    for item in PROVIDERS:
        if value == item["base_url"].rstrip("/"):
            return item
    return None
