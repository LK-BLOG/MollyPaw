"""LLM Provider base class."""
from abc import ABC, abstractmethod


class BaseProvider(ABC):
    @abstractmethod
    def chat(self, messages: list, tools=None) -> dict:
        ...

    @abstractmethod
    def list_models(self) -> list:
        ...

    @abstractmethod
    def stream_chat(self, messages, tools=None, max_tokens=None,
                    on_delta=None, cancel=None) -> dict:
        """流式聊天，返回与 chat() 同构的 dict。

        on_delta(text, kind) 逐片回调；cancel 是 agent.cancel.CancelToken。
        工具调用必须等整条流结束、参数拼完整后才返回，绝不在首个 token 时触发。
        """
        ...
