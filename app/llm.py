"""The one interface the starter needs from a model: text in, text out.

Tests use ``ScriptedModel`` so they run offline and deterministically. ``app.providers``
adapts the official OpenAI and Anthropic SDKs to the same interface.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from typing import Protocol


class ChatModel(Protocol):
    def complete(self, prompt: str) -> str: ...


class ScriptedModel:
    """Returns pre-written replies in order and records every prompt it was sent."""

    def __init__(self, replies: Iterable[str]):
        self._replies = deque(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._replies:
            raise RuntimeError("ScriptedModel ran out of replies")
        return self._replies.popleft()


class FunctionModel:
    """Wraps any ``prompt -> reply`` function, for example a rule-based fake."""

    def __init__(self, fn: Callable[[str], str]):
        self._fn = fn
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._fn(prompt)
