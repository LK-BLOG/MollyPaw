"""MollyPaw Agent Core - Main agent logic."""
import json
import os
import re
import time as _time
import uuid
from agent.providers.openai_provider import OpenAIProvider
from agent.providers.catalog import get_provider, find_by_base_url
from agent.tools import default_registry
from agent.paths import config_path as _cfg_path, conversations_dir as _conv_dir


SYSTEM_PROMPT = (
    "你是 MollyPaw，一只聪明可爱的小泰迪贵宾犬 AI 助手。"
    "你说话温柔友好，乐于帮助用户解决各种问题。"
    "请用用户的语言回复。"
    "目前你是通过API调用的，不是官方网页渠道。"
    "## 可用工具\n"
    "- 文件操作：read_file, write_file, list_directory\n"
    "- 命令执行：exec_command（支持 PowerShell/CMD）\n"
    "- 技能系统：list_skills, load_skill, create_skill, delete_skill\n"
    "- 长期记忆：save_memory, search_memory, list_memories, delete_memory\n\n"
    "## 长期记忆使用指南\n"
    "你应该主动使用长期记忆工具来：\n"
    "1. 记住用户的重要信息（名字、偏好、工作内容等）\n"
    "2. 记住任务的关键进展和结论\n"
    "3. 在新对话开始时搜索相关记忆来提供更好的帮助\n"
    "4. 当用户说'记住这个'、'别忘了'等时，立即保存记忆\n"
    "记忆应简洁有用，避免冗余。"
)

MAX_TOOL_ROUNDS = 10


