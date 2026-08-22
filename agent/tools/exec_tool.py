"""Exec Tool - Execute shell commands as an agent capability."""
import subprocess
import re
import os


class ExecTool:
    """Shell command execution tool for the agent."""

    name = "exec_tool"
    description = "Execute shell commands"

    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "exec_command",
                "description": "Execute a shell command and return its output. Supports PowerShell and cmd.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cmd": {
                            "type": "string",
                            "description": "The command to execute.",
                        },
                        "shell": {
                            "type": "string",
                            "description": "Shell to use: 'powershell' (default) or 'cmd'.",
                            "enum": ["powershell", "cmd"],
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Max execution time in seconds. Default 30.",
                        },
                    },
                    "required": ["cmd"],
                },
            },
        },
    ]

    # Danger classification patterns
    DANGEROUS_PATTERNS = [
        r'\brm\b', r'\brmdir\b', r'\bdel\b', r'\bRemove-Item\b',
        r'\bformat\b', r'\bmkfs\b', r'\bdd\b',
        r'\bshutdown\b', r'\breboot\b', r'\bRestart-Computer\b',
        r'\bStop-Computer\b',
        r'> /dev/null', r'2> /dev/null',
        r'\bsudo\b', r'\bchmod\b', r'\bchown\b',
        r'\bGet-WmiObject\b.*\bWin32_Processor\b',
        r'\bnet user\b', r'\bnet localgroup\b',
        r'\bsystemctl\b', r'\bservice\b.*\bstop\b',
        r'\btaskkill\b', r'\bStop-Process\b',
        r'\breg\b.*\bdelete\b', r'\bRemove-ItemProperty\b',
    ]

    SAFE_PATTERNS = [
        r'\bGet-Content\b', r'\bcat\b', r'\btype\b',
        r'\bGet-ChildItem\b', r'\bdir\b', r'\bls\b',
        r'\bGet-Process\b', r'\bps\b',
        r'\bGet-Date\b', r'\bdate\b',
        r'\bwhoami\b', r'\becho\b', r'\bWrite-Output\b',
        r'\bgit\b.*\blog\b', r'\bgit\b.*\bstatus\b', r'\bgit\b.*\bdiff\b',
        r'\bGet-Host\b', r'\bhostname\b',
        r'\bpython\b.*\b--version\b', r'\bpip\b.*\blist\b',
        r'\bGet-Command\b', r'\bwhere\b', r'\bwhich\b',
    ]

    def classify_danger(self, cmd_or_args) -> str:
        """Return 'safe', 'moderate', or 'dangerous'.
        Accepts either a command string or the arguments dict from function calling."""
        if isinstance(cmd_or_args, dict):
            cmd = cmd_or_args.get("cmd", "")
        else:
            cmd = str(cmd_or_args)
        cmd_lower = cmd.lower().strip()
        for pattern in self.SAFE_PATTERNS:
            if re.search(pattern, cmd_lower):
                return "safe"
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, cmd_lower):
                return "dangerous"
        return "moderate"

    def execute(self, func_name: str, arguments: dict) -> str:
        """Dispatcher called by ToolRegistry."""
        if func_name != "exec_command":
            return f"Error: ExecTool has no method '{func_name}'"
        return self.exec_command(**arguments)

    def exec_command(self, cmd: str, shell: str = "powershell", timeout: int = 30) -> str:
        """Execute a shell command and return output."""
        try:
            if shell == "cmd":
                proc = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    timeout=timeout, encoding="utf-8", errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            else:
                proc = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", cmd],
                    capture_output=True, text=True,
                    timeout=timeout, encoding="utf-8", errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            output = proc.stdout
            if proc.stderr:
                output += "\n[STDERR]\n" + proc.stderr
            if proc.returncode != 0:
                output += f"\n[Exit code: {proc.returncode}]"
            return output.strip() if output.strip() else "(no output)"
        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {timeout}s"
        except Exception as e:
            return f"Error executing command: {e}"