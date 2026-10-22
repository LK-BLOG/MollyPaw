"""诊断：上下文/输出上限校验为什么没拦住 400。

上游原话：
  This endpoint's maximum context length is 262144 tokens.
  However, you requested about 2048012 tokens
  (12 of text input, 2048000 in the output).

配置里 max_tokens=2048000（两百万），比模型总上下文 262144 还大。
本地没有拦，直接把这种参数打给上游 → 400。

这个脚本检查现有的上下文限制逻辑，找出缺口。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from agent.core import AgentCore
from agent.providers.catalog import get_provider

agent = AgentCore()
cfg = agent.config

print("=== 配置上限 ===")
print(f"  max_tokens      = {cfg.get('max_tokens')}")
print(f"  context_window  = {cfg.get('context_window')}")
print(f"  context_reserve = {cfg.get('context_reserve')}")
print(f"  provider_id     = {cfg.get('provider_id')}")

preset = get_provider(cfg.get("provider_id")) or {}
print(f"\n=== 预设（catalog）===")
print(f"  context_window  = {preset.get('context_window')}")

print(f"\n=== agent._context_limit() = {agent._context_limit()} ===")

print("\n=== 哪些地方会用到 max_tokens ===")
import inspect
from agent.providers import openai_provider

src = inspect.getsource(openai_provider.OpenAIProvider.chat)
for i, line in enumerate(src.splitlines(), 1):
    if "max_tokens" in line:
        print(f"  chat() L{i}: {line.strip()}")

src2 = inspect.getsource(openai_provider.OpenAIProvider.stream_chat)
for i, line in enumerate(src2.splitlines(), 1):
    if "max_tokens" in line:
        print(f"  stream_chat() L{i}: {line.strip()}")

print("\n=== 结论 ===")
mt = int(cfg.get("max_tokens") or 0)
limit = agent._context_limit()
print(f"  max_tokens={mt} vs 上下文上限={limit}")
if mt >= limit:
    print("  ❌ max_tokens 不小于整条上下文的上限 —— 上游必然 400")
    print("     需要在发请求前夹紧到 (context_limit - 输入预估 - reserve)")
else:
    print("  ✅ 参数在合理范围内")
