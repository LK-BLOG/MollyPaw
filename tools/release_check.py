#!/usr/bin/env python3
"""发布前校验：tag 与版本号一致、CHANGELOG 有对应段落。

参考 D:\\PawUI\\tools\\release_check.py 的做法：
**tag 就是版本号的唯一真源**，代码里不再维护一份"当前版本"，
所以不会出现「README 写的 0.1.5、实际打包出来 0.1.4」这种漂移。

用法：
    python tools/release_check.py v0.0.0.1.6          # 带 tag 校验
    python tools/release_check.py                      # 只校验 CHANGELOG
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Windows 控制台默认 GBK，打不出 ✅ / ❌ 会抛 UnicodeEncodeError。
# CI 里是 UTF-8，本地是 GBK —— 统一成"能显示什么就显示什么"。
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent


def normalize_tag(tag: str) -> str:
    """从 tag 里取出纯版本号。

    这个项目的 tag 有好几种写法（历史上就乱）：
        v0.0.0.1 / v0.0.0.1.1 / Beta-0.0.0.1.4 / beta-0.0.0.1.5
    所以不能只 lstrip("v") —— 得把前缀整个剥掉。
    """
    text = tag.strip()
    # 剥掉所有非数字开头的前缀（v / Beta- / beta- 等）
    match = re.search(r"(\d[\d.]*)$", text)
    return match.group(1) if match else text.lstrip("v")


def read_version() -> str:
    """从 main.py 里读版本号（如果有）。"""
    main_py = ROOT / "main.py"
    if not main_py.is_file():
        return ""
    text = main_py.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else ""


def changelog_section(version: str) -> str:
    changelog = ROOT / "CHANGELOG.md"
    if not changelog.is_file():
        return ""
    text = changelog.read_text(encoding="utf-8")
    match = re.search(rf"^## \[{re.escape(version)}\].*?$", text, re.M)
    if not match:
        return ""
    rest = text[match.end():]
    nxt = re.search(r"^## \[", rest, re.M)
    return (rest[: nxt.start()] if nxt else rest).strip()


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    tag = args[0] if args else ""
    problems: list[str] = []

    version = read_version()
    if version:
        print(f"main.py __version__ : {version}")
    else:
        print("main.py __version__ : (没写，版本以 tag 为准)")

    if tag:
        stripped = normalize_tag(tag)
        print(f"tag                : {tag}  ->  {stripped}")
        if version and stripped != version:
            problems.append(f"tag {tag}（{stripped}）与 main.py 的 {version} 不一致")

        section = changelog_section(stripped)
        if section:
            print(f"CHANGELOG [{stripped}] : {len(section.splitlines())} 行")
        else:
            problems.append(f"CHANGELOG.md 里没有 ## [{stripped}] 段落")

    print()
    if problems:
        for item in problems:
            print(f"  ! {item}")
        print("\n校验失败")
        return 1
    print("校验通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
