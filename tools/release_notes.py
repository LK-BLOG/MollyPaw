#!/usr/bin/env python3
"""从 CHANGELOG.md 里抠出指定版本的正文，用于 GitHub Release。

    python tools/release_notes.py v0.0.0.1.6 > notes.md

找不到该版本时回落成一行标题，不让发布流程因为「还没写 CHANGELOG」而中断 ——
tools/release_check.py 那边会把缺失的段落判成失败，职责分开。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def normalize_tag(tag: str) -> str:
    """从 tag 取纯版本号（v0.0.0.1 / Beta-0.0.0.1.4 / beta-0.0.0.2.0 都行）。"""
    match = re.search(r"(\d[\d.]*)$", tag.strip())
    return match.group(1) if match else tag.strip().lstrip("v")


def notes(version: str) -> str:
    changelog = ROOT / "CHANGELOG.md"
    if not changelog.is_file():
        return f"MollyPaw {version}"
    text = changelog.read_text(encoding="utf-8")
    match = re.search(rf"^## \[{re.escape(version)}\].*?$", text, re.M)
    if not match:
        return f"MollyPaw {version}"
    rest = text[match.end():]
    nxt = re.search(r"^## \[", rest, re.M)
    return (rest[: nxt.start()] if nxt else rest).strip()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法: python tools/release_notes.py vX.Y.Z", file=sys.stderr)
        return 2
    # Windows 控制台默认 GBK，中文和符号会炸 —— 强制 UTF-8 输出。
    # CI 里重定向到文件时同样受益（否则可能写成乱码）。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(notes(normalize_tag(argv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
