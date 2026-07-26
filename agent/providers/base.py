"""LLM Provider base class."""
from abc import ABC, abstractmethod


class BaseProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def chat(self, messages: list) -> str:
        """Send messages and return the assistant's response text."""
        ...

    @abstractmethod
    def stream_chat(self, messages: list):
        """Stream responses token by token (generator)."""
        ...
