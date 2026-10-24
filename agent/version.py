"""版本号 —— 唯一真源是 git tag，这里是构建进包的副本。

CI 发版时由 tools/apply_version.py 按 tag 覆盖；本地开发直接改这里。
"""

APP_VERSION = "0.0.0.2.1"

# 自动更新从哪个仓库取 Release
GITHUB_REPO = "LK-BLOG/MollyPaw"


def version_tuple(text):
    """'0.0.0.2.1' -> (0, 0, 0, 2, 1)。非数字段落按 0 处理。"""
    parts = []
    for chunk in str(text or "").strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(latest, current=None):
    """latest 是否比 current 新（current 默认取 APP_VERSION）。"""
    cur = version_tuple(current or APP_VERSION)
    new = version_tuple(latest)
    # 补齐长度再比，避免 0.0.0.2 与 0.0.0.2.1 比出错
    width = max(len(cur), len(new))
    return new + (0,) * (width - len(new)) > cur + (0,) * (width - len(cur))
