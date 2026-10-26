"""Process Tool — 让模型看见并处理「被停止」的命令。

用户点停止后，命令不是被杀，而是转到后台（见 agent/process_manager.py）。
模型光靠一句「被用户取消」什么也做不了，所以给它这两把工具：

  process_list(pid?)   看后台有什么在跑、输出到哪了
  process_kill(pid?)   杀掉（有子进程杀整棵树，没有就杀主进程）
"""
from agent.process_manager import child_pids, manager as bg_manager


class ProcessTool:
    """后台进程管理工具。"""

    name = "process_tool"
    description = "Inspect and kill background processes left over by a stop"

    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "process_list",
                "description": (
                    "List commands that were moved to the background (because the "
                    "user pressed stop or the timeout was hit). Shows pid, running "
                    "state, how long it has been running, and the tail of its output. "
                    "Pass pid for a single process's full output."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pid": {
                            "type": "integer",
                            "description": "Only show this process. Omit to list all.",
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "process_kill",
                "description": (
                    "Kill a background process. If it has child processes the whole "
                    "tree is killed; if it has none only the main process is killed. "
                    "Omit pid to kill every background process."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pid": {
                            "type": "integer",
                            "description": "Process id. Omit to kill all of them.",
                        },
                    },
                },
            },
        },
    ]

    def execute(self, func_name: str, arguments: dict) -> str:
        if func_name == "process_list":
            return self.process_list(**arguments)
        if func_name == "process_kill":
            return self.process_kill(**arguments)
        return f"Error: ProcessTool has no method '{func_name}'"

    # -- 列 ------------------------------------------------------------------

    def process_list(self, pid=None) -> str:
        mgr = bg_manager()
        if pid is not None:
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                return "Error: pid must be an integer"
            entry = mgr.get(pid)
            if entry is None:
                return (
                    f"No background process with pid {pid}. "
                    "Use process_list without arguments to see what is running."
                )
            entry.refresh_exit()
            out, err, truncated = entry.snapshot(max_lines=200, max_chars=8000)
            lines = [
                "pid: %d" % entry.pid,
                "command: %s" % entry.cmd,
                "shell: %s" % entry.shell,
                "state: %s" % ("running" if entry.alive else "exited"),
                "exit_code: %s" % entry.exit_code,
                "ran_for_seconds: %d" % int(entry.age),
                "child_processes: %s" % (child_pids(entry.pid) or "none"),
                "",
                "--- stdout%s ---" % (" (tail)" if truncated else ""),
                out or "(empty)",
            ]
            if err:
                lines += ["", "--- stderr ---", err]
            return "\n".join(lines)

        entries = mgr.list()
        if not entries:
            return "No background processes. Nothing was moved to the background."

        alive = [e for e in entries if e.alive]
        lines = [
            "%d background process(es), %d still running." % (len(entries), len(alive)),
            "",
        ]
        for entry in entries:
            entry.refresh_exit()
            state = "running" if entry.alive else "exited(%s)" % entry.exit_code
            killed = " killed_by=%s" % entry.killed_by if entry.killed_by else ""
            kids = child_pids(entry.pid) if entry.alive else []
            lines.append(
                "- pid=%d [%s] %ds%s%s\n    $ %s" % (
                    entry.pid, state, int(entry.age), killed,
                    " children=%s" % kids if kids else "",
                    entry.cmd.replace("\n", " ")[:300],
                )
            )
            out, _, _ = entry.snapshot(max_lines=8, max_chars=600)
            if out.strip():
                for line in out.rstrip().splitlines()[-4:]:
                    lines.append("      | " + line)
        lines += [
            "",
            "Kill with process_kill(pid=...) or process_kill() for all of them.",
        ]
        return "\n".join(lines)

    # -- 杀 ------------------------------------------------------------------

    def process_kill(self, pid=None) -> str:
        mgr = bg_manager()
        if pid is None:
            entries = [e for e in mgr.list() if e.alive]
            if not entries:
                return "No running background process to kill."
            lines = ["Killed %d background process(es):" % len(entries)]
            for entry in entries:
                info = mgr.kill(entry.pid, by="user")
                lines.append(self._describe_kill(info, entry.cmd))
            return "\n".join(lines)

        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return "Error: pid must be an integer"

        entry = mgr.get(pid)
        cmd = entry.cmd if entry is not None else "(not in background table)"
        if entry is not None and not entry.alive:
            return (
                "pid %d already exited (exit_code=%s). Nothing to kill."
                % (pid, entry.exit_code)
            )
        info = mgr.kill(pid, by="user")
        return self._describe_kill(info, cmd)

    @staticmethod
    def _describe_kill(info, cmd):
        kids = info.get("children") or []
        if kids:
            how = "killed process tree (children: %s)" % ", ".join(str(k) for k in kids)
        else:
            how = "no child process, killed the main process only"
        state = "ok" if info.get("ok") else "failed"
        return "- pid=%d %s — %s\n    $ %s" % (
            info.get("pid"), state, how, " ".join(str(cmd).split())[:200])
