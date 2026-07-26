"""MollyPaw Agent - Tools."""
from agent.tools.registry import ToolRegistry
from agent.tools.file_tool import FileTool

# Default registry with built-in tools registered.
default_registry = ToolRegistry()
default_registry.register(FileTool())
