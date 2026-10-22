"""MollyPaw Relay — 文件访问（远程 RPC）。

用户明确要求「不限目录、不要黑名单」。所以这里**真的不拦任何路径**：
`C:\\Windows\\System32`、`~/.ssh`、浏览器 Cookie 库，全都可读可写。

代价是明白的：任何拿到 PSK + 设备 token 的人都能读写这台机器的任何文件。
缓解措施（都实现了）：
  - 每次访问写审计日志 `data/relay/fs_audit.log`（时间 / 设备 / 操作 / 路径 / 结果）
  - 写操作（write/mkdir/delete）必须走审批（在 bridge 里拦）
  - 设备可以单独吊销
  - 观察端完全不能碰 fs

这条风险已在 PROTOCOL.md 与交付说明里书面记录，不再粉饰。
"""
import base64
import json
import os
import threading
import time

from agent.relay import crypto as C


class FsApi:
    """fs.* 方法的实现。"""

    def __init__(self, audit_path=None, logger=None):
        if audit_path is None:
            from agent.paths import data_dir

            base = os.path.join(data_dir(), "relay")
            os.makedirs(base, exist_ok=True)
            audit_path = os.path.join(base, "fs_audit.log")
        self.audit_path = audit_path
        self.logger = logger
        self._audit_lock = threading.RLock()

    # -- 审计 --------------------------------------------------------------

    def _audit(self, device, action, path, ok, detail=""):
        entry = {
            "ts": time.time(),
            "device": device or "unknown",
            "action": action,
            "path": str(path),
            "ok": bool(ok),
            "detail": str(detail)[:300],
        }
        try:
            with self._audit_lock:
                os.makedirs(os.path.dirname(self.audit_path), exist_ok=True)
                with open(self.audit_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            if self.logger:
                try:
                    self.logger(f"fs audit write failed: {exc}")
                except Exception:
                    pass

    def read_audit(self, limit=200):
        """读最近的审计记录（给设置页看）。"""
        if not os.path.exists(self.audit_path):
            return []
        try:
            with open(self.audit_path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-limit:]
            out = []
            for line in lines:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            out.reverse()
            return out
        except Exception:
            return []

    # -- 路径 --------------------------------------------------------------

    @staticmethod
    def _abs(path):
        """把用户给的路径规范化成绝对路径。

        支持 `~` 和 Windows 盘符。不做任何白名单校验 —— 这是刻意的。
        """
        if not path:
            return os.path.abspath(os.getcwd())
        p = os.path.expandvars(os.path.expanduser(str(path)))
        return os.path.abspath(p)

    # -- 方法 --------------------------------------------------------------

    def roots(self, device=None):
        """返回常见根目录，方便手机端快速跳转。"""
        roots = []
        if os.name == "nt":
            for letter in "CDEFGH":
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    roots.append({"name": f"{letter} 盘", "path": drive})
            home = os.path.expanduser("~")
            if os.path.isdir(home):
                roots.insert(0, {"name": "用户目录", "path": home})
        else:
            roots.append({"name": "根目录", "path": "/"})
            home = os.path.expanduser("~")
            if os.path.isdir(home):
                roots.insert(0, {"name": "用户目录", "path": home})
        return {"roots": roots}

    def list_dir(self, path=".", device=None):
        target = self._abs(path)
        try:
            entries = []
            with os.scandir(target) as it:
                for entry in it:
                    if len(entries) >= 5000:
                        break
                    try:
                        is_dir = entry.is_dir()
                        size = 0 if is_dir else entry.stat().st_size
                        mtime = entry.stat().st_mtime
                    except OSError:
                        is_dir, size, mtime = False, 0, 0
                    entries.append({
                        "name": entry.name,
                        "is_dir": is_dir,
                        "size": size,
                        "mtime": mtime,
                    })
            # 目录在前，然后按名字排（大小写不敏感，中文也能排）
            entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
            self._audit(device, "list", target, True)
            return {"path": target, "entries": entries,
                    "parent": os.path.dirname(target)}
        except Exception as exc:
            self._audit(device, "list", target, False, exc)
            raise

    def stat(self, path, device=None):
        target = self._abs(path)
        try:
            st = os.stat(target)
            result = {
                "path": target,
                "size": st.st_size,
                "mtime": st.st_mtime,
                "is_dir": os.path.isdir(target),
            }
            self._audit(device, "stat", target, True)
            return result
        except Exception as exc:
            self._audit(device, "stat", target, False, exc)
            raise

    def read(self, path, offset=0, length=None, device=None):
        """读一段文件内容，返回 base64。单次最多 FS_CHUNK 字节。"""
        target = self._abs(path)
        offset = max(0, int(offset or 0))
        limit = C.FS_CHUNK if length is None else min(int(length), C.FS_CHUNK)
        limit = max(0, limit)
        try:
            size = os.path.getsize(target)
            with open(target, "rb") as f:
                f.seek(offset)
                data = f.read(limit)
            eof = (offset + len(data)) >= size
            self._audit(device, "read", target, True, f"{offset}+{len(data)}/{size}")
            return {
                "path": target,
                "data_b64": base64.b64encode(data).decode("ascii"),
                "size": size,
                "offset": offset,
                "eof": eof,
                "chunk_size": C.FS_CHUNK,
            }
        except Exception as exc:
            self._audit(device, "read", target, False, exc)
            raise

    def write(self, path, data_b64, offset=None, device=None):
        """写文件。offset 为 None 时覆盖写，否则从 offset 追加式写入。"""
        target = self._abs(path)
        try:
            raw = base64.b64decode(data_b64)
        except Exception as exc:
            self._audit(device, "write", target, False, f"bad base64: {exc}")
            raise ValueError("data_b64 is not valid base64")

        try:
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            mode = "r+b" if (offset is not None and os.path.exists(target)) else "wb"
            with open(target, mode) as f:
                if offset is not None:
                    f.seek(int(offset))
                f.write(raw)
            self._audit(device, "write", target, True, f"{len(raw)} bytes")
            return {"written": len(raw), "path": target}
        except Exception as exc:
            self._audit(device, "write", target, False, exc)
            raise

    def mkdir(self, path, device=None):
        target = self._abs(path)
        try:
            os.makedirs(target, exist_ok=True)
            self._audit(device, "mkdir", target, True)
            return {"ok": True, "path": target}
        except Exception as exc:
            self._audit(device, "mkdir", target, False, exc)
            raise

    def delete(self, path, device=None):
        """删除文件或空目录。

        非空目录要递归删除 —— 这是危险操作，所以 bridge 层强制它走审批。
        """
        target = self._abs(path)
        try:
            if os.path.isdir(target) and not os.path.islink(target):
                import shutil

                shutil.rmtree(target)
            else:
                os.remove(target)
            self._audit(device, "delete", target, True)
            return {"ok": True, "path": target}
        except Exception as exc:
            self._audit(device, "delete", target, False, exc)
            raise
