"""Exec Tool - Execute shell commands as an agent capability."""
import os
import re
import subprocess


class ExecTool:
    """Shell command execution tool for the agent."""

    name = "exec_tool"
    description = "Execute shell commands"

    # 正在跑的子进程，供取消时杀进程树。key=Popen 对象。
    _running = set()
    _running_lock = None

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

    @classmethod
    def _register(cls, proc):
        import threading

        if cls._running_lock is None:
            cls._running_lock = threading.Lock()
        with cls._running_lock:
            cls._running.add(proc)

    @classmethod
    def _unregister(cls, proc):
        if cls._running_lock is None:
            return
        with cls._running_lock:
            cls._running.discard(proc)

    @classmethod
    def kill_all(cls):
        """杀掉所有在跑的子进程树。取消时由上层调用。"""
        from agent.cancel import kill_process_tree

        if cls._running_lock is None:
            return
        with cls._running_lock:
            procs = list(cls._running)
        for proc in procs:
            if proc.poll() is None:
                kill_process_tree(proc.pid)

    def exec_command(self, cmd: str, shell: str = "powershell",
                     timeout: int = 30, cancel=None) -> str:
        """执行命令，支持取消。

        用 Popen 而不是 run，是为了能在用户点"停止"时**真的杀掉进程树**。
        run() 会一直阻塞到命令自己结束，取消按钮就成了摆设。

        cancel 不传时自动从上下文取（agent.cancel.use_token 设置的），
        这样 AgentCore 不需要给所有工具改签名。
        """
        if cancel is None:
            from agent.cancel import current_token

            cancel = current_token()

        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        if shell == "cmd":
            args = cmd
            use_shell = True
        else:
            args = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
            use_shell = False

        try:
            proc = subprocess.Popen(
                args,
                shell=use_shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
                start_new_session=(os.name != "nt"),
            )
        except Exception as exc:
            return f"Error starting command: {exc}"

        self._register(proc)

        stdout_chunks = []
        stderr_chunks = []

        def _reader(stream, sink):
            try:
                for line in iter(stream.readline, ""):
                    sink.append(line)
            except Exception:
                pass

        import threading
        import time as _time

        t_out = threading.Thread(target=_reader, args=(proc.stdout, stdout_chunks), daemon=True)
        t_err = threading.Thread(target=_reader, args=(proc.stderr, stderr_chunks), daemon=True)
        t_out.start()
        t_err.start()

        deadline = (_time.time() + timeout) if (timeout and timeout > 0) else None
        cancelled = False
        timed_out = False

        try:
            while proc.poll() is None:
                if cancel is not None and cancel.cancelled:
                    cancelled = True
                    from agent.cancel import kill_process_tree

                    kill_process_tree(proc.pid)
                    try:
                        proc.wait(timeout=3)
                    except Exception:
                        pass
                    break
                if deadline is not None and _time.time() > deadline:
                    timed_out = True
                    from agent.cancel import kill_process_tree

                    kill_process_tree(proc.pid)
                    try:
                        proc.wait(timeout=3)
                    except Exception:
                        pass
                    break
                _time.sleep(0.05)
        finally:
            for stream in (proc.stdout, proc.stderr):
                try:
                    stream.close()
                except Exception:
                    pass
            t_out.join(timeout=1)
            t_err.join(timeout=1)
            self._unregister(proc)

        if cancelled:
            from agent.cancel import CancelledError

            raise CancelledError("command cancelled by user")

        output = "".join(stdout_chunks)
        if stderr_chunks:
            output += "\n[STDERR]\n" + "".join(stderr_chunks)
        if timed_out:
            output += f"\nError: Command timed out after {timeout}s"
        elif proc.returncode not in (0, None):
            output += f"\n[Exit code: {proc.returncode}]"
        return output.strip() if output.strip() else "(no output)"