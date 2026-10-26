"""MollyPaw sleep consolidation cycle."""
import json
import os
import re
import threading
import time
from datetime import datetime

from agent.paths import data_dir, conversations_dir
from agent.tools.file_tool import FileTool
from agent.tools.memory_tool import MemoryTool
from agent.tools.registry import ToolRegistry


SLEEP_PROMPT = """【角色】
你现在运行在 MollyPaw 的「睡眠整理」后台任务中。用户不在场，没有人在等你回话。
你的输出不会被直接展示给用户，因此不要寒暄、不要提问、不要请求确认、不要输出给人看的说明文字。
你唯一的产出方式：调用工具写入结果。

【输入】
以下是本段时间内需要整理的对话记录：
--- BEGIN TRANSCRIPT ---
{{TRANSCRIPT}}
--- END TRANSCRIPT ---

【你要做的事，按顺序执行】

1. 记忆整理（调用 save_memory）
   - 抽取「未来仍然有用」的信息：用户的身份、偏好、长期目标、明确的纠正与要求、重要结论、进行中的任务。
   - 每条记忆只表达一件事，写成陈述句，尽量简短（建议 ≤ 100 字）。
   - 只写对话里真实出现过的事实。不确定、推测、临时情绪、闲聊，一律不写。
   - 同一信息如果已存在，不要重复保存；若内容有更新，保存一条更准确的新版本。
   - 分类使用：info（事实）/ preference（偏好与要求）/ task（任务与进展）/ note（其他）。
   - 标签 2~5 个，逗号分隔，用简短英文或中文关键词。

2. 对话梳理（不写文件，只做判断）
   - 判断本段对话属于：新话题 / 进行中的任务 / 已完结。
   - 若发现对话里存在未完成的事项，将其作为一条 category="task" 的记忆保存，注明「待办」。
   - 若发现用户对某些内容表达过否认、纠正或拒绝，必须原样保留该事实，不得美化、不得省略。

【硬性禁止】
- 禁止编造任何未在对话中出现的信息。
- 禁止保存敏感凭据：API Key、密码、token、私钥、身份证号、银行卡号等。若对话中出现，一律跳过。
- 禁止把「你自己的身份设定」当作事实保存。
- 禁止输出 JSON 之外的自由文本解释（工具调用结果除外）。

【结束条件】
完成上述步骤后，调用一次工具输出结束信号：save_memory(
  content="睡眠整理完成：新增 N 条记忆，跳过 M 条敏感内容。",
  tags="sleep,log", category="note"
)
只有这一次输出是给系统做日志用的，仍需保持简短、不得包含敏感信息。
"""

DREAM_PROMPT = """【角色】
你正在为一只有点笨拙、很粘人、用四条腿走路的小泰迪 —— MollyPaw —— 写一个「梦」。
这是纯创作任务，与用户的真实经历无关。

【输入】
- 本段时间的对话主题（必须作为梦的核心灵感，提炼主题、情绪、人物关系、任务进展和技术概念；不可照抄原句，不可泄露隐私）：
{{TRANSCRIPT_SUMMARY}}
- 近期保存的记忆摘要（仅作氛围参考）：
{{MEMORY_DIGEST}}

【创作前工具步骤】
1. 调用 list_memories(limit=20)，查看近期记忆，选出与对话主题相关的 2~5 个元素。
2. 调用 list_directory("{{DREAM_DIR}}")；如果存在最近的梦，调用 read_file 读取最近一个，避免重复意象和重复情节。
3. 完成检索后再构思并调用 write_file 保存。

【产物要求】
1. 写一篇完整但简短的梦境片段，500~800 字，中文。
2. 以泰迪的第一人称或第三人称视角皆可，语气温柔、直白，带一点笨拙的可爱。
   不要写成散文诗，不要文学腔，不要堆砌比喻和形容词，按普通故事的方式写清楚经过。
3. 梦的意象倾向于：暖色调、骨头、沙发、爪印、雪、纸箱、窗外、数据流变成的小河等。
   避免恐怖、暴力、色情、负面暗示内容。
4. 不得出现真实人物的隐私信息（姓名、地址、账号、聊天原文）。
5. 不得写成「我昨晚真的梦到了……」这种声称真实经历的口气。
   必须让读者明确知道这是被创作出来的虚构内容。

【输出格式】
把结果保存为文件 {{DREAM_PATH}}，文件名格式为 dream_年份_月份_日期_第几个梦.md，文件内容格式严格如下：

---
title: 泰迪的一夜
date: {{DATE}}
type: generated-dream
notice: 本节为 AI 生成的虚构创作，并非真实经历，请勿当作事实引用。
---

（正文）

【硬性禁止】
- 禁止把梦中内容写入长期记忆。
- 禁止在梦的正文中使用第一人称向用户喊话（如「主人我今天梦到」）。
- 禁止引用或泄露任何敏感凭据。
"""


