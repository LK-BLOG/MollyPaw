"""File Tool - Read/write files as an agent capability."""
import os


class FileTool:
    """File read/write/list tool for the agent.

    Each public method is exposed to the LLM via the TOOLS schema list.
    The ``execute`` dispatcher is called by the ToolRegistry.
    """

    name = "file_tool"
    description = "Read and write local files"

    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read the contents of a text file and return them as a string.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute or relative path to the file.",
                        }
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write (overwrite) text content to a file. Creates the file if it does not exist.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute or relative path to the file.",
                        },
                        "content": {
                            "type": "string",
                            "description": "The full text content to write.",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_directory",
                "description": "List files and subdirectories in a folder. Returns a formatted listing with types and sizes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Directory path. Defaults to the current working directory.",
                        }
                    },
                    "required": [],
                },
            },
        },
    ]

    def execute(self, func_name: str, arguments: dict) -> str:
        """Dispatcher called by ToolRegistry."""
        method = getattr(self, func_name, None)
        if method is None:
            return f"Error: FileTool has no method '{func_name}'"
        return method(**arguments)

    def read_file(self, path: str) -> str:
        """Read a file and return its contents."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"

    def write_file(self, path: str, content: str) -> str:
        """Write content to a file."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    def list_directory(self, path: str = ".") -> str:
        """List files in a directory."""
        try:
            entries = os.listdir(path)
            lines = []
            for entry in sorted(entries):
                full = os.path.join(path, entry)
                kind = "d" if os.path.isdir(full) else "f"
                size = os.path.getsize(full) if os.path.isfile(full) else 0
                lines.append(f"[{kind}] {entry} ({size} bytes)")
            return "\n".join(lines) if lines else "(empty directory)"
        except Exception as e:
            return f"Error listing directory: {e}"
