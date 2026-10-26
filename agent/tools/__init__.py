"""MollyPaw Agent - Tools."""
from agent.tools.registry import ToolRegistry
from agent.tools.file_tool import FileTool
from agent.tools.exec_tool import ExecTool
from agent.tools.process_tool import ProcessTool
from agent.tools.skill_tool import SkillTool
from agent.tools.memory_tool import MemoryTool
from agent.tools.web_tool import WebTool

# Default registry with built-in tools registered.
default_registry = ToolRegistry()
default_registry.register(FileTool())

# Register ExecTool and its danger classifier
_exec_tool = ExecTool()
default_registry.register(_exec_tool)
default_registry.register_danger_classifier("exec_command", _exec_tool.classify_danger)

# Register ProcessTool —— 处理被"停止"转进后台的命令
_process_tool = ProcessTool()
default_registry.register(_process_tool)
default_registry.register_danger_classifier(
    "process_kill", lambda arguments: "moderate")

# Register SkillTool
default_registry.register(SkillTool())

# Register MemoryTool
default_registry.register(MemoryTool())

# Register web search and fetch
default_registry.register(WebTool())