class _SleepFileTool(FileTool):
    """File tool restricted to the sleep data directory."""

    def __init__(self, root):
        self.root = os.path.abspath(root)

    def write_file(self, path, content):
        target = os.path.abspath(path)
        try:
            if os.path.commonpath([target, self.root]) != self.root:
                return "Error: sleep may only write files under data/dreams."
        except ValueError:
            return "Error: sleep may only write files under data/dreams."
        return super().write_file(target, content)


class SleepExecutor:
    """跑「提示词 → 模型 → 工具 → 回到模型」这一圈。

    单独拆出来是为了能测：这里最容易出的错是「没有中断能力」和
    「工具白名单没生效」，两者都不该埋在 400 行的 SleepCycle 里。

    和 AgentCore 的区别：
      - 没有历史，每次从一条 system 提示词开始（睡眠任务是独立的一次性工作）；
      - **没有轮数上限**（用户明确要求把睡眠的调用上限也删掉，活才干得完），
        退出只靠：模型不再调工具 / 被中断 / 抛异常；
      - 每次模型调用都带 CancelToken，用户一有动作就能立刻掐断。
    """

    def __init__(self, provider, logger, registry_factory,
                 is_sensitive, is_safe_write_path):
        self.provider = provider
        self.logger = logger
        self._registry_factory = registry_factory
        self._is_sensitive = is_sensitive
        self._is_safe_write_path = is_safe_write_path

    def run(self, prompt, allowed_tools, is_interrupted,
            register_token=None, write_root=None, write_path=None):
        from agent.cancel import CancelledError, CancelToken

        registry, schemas = self._registry_factory(allowed_tools)
        messages = [{"role": "system", "content": prompt}]

        def _publish(token):
            if register_token:
                try:
                    register_token(token)
                except Exception:
                    pass

        while True:
            if is_interrupted():
                return False
            token = CancelToken()
            _publish(token)
            try:
                result = self._chat(messages, schemas, token)
            except CancelledError:
                return False
            finally:
                _publish(None)

            calls = result.get("tool_calls") or []
            if not calls:
                return True

            messages.append({
                "role": "assistant",
                "content": result.get("content") or "",
                "tool_calls": calls,
            })
            for call in calls:
                if is_interrupted():
                    return False
                fn = call.get("function", {})
                name = fn.get("name", "")
                call_id = call.get("id", "")
                self.logger("工具调用: " + str(name))
                try:
                    arguments = json.loads(fn.get("arguments") or "{}")
                except (TypeError, json.JSONDecodeError):
                    arguments = {}
                output = self._invoke(
                    registry, allowed_tools, name, arguments, write_root, write_path)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": output,
                })

    def _chat(self, messages, schemas, token):
        """调一次模型。provider 不支持 cancel 时退回普通调用（老测试桩）。"""
        try:
            return self.provider.chat(messages, tools=schemas, cancel=token)
        except TypeError as exc:
            if "cancel" not in str(exc):
                raise
            token.raise_if_cancelled()
            return self.provider.chat(messages, tools=schemas)

    def _invoke(self, registry, allowed_tools, name, arguments,
                write_root, write_path):
        if name not in allowed_tools:
            return "Error: tool is not allowed during sleep."
        if name == "save_memory" and self._is_sensitive(arguments.get("content", "")):
            return "Error: sensitive content skipped."
        if name == "write_file":
            path = str(arguments.get("path") or "")
            content = str(arguments.get("content") or "")
            if write_path and os.path.abspath(path) != os.path.abspath(write_path):
                return "Error: use the exact dream path: " + str(write_path)
            if write_root and not self._is_safe_write_path(path, write_root):
                return "Error: sleep may only write dream files under data/dreams."
            if self._is_sensitive(content):
                return "Error: sensitive content skipped."
        return str(registry.execute(name, arguments))


