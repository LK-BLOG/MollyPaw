"""File Tool - Read/write files as an agent capability."""


class FileTool:
    """Simple file read/write tool for the agent."""

    name = "file_tool"
    description = "Read and write local files"

    def read_file(self, path: str) -> str:
        """Read a file and return its contents."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"

    def write_file(self, path: str, content: str) -> str:
        """Write content to a file."""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"Successfully wrote to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    def list_directory(self, path: str = ".") -> str:
        """List files in a directory."""
        import os
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
