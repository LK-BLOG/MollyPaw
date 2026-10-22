"""按版本号更新 CHANGELOG 标题与 Android 版本。

版本号的唯一真源是 tag（发布时由 CI 写进产物）。
这个脚本用于本地把"当前开发版本"同步到各处，避免手改漏掉。

用法：python tools/apply_version.py 0.0.0.1.0
"""
import io, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANDROID_BUILD = r"D:\MollyPaw-Android\app\build.gradle.kts"


def version_code(version):
    parts = [p for p in version.split(".") if p.isdigit()]
    if not parts:
        raise SystemExit("版本号里没有数字段")
    code = 0
    for part in parts:
        code = code * 100 + int(part)
    return code


def main(argv):
    if len(argv) < 2:
        print("用法: python tools/apply_version.py X.Y.Z", file=sys.stderr)
        return 2
    version = argv[1].lstrip("v")
    code = version_code(version)

    # 1) CHANGELOG：把"未发布"改成该版本
    changelog = os.path.join(ROOT, "CHANGELOG.md")
    if os.path.isfile(changelog):
        text = io.open(changelog, encoding="utf-8").read()
        text = re.sub(r"^## \[未发布\]\s*$",
                      f"## [{version}] - 2026-10-22", text, flags=re.M)
        io.open(changelog, "w", encoding="utf-8", newline="").write(text)
        print(f"CHANGELOG 版本段 -> {version}")

    # 2) Android build.gradle.kts
    if os.path.isfile(ANDROID_BUILD):
        text = io.open(ANDROID_BUILD, encoding="utf-8").read()
        text, n1 = re.subn(r"versionCode\s*=\s*\d+", f"versionCode = {code}", text)
        text, n2 = re.subn(r'versionName\s*=\s*"[^"]*"', f'versionName = "{version}"', text)
        if n1 and n2:
            io.open(ANDROID_BUILD, "w", encoding="utf-8", newline="").write(text)
            print(f"Android 版本 -> {version} (code {code})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
