"""验证 max_tokens 的发送策略。

用户要求：max_tokens 根本就不用给。
所以规则必须是 —— **只有显式设了正数才发，0/空/None 一律不带。**

这个脚本不联网，只检查 payload 组装结果。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from agent.providers.openai_provider import OpenAIProvider

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append((name, detail))
        print(f"  [FAIL] {name} :: {detail}")


def make(max_tokens):
    return OpenAIProvider(
        api_key="k", base_url="http://127.0.0.1:1/v1", model="m",
        protocol="chat", max_tokens=max_tokens,
    )


def main():
    print("=== _effective_max_tokens 的取值 ===")
    cases = [
        (0, None, "0 = 不带"),
        (None, None, "None = 不带"),
        ("", None, "空字符串 = 不带"),
        ("abc", None, "非数字 = 不带"),
        (-5, None, "负数 = 不带"),
        (2048, 2048, "正数 = 带"),
        ("4096", 4096, "数字字符串 = 带"),
    ]
    for value, expected, desc in cases:
        p = make(value)
        got = p._effective_max_tokens(None)
        check(f"{desc}（{value!r} -> {got}）", got == expected,
                f"期望 {expected}，实际 {got}")

    print("\n=== override 优先级 ===")
    p = make(0)
    check("override=1024 时用 1024", p._effective_max_tokens(1024) == 1024)
    check("override=0 时仍不带", p._effective_max_tokens(0) is None)

    print("\n=== 实际 payload 组装（拦截 _post，不联网）===")
    captured = {}

    class FakeResp:
        def json(self):
            return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    def fake_post(path, payload):
        captured["payload"] = payload
        return FakeResp()

    p = make(0)
    p._post = fake_post
    p.chat([{"role": "user", "content": "hi"}])
    check("max_tokens=0 时 payload 里没有 max_tokens",
          "max_tokens" not in captured["payload"],
          str(captured["payload"].keys()))

    p = make(2048)
    p._post = fake_post
    p.chat([{"role": "user", "content": "hi"}])
    check("max_tokens=2048 时 payload 里有",
          captured["payload"].get("max_tokens") == 2048,
          str(captured["payload"].get("max_tokens")))

    print("\n=== responses 协议同样规则 ===")
    p = make(0)
    p.protocol = "responses"

    class FakeResp2:
        def json(self):
            return {"output_text": "ok", "usage": {}}

    captured.clear()
    p._post = lambda path, payload: (captured.__setitem__("payload", payload), FakeResp2())[1]
    p.chat([{"role": "user", "content": "hi"}])
    check("responses 协议 max_tokens=0 时没有 max_output_tokens",
          "max_output_tokens" not in captured["payload"],
          str(captured["payload"].keys()))

    print("\n=== DEFAULT_CONFIG 默认值 ===")
    from agent.core import AgentCore
    default = AgentCore.DEFAULT_CONFIG.get("max_tokens")
    check("默认 max_tokens = 0（不带）", default == 0, f"实际 {default}")

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for name, detail in FAIL:
        print(f"  FAIL: {name} :: {detail}")
    print("=" * 56)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