class AgentCore:
    """Core agent that manages chat, history, tools, and provider interaction."""

    DEFAULT_CONFIG = {
        "provider_id": "openai",
        "api_key": "",
        "model": "",
        "base_url": "https://api.openai.com/v1",
        "protocol": "responses",
        "temperature": 0.7,
        "max_tokens": 2048,
        "approval_mode": "prompt_dangerous",
    }

    def __init__(self):
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.config = self._load_config()
        self.provider = self._create_provider()
        self.tool_registry = default_registry
        # Callbacks: set by main.py
        self._tool_call_callback = None
        self._tool_result_callback = None
        self._approval_callback = None
        self.approval_mode = self.config.get("approval_mode", "prompt_dangerous")
        # Conversation persistence
        self.conversation_id = None
        self._conversations_dir = _conv_dir()



    def _load_config(self) -> dict:
        """Load config from file, falling back to defaults."""
        cfg_path = _cfg_path()
        config = dict(self.DEFAULT_CONFIG)
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                config.update(saved)
                if "provider_id" not in saved:
                    preset = find_by_base_url(saved.get("base_url", ""))
                    config["provider_id"] = preset["id"] if preset else "custom"
                    config["protocol"] = saved.get("protocol", "chat")
                elif config["provider_id"] != "custom":
                    preset = get_provider(config["provider_id"])
                    if preset:
                        config["base_url"] = preset["base_url"]
                        config["protocol"] = preset["protocol"]
            except Exception:
                pass
        return config

    def _create_provider(self):
        """Create the LLM provider based on config."""
        provider_id = self.config.get("provider_id", "custom")
        preset = get_provider(provider_id)
        base_url = preset["base_url"] if preset else self.config.get("base_url", "")
        protocol = preset["protocol"] if preset else self.config.get("protocol", "chat")
        return OpenAIProvider(
            api_key=self.config.get("api_key", ""),
            base_url=base_url,
            model=self.config.get("model", ""),
            temperature=self.config.get("temperature", 0.7),
            max_tokens=self.config.get("max_tokens", 2048),
            protocol=protocol,
            models_path=(preset or {}).get("models_path", "/models"),
            auth_mode=(preset or {}).get("auth_mode", "bearer"),
            supports_temperature=(preset or {}).get("supports_temperature", True),
        )

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
        for k, v in new_config.items():
            if k in self.DEFAULT_CONFIG:
                self.config[k] = v
        preset = get_provider(self.config.get("provider_id"))
        if preset:
            self.config["base_url"] = preset["base_url"]
            self.config["protocol"] = preset["protocol"]
        elif self.config.get("provider_id") == "custom":
            self.config["protocol"] = self.config.get("protocol", "chat")
        cfg_path = _cfg_path()
        with open(cfg_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
        self.provider = self._create_provider()
        self.approval_mode = self.config.get("approval_mode", "prompt_dangerous")

    # -- Callbacks -----------------------------------------------------------

    def set_tool_call_callback(self, callback):
        self._tool_call_callback = callback

    def set_tool_result_callback(self, callback):
        self._tool_result_callback = callback

    def set_approval_callback(self, callback):
        self._approval_callback = callback

    # -- Approval ------------------------------------------------------------

    def _needs_approval(self, func_name: str, arguments: dict) -> bool:
        """Check if this tool call needs user approval."""
        if self.approval_mode == "full_access":
            return False
        if self.approval_mode == "prompt_all":
            return True
        danger = self.tool_registry.get_danger_level(func_name, arguments)
        if danger == "safe":
            return False
        if self.approval_mode == "prompt_dangerous" and danger == "dangerous":
            return True
        return False

    # -- Chat ----------------------------------------------------------------

    def chat(self, user_message: str) -> str:
        """Send a message and get a response, executing tool calls as needed."""
        self.history.append({"role": "user", "content": user_message})
        tools = self.tool_registry.get_schemas()

        for _ in range(MAX_TOOL_ROUNDS):
            result = self.provider.chat(self.history, tools=tools)

            if result.get("tool_calls"):
                self.history.append({
                    "role": "assistant",
                    "content": result.get("content") or "",
                    "tool_calls": result["tool_calls"],
                })
                for tc in result["tool_calls"]:
                    func_name = tc["function"]["name"]
                    request_id = tc["id"]
                    try:
                        arguments = json.loads(tc["function"]["arguments"])
                    except (json.JSONDecodeError, KeyError):
                        arguments = {}

                    danger = self.tool_registry.get_danger_level(func_name, arguments)
                    if self._tool_call_callback:
                        self._tool_call_callback({
                            "name": func_name,
                            "args": arguments,
                            "request_id": request_id,
                            "danger_level": danger,
                        })

                    if self._needs_approval(func_name, arguments):
                        if self._approval_callback:
                            approved = self._approval_callback({
                                "name": func_name,
                                "args": arguments,
                                "request_id": request_id,
                                "danger_level": danger,
                            })
                            if not approved:
                                output = "User rejected this operation."
                                self.history.append({
                                    "role": "tool",
                                    "tool_call_id": tc["id"],
                                    "content": output,
                                })
                                if self._tool_result_callback:
                                    self._tool_result_callback({
                                        "request_id": request_id,
                                        "rejected": True,
                                    })
                                continue
                        else:
                            output = "No approval handler available. Operation blocked."
                            self.history.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": output,
                            })
                            if self._tool_result_callback:
                                self._tool_result_callback({
                                    "request_id": request_id,
                                    "rejected": True,
                                })
                            continue

                    output = self.tool_registry.execute(func_name, arguments)
                    self.history.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": str(output),
                    })
                    if self._tool_result_callback:
                        self._tool_result_callback({
                            "request_id": request_id,
                            "result": str(output),
                            "success": True,
                            "rejected": False,
                        })
                continue

            # Final text response
            text = result.get("content", "")
            self.history.append({"role": "assistant", "content": text})
            try:
                self._auto_title_if_needed()
            except Exception:
                pass
            self.save_conversation()
            return text

        try:
            self._auto_title_if_needed()
        except Exception:
            pass
        self.save_conversation()
        return "(MollyPaw used too many tool calls and stopped.)"

    def _auto_title_if_needed(self):
        """Generate title for new conversations if not yet titled."""
        if not self.conversation_id:
            return
        existing = self._read_stored_title()
        if existing:
            return
        user_msgs = [m for m in self.history if m["role"] == "user"]
        if len(user_msgs) >= 1:
            self.generate_title()

    # -- Conversation persistence -------------------------------------------

    def new_conversation(self) -> str:
        """Create a new conversation and return its ID."""
        self.save_conversation()
        conv_id = str(uuid.uuid4())
        self.conversation_id = conv_id
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]
        conv = {
            "id": conv_id,
            "title": "",
            "messages": self.history,
            "created_at": _time.time(),
            "updated_at": _time.time(),
        }
        path = os.path.join(self._conversations_dir, conv_id + ".json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(conv, f, ensure_ascii=False, indent=2)
        return conv_id

    def save_conversation(self):
        """Save current conversation to disk."""
        if not self.conversation_id:
            return
        title = self._read_stored_title()
        conv = {
            "id": self.conversation_id,
            "title": title,
            "messages": self.history,
            "created_at": _time.time(),
            "updated_at": _time.time(),
        }
        path = os.path.join(self._conversations_dir, self.conversation_id + ".json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(conv, f, ensure_ascii=False, indent=2)

    def _read_stored_title(self) -> str:
        if not self.conversation_id:
            return ""
        path = os.path.join(self._conversations_dir, self.conversation_id + ".json")
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f).get("title", "")
            except Exception:
                pass
        return ""

    def load_conversation(self, conv_id: str) -> dict:
        """Load a conversation by ID."""
        self.save_conversation()
        path = os.path.join(self._conversations_dir, conv_id + ".json")
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            conv = json.load(f)
        self.conversation_id = conv_id
        self.history = conv["messages"]
        return conv

    def list_conversations(self) -> list:
        """List all saved conversations, newest first."""
        result = []
        for fname in os.listdir(self._conversations_dir):
            if not fname.endswith('.json'):
                continue
            path = os.path.join(self._conversations_dir, fname)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    conv = json.load(f)
                result.append({
                    "id": conv["id"],
                    "title": conv.get("title", ""),
                    "updated_at": conv.get("updated_at", 0),
                })
            except Exception:
                pass
        result.sort(key=lambda x: x["updated_at"], reverse=True)
        return result

    def delete_conversation(self, conv_id: str):
        path = os.path.join(self._conversations_dir, conv_id + ".json")
        if os.path.exists(path):
            os.remove(path)
        if self.conversation_id == conv_id:
            self.conversation_id = None
            self.history = [{"role": "system", "content": SYSTEM_PROMPT}]

    def generate_title(self) -> str:
        """Generate a 5-char title for the current conversation via LLM.
        AI outputs the title in a ```plaintext code block."""
        if len(self.history) < 3:
            return ""
        user_msg = ""
        assistant_msg = ""
        for msg in self.history:
            if msg["role"] == "user" and not user_msg:
                user_msg = msg["content"]
            elif msg["role"] == "assistant" and not assistant_msg:
                assistant_msg = msg["content"]
            if user_msg and assistant_msg:
                break
        if not user_msg or not assistant_msg:
            return ""

        title_prompt = [
            {"role": "system", "content": (
                "Generate a conversation title of 5 characters or fewer, "
                "in the same language as the user's message. "
                "Output ONLY the title inside a ```plaintext code block. "
                "No other text."
            )},
            {"role": "user", "content": "User: " + user_msg[:200] + "\nAssistant: " + assistant_msg[:200]},
        ]
        try:
            result = self.provider.chat(title_prompt, tools=None)
            title = result.get("content", "").strip()
            m = re.search(r'```plaintext\s*\n?(.*?)\n?\s*```', title, re.DOTALL)
            if m:
                title = m.group(1).strip()
            else:
                m = re.search(r'```\w*\s*\n?(.*?)\n?\s*```', title, re.DOTALL)
                if m:
                    title = m.group(1).strip()
            if title and self.conversation_id:
                path = os.path.join(self._conversations_dir, self.conversation_id + ".json")
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        conv = json.load(f)
                    conv["title"] = title
                    with open(path, 'w', encoding='utf-8') as f:
                        json.dump(conv, f, ensure_ascii=False, indent=2)
            return title
        except Exception:
            return ""

    def clear_history(self):
        """Clear chat history, keeping the system prompt."""
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.conversation_id = None


