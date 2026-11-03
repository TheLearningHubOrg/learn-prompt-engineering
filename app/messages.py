"""Stage 1: prompt anatomy, provider request shapes and context-window layout."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.tokens import estimate_tokens

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass
class Conversation:
    """System instructions plus alternating user/assistant turns."""

    system: str
    turns: list[Message] = field(default_factory=list)

    def user(self, text: str) -> Conversation:
        self.turns.append(Message("user", text))
        return self

    def assistant(self, text: str) -> Conversation:
        self.turns.append(Message("assistant", text))
        return self

    def validate(self) -> None:
        if not self.turns:
            raise ValueError("a conversation needs at least one user turn")
        if self.turns[0].role != "user":
            raise ValueError("the first turn must come from the user")
        for prev, cur in zip(self.turns, self.turns[1:], strict=False):
            if prev.role == cur.role:
                raise ValueError(f"two '{cur.role}' turns in a row; merge them or insert the other role")

    def to_openai_chat(self, system_role: Literal["system", "developer"] = "system") -> dict[str, Any]:
        """Chat Completions: instructions are the first message. Reasoning models use 'developer'."""
        self.validate()
        messages = [{"role": system_role, "content": self.system}]
        messages += [{"role": m.role, "content": m.content} for m in self.turns]
        return {"messages": messages}

    def to_openai_responses(self) -> dict[str, Any]:
        """Responses API: instructions travel in their own field."""
        self.validate()
        return {
            "instructions": self.system,
            "input": [{"role": m.role, "content": m.content} for m in self.turns],
        }

    def to_anthropic(self) -> dict[str, Any]:
        """Messages API: ``system`` is a top-level parameter, never a message."""
        self.validate()
        return {
            "system": self.system,
            "messages": [{"role": m.role, "content": m.content} for m in self.turns],
        }

    def to_gemini(self) -> dict[str, Any]:
        """Gemini REST: ``system_instruction`` plus ``contents``; the assistant role is 'model'."""
        self.validate()
        return {
            "system_instruction": {"parts": [{"text": self.system}]},
            "contents": [
                {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
                for m in self.turns
            ],
        }


def edge_order[T](ranked: Sequence[T]) -> list[T]:
    """Place the most relevant items at the start and end of the context.

    ``ranked`` is best-first. Output for [a, b, c, d, e] is [a, c, e, d, b]: the two
    strongest items sit at the edges, where long-context recall is most reliable.
    """
    front = list(ranked[0::2])
    back = list(ranked[1::2])
    return front + back[::-1]


def pack_documents(
    ranked_docs: Sequence[str],
    budget_tokens: int,
    count: Callable[[str], int] = estimate_tokens,
) -> list[str]:
    """Greedily keep the best-ranked documents that fit the budget, in rank order."""
    kept: list[str] = []
    used = 0
    for doc in ranked_docs:
        cost = count(doc)
        if used + cost <= budget_tokens:
            kept.append(doc)
            used += cost
    return kept
