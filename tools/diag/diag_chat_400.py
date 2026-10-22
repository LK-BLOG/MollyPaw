"""诊断桌面端发消息 400：把上游返回的**原始错误体**打出来。

用户现象：桌面端发消息全是 400。
不要在本地猜，直接把请求打出去看服务端怎么说。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import requests

from agent.core import AgentCore

agent = AgentCore()
cfg = agent.config
print("=== 当前配置 ===")
for key in ("provider_id", "model", "base_url", "protocol",
            "temperature", "max_tokens", "thinking_level", "context_window"):
    print(f"  {key:16s} = {cfg.get(key)}")
print(f"  api_key          = {str(cfg.get('api_key'))[:12]}...")

provider = agent.provider
print("\n=== provider 实际参数 ===")
print(f"  protocol       = {provider.protocol}")
print(f"  models_path    = {provider.models_path}")
print(f"  thinking_mode  = {provider.thinking_mode}")
print(f"  thinking_level = {provider.thinking_level}")
print(f"  supports_temp  = {provider.supports_temperature}")

messages = [
    {"role": "system", "content": "你是 MollyPaw。"},
    {"role": "user", "content": "说一句你好"},
]

# --- 1. 非流式（老路径）---
print("\n=== 1. 非流式 chat() ===")
payload = {
    "model": provider.model,
    "messages": provider._prepare_messages(messages),
    "max_tokens": provider.max_tokens,
}
if provider.supports_temperature:
    payload["temperature"] = provider.temperature
provider._apply_thinking(payload)
print("payload 键:", sorted(payload.keys()))
print("max_tokens =", payload.get("max_tokens"))
try:
    r = requests.post(provider._url("/chat/completions"),
                      headers=provider._headers(), json=payload, timeout=60)
    print(f"HTTP {r.status_code}")
    if r.status_code != 200:
        print("响应体:", r.text[:800])
    else:
        data = r.json()
        print("OK, content =", str(data["choices"][0]["message"].get("content"))[:80])
except Exception as exc:
    print("异常:", type(exc).__name__, exc)

# --- 2. 流式（新路径，桌面端现在走这条）---
print("\n=== 2. 流式 stream_chat() ===")
payload2 = {
    "model": provider.model,
    "messages": provider._prepare_messages(messages),
    "max_tokens": provider.max_tokens,
    "stream": True,
}
if provider.supports_temperature:
    payload2["temperature"] = provider.temperature
provider._apply_thinking(payload2)
print("payload 键:", sorted(payload2.keys()))
try:
    r = requests.post(provider._url("/chat/completions"),
                      headers=provider._headers(), json=payload2,
                      stream=True, timeout=(30, 60))
    print(f"HTTP {r.status_code}")
    if r.status_code != 200:
        print("响应体:", r.text[:800])
    else:
        lines = 0
        for raw in r.iter_lines(decode_unicode=False):
            if not raw:
                continue
            lines += 1
            if lines <= 3:
                print("  ", raw.decode("utf-8", "replace")[:160])
            if lines >= 6:
                break
        r.close()
        print(f"  收到 {lines} 行（截断预览）")
except Exception as exc:
    print("异常:", type(exc).__name__, exc)

print("\n=== 3. thinking_level 对 payload 的影响 ===")
for level in ("none", "low", "medium", "high", "max"):
    provider.thinking_level = level
    p = {}
    provider._apply_thinking(p)
    print(f"  level={level:7s} -> {json.dumps(p, ensure_ascii=False)}")