class SleepCycle:
    """空闲进入「睡眠整理」的后台任务。

    修过的坑（都别再犯）：
      1. **空闲时间以前是硬编码 30 秒，而且把用户配置直接覆盖掉**。
         `_normalize_config` 里写死 `idle_minutes = IDLE_SECONDS / 60`，
         设置里的"空闲分钟数"永远不生效 —— 用户去倒杯水回来，
         MollyPaw 已经在跑整理任务烧 token 了。现在真读配置。
      2. **LLM 调用是阻塞的，而且没法打断**。用户在整理过程中回来发消息，
         得等这次调用彻底结束（最长能卡到读超时）。现在每次调用都带
         CancelToken，用户一有动作就 close 连接立刻中断。
      3. **异常会把状态卡死在 sleeping**。整理任务抛异常后 state 停在
         "sleeping"、宠物保持"睡觉"，monitor 线程也死了 —— 看起来就是
         "宠物永久睡眠，怎么点都没反应"。现在 finally 里一定复位。
    """

    VALID_MODES = {"off", "display_only", "full"}
    TASK_ORDER = ["memory", "review", "dream"]
    MEMORY_TOOLS = {"save_memory", "search_memory", "list_memories"}
    FILE_TOOLS = {"write_file", "read_file", "list_directory"}
    MEMORY_READ_TOOLS = {"search_memory", "list_memories"}

    # 默认空闲 10 分钟才睡。太短等于用户一走神就被后台任务占着模型。
    DEFAULT_IDLE_MINUTES = 10.0
    MIN_IDLE_MINUTES = 0.5

    def __init__(self, provider, config, set_pet_state, is_busy, logger=None):
        self.provider = provider
        self.config = config
        self.set_pet_state = set_pet_state
        self.is_busy = is_busy
        self.logger = logger or (lambda message: print("[Sleep] " + message))
        self.state = "awake"
        self.last_activity = time.time()
        self._lock = threading.RLock()
        self._stop_monitor = threading.Event()
        self._interrupt = threading.Event()
        self._monitor_thread = None
        self._active_token = None   # 当前正在跑的 LLM 调用的取消令牌
        self._data_dir = data_dir()
        self._state_path = os.path.join(self._data_dir, "sleep_state.json")
        self._dreams_dir = os.path.join(self._data_dir, "dreams")
        os.makedirs(self._dreams_dir, exist_ok=True)
        self._sleep_config = self._normalize_config(config.get("sleep", {}))

    def _normalize_config(self, value):
        value = value if isinstance(value, dict) else {}
        mode = value.get("mode", "off")
        if mode not in self.VALID_MODES:
            mode = "off"
        tasks = value.get("tasks", self.TASK_ORDER)
        if not isinstance(tasks, list):
            tasks = self.TASK_ORDER
        tasks = [task for task in self.TASK_ORDER if task in tasks]
        try:
            idle_minutes = float(value.get("idle_minutes", self.DEFAULT_IDLE_MINUTES))
        except (TypeError, ValueError):
            idle_minutes = self.DEFAULT_IDLE_MINUTES
        if idle_minutes <= 0:
            idle_minutes = self.DEFAULT_IDLE_MINUTES
        idle_minutes = max(self.MIN_IDLE_MINUTES, idle_minutes)
        return {
            "mode": mode,
            "tasks": tasks,
            "idle_minutes": idle_minutes,
        }

    def reload_config(self):
        self._sleep_config = self._normalize_config(self.config.get("sleep", {}))
        if self._sleep_config["mode"] == "off":
            self.stop()
        else:
            self.start()

    def start(self):
        self._sleep_config = self._normalize_config(self.config.get("sleep", {}))
        if self._sleep_config["mode"] == "off":
            return
        with self._lock:
            if self._monitor_thread and self._monitor_thread.is_alive():
                return
            self._stop_monitor.clear()
            self.state = "awake"
            self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()

    def stop(self):
        self._stop_monitor.set()
        self._interrupt.set()
        self._cancel_active()
        with self._lock:
            self.state = "awake"
        self.set_pet_state("idle")

    def _cancel_active(self):
        """掐掉当前正在跑的 LLM 调用。

        睡眠整理的每次模型调用都挂着一个 CancelToken，close 掉连接就能
        让那次调用立刻抛 CancelledError —— 不然用户要等到读超时才拿回控制权。
        """
        token = self._active_token
        if token is not None:
            try:
                token.cancel("wake")
            except Exception:
                pass

    def mark_activity(self):
        self.last_activity = time.time()
        if self.state != "awake":
            self.wake()
        elif self._sleep_config["mode"] != "off":
            self.start()

    def wake(self):
        self.last_activity = time.time()
        self._cancel_active()
        with self._lock:
            if self.state in ("sleeping", "waking"):
                self._interrupt.set()
                self.state = "waking"
                return
            self.state = "awake"
            self._interrupt.clear()
        self.set_pet_state("idle")
        self.start()

    def get_status(self):
        return {
            "state": self.state,
            "mode": self._sleep_config["mode"],
            "tasks": list(self._sleep_config["tasks"]),
            "idle_minutes": self._sleep_config["idle_minutes"],
            "last_activity": self.last_activity,
        }

    def _monitor_loop(self):
        self.logger("monitor started")
        try:
            while not self._stop_monitor.is_set():
                self._sleep_config = self._normalize_config(self.config.get("sleep", {}))
                if self._sleep_config["mode"] == "off":
                    break
                if self.state != "awake":
                    break
                idle_seconds = self._sleep_config["idle_minutes"] * 60
                if not self.is_busy() and time.time() - self.last_activity >= idle_seconds:
                    self._enter_sleep()
                    break
                self._stop_monitor.wait(1)
        finally:
            self._monitor_thread = None
            self.logger("monitor stopped")
            if self.state == "awake" and self._sleep_config["mode"] != "off" and not self._stop_monitor.is_set():
                self.start()

    def _enter_sleep(self):
        with self._lock:
            if self.state != "awake" or self.is_busy():
                return
            self.state = "sleeping"
            self._interrupt.clear()
        self.set_pet_state("sleep")
        state = self._read_state()
        state["last_sleep_at"] = time.time()
        self._write_state(state)
        self.logger("进入睡眠")
        try:
            if self._sleep_config["mode"] == "display_only":
                self.logger("只显示模式，不执行任务")
            elif self._sleep_config["mode"] == "full":
                self._run_tasks()
        except Exception as exc:  # noqa: BLE001
            # 后台任务出错绝不能把状态卡在 sleeping：
            # 那会让宠物永远显示在睡觉，而且 monitor 线程已经退了，
            # 用户怎么点都醒不过来。
            self.logger("睡眠任务出错: %r" % (exc,))
        finally:
            if self._interrupt.is_set():
                self._finish_wake()
            elif self.state == "sleeping":
                with self._lock:
                    self.state = "deepsleep"
                self.set_pet_state("sleep")
                self.logger("睡眠整理完成，进入 deepsleep")
            else:
                # 状态被别处改过（比如 stop()），保证最终是醒着的
                with self._lock:
                    if self.state not in ("awake", "deepsleep"):
                        self.state = "awake"
                if self.state == "awake":
                    self.set_pet_state("idle")

    def _finish_wake(self):
        with self._lock:
            self._interrupt.clear()
            self.state = "awake"
        self.set_pet_state("idle")
        self.logger("已中断并唤醒")
        self.start()

    def _run_tasks(self):
        run_started_at = time.time()
        transcript, latest_updated_at = self._load_transcript(run_started_at)
        selected = set(self._sleep_config["tasks"])
        if ("memory" in selected or "review" in selected) and transcript:
            ok = self._run_prompt(SLEEP_PROMPT.replace("{{TRANSCRIPT}}", transcript), self.MEMORY_TOOLS)
            if self._interrupt.is_set():
                return
            if ok:
                state = self._read_state()
                # 水位线要落在**这批会话最新的更新时间**上，
                # 不能拿 run_started_at —— 那是"开始整理的时间"，
                # 会把整理期间新建/更新的会话一并算成"已整理"，永久漏掉。
                state["last_consolidated_at"] = max(
                    float(state.get("last_consolidated_at", 0) or 0),
                    latest_updated_at,
                )
                self._write_state(state)
                self.logger("记忆与对话整理完成")
        if "dream" in selected:
            if self._interrupt.is_set():
                return
            self._write_dream(transcript, run_started_at)

    def _run_prompt(self, prompt, allowed_tools, write_root=None, write_path=None):
        executor = SleepExecutor(
            self.provider, self.logger,
            self._sleep_registry, self._contains_sensitive,
            self._is_safe_write_path,
        )
        return executor.run(
            prompt, allowed_tools,
            is_interrupted=lambda: self._interrupt.is_set(),
            register_token=self._register_token,
            write_root=write_root, write_path=write_path,
        )

    def _register_token(self, token):
        """记录当前在跑的 LLM 调用令牌，好让 wake()/stop() 能立刻掐断。"""
        self._active_token = token

    @staticmethod
    def _contains_sensitive(value):
        text = str(value or "").lower()
        markers = ("api_key", "api key", "password", "passwd", "密码", "token", "私钥", "private key", "身份证", "银行卡")
        if any(marker in text for marker in markers):
            return True
        return bool(re.search(r"sk-[a-z0-9_-]{8,}", text))

    @staticmethod
    def _is_safe_write_path(path, root):
        target = os.path.abspath(path)
        base = os.path.abspath(root)
        try:
            if os.path.commonpath([target, base]) != base:
                return False
        except ValueError:
            return False
        name = os.path.basename(target)
        return name.startswith("dream_") and name.endswith(".md")

    def _sleep_registry(self, allowed_tools):
        registry = ToolRegistry()
        registry.register(MemoryTool())
        registry.register(_SleepFileTool(self._dreams_dir))
        schemas = [
            schema for schema in registry.get_schemas()
            if schema.get("function", {}).get("name") in allowed_tools
        ]
        return registry, schemas

    def _load_transcript(self, run_started_at):
        state = self._read_state()
        watermark = float(state.get("last_consolidated_at", 0) or 0)
        chunks = []
        latest = watermark
        try:
            filenames = os.listdir(conversations_dir())
        except OSError:
            # 会话目录还不存在（全新安装、从没聊过）——不是错误，
            # 以前这里直接抛，把 monitor 线程连带打死，状态卡死在 sleeping。
            return "", watermark
        for fname in filenames:
            if not fname.endswith(".json"):
                continue
            path = os.path.join(conversations_dir(), fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    conversation = json.load(f)
                updated_at = float(conversation.get("updated_at", os.path.getmtime(path)))
                if updated_at <= watermark or updated_at > run_started_at:
                    continue
                latest = max(latest, updated_at)
                for message in conversation.get("messages", []):
                    role = message.get("role")
                    content = str(message.get("content") or "").strip()
                    if role == "user" and content:
                        chunks.append("[用户]: " + content)
                    elif role == "assistant" and content and not message.get("tool_calls"):
                        chunks.append("[助手]: " + content)
            except Exception:
                continue
        return ("\n".join(chunks))[-20000:], latest

    def _next_dream_filename(self, date):
        prefix = "dream_" + date.replace("-", "_") + "_"
        index = 1
        while os.path.exists(os.path.join(self._dreams_dir, prefix + str(index) + ".md")):
            index += 1
        return prefix + str(index) + ".md"

    def _write_dream(self, transcript, run_started_at):
        date = datetime.now().strftime("%Y-%m-%d")
        filename = self._next_dream_filename(date)
        memories = MemoryTool().list_memories(20)
        prompt = DREAM_PROMPT.replace("{{TRANSCRIPT_SUMMARY}}", transcript[-3000:] or "无新对话")
        prompt = prompt.replace("{{MEMORY_DIGEST}}", memories)
        prompt = prompt.replace("{{DREAM_DIR}}", self._dreams_dir)
        target = os.path.join(self._dreams_dir, filename)
        prompt = prompt.replace("{{DATE}}", date).replace("{{DREAM_PATH}}", target)
        self._run_prompt(prompt, self.FILE_TOOLS | self.MEMORY_READ_TOOLS, write_root=self._dreams_dir, write_path=target)
        if not self._interrupt.is_set() and self._dream_char_count(target) < 400:
            self.logger("梦过短或未落盘，执行一次重写")
            retry = prompt + "\n\n上一次没有正确保存，或正文少于 500 字。必须调用 write_file 保存到同一路径；正文至少 500 字；不要文学腔。"
            self._run_prompt(retry, self.FILE_TOOLS | self.MEMORY_READ_TOOLS, write_root=self._dreams_dir, write_path=target)
        if os.path.isfile(target):
            self.logger("梦已保存: " + target)
        elif not self._interrupt.is_set():
            self.logger("梦未落盘")

    @staticmethod
    def _dream_char_count(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            return len(re.sub(r"\s+", "", text))
        except Exception:
            return 0

    def _read_state(self):
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                value = json.load(f)
            if isinstance(value, dict):
                return value
        except Exception:
            pass
        return {"last_consolidated_at": 0, "last_sleep_at": 0}

    def _write_state(self, value):
        temp = self._state_path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
        os.replace(temp, self._state_path)
