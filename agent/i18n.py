"""后端消息的多语言。

为什么需要：前端 UI 已经能切中/英，但**后端返回给用户看的文案**（比如
「远程互联还没开启」「没找到带安装包的 Release」）原来是写死中文的，
切到英文界面还是弹一串中文 —— 看起来像没翻译完。

设计取舍：
  - 只覆盖「用户真的会看到」的文案（错误提示、状态说明）。
    日志、内部异常不翻译 —— 那些是给开发者看的，翻了反而难搜。
  - 语言从 config.language 读（前端那个中/英开关写的就是它）。
  - 缺词条时回退中文，再缺就回退 key 本身，绝不抛异常：
    一句提示翻译不出来，不该让整个功能挂掉。
"""

DEFAULT_LANG = "zh"

# key -> {"zh": ..., "en": ...}
MESSAGES = {
    # -- 远程互联 --
    "relay_not_running": {
        "zh": "远程互联还没开启。先点「开启远程互联」，等状态变成「已连接」再添加设备。",
        "en": "Remote access is off. Turn it on and wait until it says Connected, "
              "then add a device.",
    },
    "relay_not_connected": {
        "zh": "中继还没连上（当前状态：{state}）。网络不稳时它会自己重试，"
              "等显示「已连接」再添加设备。",
        "en": "The relay is not connected yet (state: {state}). It keeps retrying "
              "on flaky networks — wait for Connected, then add a device.",
    },
    "relay_need_psk": {
        "zh": "先填一个够强的连接密钥再开启。",
        "en": "Set a strong connection key before turning this on.",
    },
    # -- 自动更新 --
    "update_module_missing": {
        "zh": "更新模块不可用：{error}",
        "en": "Update module unavailable: {error}",
    },
    "update_no_asset": {
        "zh": "没有可下载的安装包地址",
        "en": "No downloadable installer found",
    },
    "update_not_downloaded": {
        "zh": "还没下载好新版本",
        "en": "The new version hasn't been downloaded yet",
    },
    "update_source_mode": {
        "zh": "源码运行模式不支持自替换，请用 git pull 更新",
        "en": "Source mode can't self-update — use git pull instead",
    },
    "update_not_windows": {
        "zh": "当前不是 Windows 安装包，跳过自替换",
        "en": "Not a Windows build — skipping self-replace",
    },
    # -- 通用 --
    "busy_other_device": {
        "zh": "这条会话正在别的地方跑，等它结束再发。",
        "en": "This session is busy elsewhere — wait for it to finish.",
    },
}


def normalize(lang):
    text = (lang or "").strip().lower()
    if text.startswith("zh"):
        return "zh"
    if text.startswith("en"):
        return "en"
    return DEFAULT_LANG


def msg(key, lang=None, **kwargs):
    """取一条本地化文案。永远返回字符串，不抛异常。"""
    entry = MESSAGES.get(key)
    if not entry:
        return key
    text = entry.get(normalize(lang)) or entry.get(DEFAULT_LANG) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text
