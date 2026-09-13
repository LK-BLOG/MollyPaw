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
    def stream_chat(self, messages: list):
        ...
