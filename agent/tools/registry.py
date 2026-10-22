"""Tool Registry - Manages agent tools and dispatches execution."""
import json


class ToolRegistry:
    """Collects tool schemas and dispatches function calls."""

    def __init__(self):
        self._tool_map = {}   # function_name -> tool instance
        self._schemas = []    # OpenAI tools format
        self._danger_map = {} # function_name -> danger classifier callable

    def register(self, tool):
        """Register a tool that exposes TOOLS (list of OpenAI schemas)
        and an execute(name, arguments) method."""
        for schema in tool.TOOLS:
            func_name = schema["function"]["name"]
            self._tool_map[func_name] = tool
        self._schemas.extend(tool.TOOLS)

    def register_danger_classifier(self, func_name: str, classifier):
        """Register a danger classifier for a specific function.
        classifier(arguments) -> str ('safe', 'moderate', 'dangerous')"""
        self._danger_map[func_name] = classifier

    def get_schemas(self):
        """Return the tools list for the API payload, or None."""
        return self._schemas if self._schemas else None

    def get_danger_level(self, func_name: str, arguments: dict) -> str:
        """Determine danger level for a tool call.
        Returns 'safe', 'moderate', or 'dangerous'."""
        # Check registered classifier first
        if func_name in self._danger_map:
            return self._danger_map[func_name](arguments)

        # Built-in classifications
        if func_name == "write_file":
            return "moderate"
        elif func_name == "create_skill":
            return "moderate"
        elif func_name == "delete_skill":
            return "dangerous"
        elif func_name == "exec_command":
            # Default: moderate for unknown exec
            return "moderate"

        return "safe"

    def execute(self, func_name: str, arguments: dict) -> str:
        """Execute a function call and return the result as a string."""
        tool = self._tool_map.get(func_name)
        if not tool:
            return f"Error: unknown tool '{func_name}'"
        if not isinstance(arguments, dict):
            return f"Error: invalid arguments for '{func_name}': expected an object"
        schema = next((item for item in self._schemas if item.get("function", {}).get("name") == func_name), {})
        required = schema.get("function", {}).get("parameters", {}).get("required", [])
        missing = [name for name in required if name not in arguments]
        if missing:
            return f"Error: missing required argument(s) for '{func_name}': {', '.join(missing)}"
        try:
            return tool.execute(func_name, arguments)
        except TypeError as exc:
            return f"Error: invalid arguments for '{func_name}': {exc}"
        except Exception as exc:
            return f"Error executing '{func_name}': {exc}"