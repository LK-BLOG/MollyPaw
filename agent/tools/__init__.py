"""MollyPaw Agent - Tools."""
from agent.tools.registry import ToolRegistry
from agent.tools.file_tool import FileTool
from agent.tools.exec_tool import ExecTool
from agent.tools.skill_tool import SkillTool
from agent.tools.memory_tool import MemoryTool

# Default registry with built-in tools registered.
default_registry = ToolRegistry()
default_registry.register(FileTool())

# Register ExecTool and its danger classifier
_exec_tool = ExecTool()
default_registry.register(_exec_tool)
default_registry.register_danger_classifier("exec_command", _exec_tool.classify_danger)

# Register SkillTool
default_registry.register(SkillTool())

# Register MemoryTool
default_registry.register(MemoryTool())
