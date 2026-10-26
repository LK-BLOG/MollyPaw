"""Exec Tool - Execute shell commands as an agent capability.

## 停止语义（0.0.0.2.1 改的）

用户点「停止」时，这条命令**不会被硬杀**，而是转入后台继续跑
（见 agent/process_manager.py）。原因和好处写在那个模块的文档里，
一句话：硬杀会丢状态、还会让 UI 卡在"正在停"，而转后台之后
模型能看到进程、自己决定是留还是杀。

超时（`timeout` 参数）也走同一条路：不再杀掉命令，而是**把它推到后台**
并告诉模型 pid —— 卡住的命令照样能跑完，但这一轮不再被它拖住。
"""
import os
import re
import subprocess
import threading
import time as _time

from agent.process_manager import manager as bg_manager


class ExecTool:
    """Shell command execution tool for the agent."""

    name = "exec_tool"
    description = "Execute shell commands"

    # 正在跑的子进程，供"全部清理"用。key=Popen 对象。
    _running = set()
    _running_lock = None

    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "exec_command",
                "description": (
                    "Execute a shell command and return its output. "
                    "Supports PowerShell and cmd. "
                    "If the command is still running when the timeout is hit, "
                    "it is moved to the background (you get its pid back) "
                    "instead of being killed — use process_list / process_kill "
                    "to deal with it."
                ),
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
                            "description": (
                                "How many seconds to wait before moving the command "
                                "to the background. Default 30."
                            ),
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
        """强杀所有在跑的子进程树（真·清理，不是停止）。

        注意：用户点「停止」时**不会**走这里了 —— 停止是转后台。
        这个方法是给程序退出 / 显式清理用的。
        """
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

        用 Popen 而不是 run，是为了能在用户点"停止"时把进程**转入后台**
        （run() 会一直阻塞到命令自己结束，停止按钮就成了摆设）。

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

        t_out = threading.Thread(target=_reader, args=(proc.stdout, stdout_chunks), daemon=True)
        t_err = threading.Thread(target=_reader, args=(proc.stderr, stderr_chunks), daemon=True)
        t_out.start()
        t_err.start()

        deadline = (_time.time() + timeout) if (timeout and timeout > 0) else None
        reason = None   # None / "cancelled" / "timeout"

        try:
            while proc.poll() is None:
                if cancel is not None and cancel.cancelled:
                    reason = "cancelled"
                    break
                if deadline is not None and _time.time() > deadline:
                    reason = "timeout"
                    break
                _time.sleep(0.05)
        finally:
            if reason is None:
                # 正常跑完：关管道、等读线程收尾
                for stream in (proc.stdout, proc.stderr):
                    try:
                        stream.close()
                    except Exception:
                        pass
                t_out.join(timeout=1)
                t_err.join(timeout=1)
                self._unregister(proc)
            else:
                # 转后台：**不能关管道也不能 kill**，读线程继续持有它
                self._unregister(proc)
                self._handoff(proc, cmd, shell, stdout_chunks, stderr_chunks)

        if reason == "cancelled":
            from agent.cancel import CancelledError

            # 注意：这里抛出去，AgentCore 会回滚本轮历史。
            # 后台进程的事记在 ProcessManager 里，下一轮通过系统提示摆给模型看。
            raise CancelledError(
                "command cancelled by user; it was moved to the background "
                "(pid %d) instead of being killed — use process_list / "
                "process_kill to deal with it" % proc.pid
            )

        if reason == "timeout":
            tail_out, tail_err, trunc = _tail_text(stdout_chunks, stderr_chunks)
            note = (
                "\n[这台命令超过 %ss 还没跑完，已转入后台继续跑，pid=%d]\n"
                "它没有被杀。想留结果就用 process_list 看输出；"
                "想停掉就用 process_kill(pid=%d)。"
                "[Exit code: None]" % (timeout, proc.pid, proc.pid)
            )
            body = tail_out
            if tail_err:
                body += "\n[STDERR]\n" + tail_err
            if trunc:
                body += "\n... (输出过长，只保留尾部)"
            return (body + note).strip()

        output = "".join(stdout_chunks)
        if stderr_chunks:
            output += "\n[STDERR]\n" + "".join(stderr_chunks)
        if proc.returncode not in (0, None):
            output += f"\n[Exit code: {proc.returncode}]"
        return output.strip() if output.strip() else "(no output)"

    def _handoff(self, proc, cmd, shell, stdout_chunks, stderr_chunks):
        """把进程交给 ProcessManager 托管。失败也不能影响取消本身。"""
        try:
            entry = bg_manager().adopt(
                proc, cmd, stdout_chunks, stderr_chunks, shell=shell)
            # 兜底：若进程其实已经退了，托管表里那条立刻标记
            entry.refresh_exit()
            return entry
        except Exception:
            return None


def _tail_text(stdout_chunks, stderr_chunks, max_chars=6000):
    out = "".join(stdout_chunks)
    err = "".join(stderr_chunks)
    trunc = False
    if len(out) > max_chars:
        out = out[-max_chars:]
        trunc = True
    if len(err) > max_chars:
        err = err[-max_chars:]
        trunc = True
    return out, err, trunc
