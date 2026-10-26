"""按 git tag 把版本号写进代码 / 横幅。

版本号的唯一真源是 tag —— 但 exe 里得有个能读到的常量，
自动更新要靠它跟 GitHub 上的最新 release 比大小。
CI 在打包前调用本脚本，本地也可以手动跑。

用法：
    python tools/apply_version.py                # 用 git describe 最近 tag
    python tools/apply_version.py beta-0.0.0.2.1 # 显式指定
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def normalize_tag(tag):
    """beta-0.0.0.2.1 / Beta-0.0.0.2.1 / v0.0.0.2.1 -> 0.0.0.2.1"""
    text = (tag or "").strip()
    match = re.search(r"(\d[\d.]*)$", text)
    return match.group(1) if match else text


def git_tag():
    try:
        out = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=ROOT, stderr=subprocess.DEVNULL,
        ).decode("utf-8", "replace").strip()
        return out
    except Exception:
        return ""


def current_version():
    """读出仓库里现有的 APP_VERSION。

    CI 的 checkout 默认只取一个 commit、不带 tag，`git describe` 会空;
    这时候**不该报错退出** —— 非 tag 构建只要沿用现有版本号就行。
    以前这里直接 SystemExit，于是每次 push main 的打包任务都以
    「拿不到有效版本号」失败，CI 天天红。
    """
    path = os.path.join(ROOT, "agent", "version.py")
    try:
        with open(path, "r", encoding="utf-8") as f:
            match = re.search(r'APP_VERSION = "([^"]*)"', f.read())
        return match.group(1) if match else ""
    except OSError:
        return ""


def write_version(version):
    path = os.path.join(ROOT, "agent", "version.py")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    new, count = re.subn(
        r'APP_VERSION = "[^"]*"',
        'APP_VERSION = "%s"' % version,
        text,
    )
    if count == 0:
        raise SystemExit("agent/version.py 里找不到 APP_VERSION")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    return path


def write_banner(version):
    path = os.path.join(ROOT, "build.bat")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    new, count = re.subn(
        r"MollyPaw Builder - Beta [\d.]+",
        "MollyPaw Builder - Beta %s" % version,
        text,
    )
    if count == 0:
        return None
    # build.bat 必须是 CRLF + 无 BOM，否则 cmd 会报「不是内部或外部命令」
    new = new.replace("\r\n", "\n").replace("\n", "\r\n")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    return path


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else git_tag()
    version = normalize_tag(tag)
    if not version or not re.match(r"^\d+(\.\d+)*$", version):
        fallback = current_version()
        if not fallback:
            raise SystemExit("拿不到有效版本号（tag=%r）" % tag)
        print("没有可用 tag（tag=%r），沿用仓库现有版本 %s" % (tag, fallback))
        version = fallback
    print("version =", version)
    print("wrote", write_version(version))
    banner = write_banner(version)
    if banner:
        print("wrote", banner)
    return 0


if __name__ == "__main__":
    sys.exit(main())
