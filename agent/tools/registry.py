"""Tool Registry - Manages agent tools and dispatches execution."""
import json


class ToolRegistry:
    """Collects tool schemas and dispatches function calls."""

    def __init__(self):
        self._tool_map = {}   # function_name -> tool instance
        self._schemas = []    # OpenAI tools format

    def register(self, tool):
        """Register a tool that exposes TOOLS (list of OpenAI schemas)
        and an execute(name, arguments) method."""
        for schema in tool.TOOLS:
            func_name = schema["function"]["name"]
            self._tool_map[func_name] = tool
        self._schemas.extend(tool.TOOLS)

    def get_schemas(self):
        """Return the tools list for the API payload, or None."""
        return self._schemas if self._schemas else None

    def execute(self, func_name: str, arguments: dict) -> str:
        """Execute a function call and return the result as a string."""
        tool = self._tool_map.get(func_name)
        if not tool:
            return f"Error: unknown tool '{func_name}'"
        return tool.execute(func_name, arguments)
