"""Stage 6: prompt versioning, token budgets, cost estimates and gradual rollout."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field

from app.llm import ChatModel
from app.tokens import estimate_tokens


@dataclass(frozen=True)
class PromptVersion:
    name: str
    version: int
    digest: str
    text: str


@dataclass
class PromptRegistry:
    """Append-only store of prompt versions, addressed by name and version number.

    Registering identical text again returns the existing version, so a deploy that
    changes nothing does not create a new version and does not reset eval baselines.
    """

    _versions: dict[str, list[PromptVersion]] = field(default_factory=dict)

    def register(self, name: str, text: str) -> PromptVersion:
        digest = hashlib.sha256(text.encode()).hexdigest()[:12]
        history = self._versions.setdefault(name, [])
        if history and history[-1].digest == digest:
            return history[-1]
        entry = PromptVersion(name, len(history) + 1, digest, text)
        history.append(entry)
        return entry

    def get(self, name: str, version: int | None = None) -> PromptVersion:
        history = self._versions.get(name)
        if not history:
            raise KeyError(f"no prompt named '{name}'")
        if version is None:
            return history[-1]
        if not 1 <= version <= len(history):
            raise KeyError(f"'{name}' has no version {version}")
        return history[version - 1]

    def history(self, name: str) -> list[PromptVersion]:
        return list(self._versions.get(name, []))


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class TokenBudget:
    """Circuit breaker for one task: stop when steps or tokens pass a ceiling."""

    max_tokens: int
    max_steps: int
    tokens: int = 0
    steps: int = 0

    def charge(self, tokens: int) -> None:
        self.steps += 1
        self.tokens += tokens
        if self.steps > self.max_steps:
            raise BudgetExceeded(f"step limit {self.max_steps} exceeded")
        if self.tokens > self.max_tokens:
            raise BudgetExceeded(f"token limit {self.max_tokens} exceeded ({self.tokens} used)")


class BudgetedModel:
    """Wraps any ``ChatModel`` and charges a ``TokenBudget`` for prompt plus reply.

    Uses ``estimate_tokens`` so it works offline; with a real provider, charge the
    ``usage`` numbers the API returns instead.
    """

    def __init__(self, model: ChatModel, budget: TokenBudget, count: Callable[[str], int] = estimate_tokens):
        self._model = model
        self.budget = budget
        self._count = count

    def complete(self, prompt: str) -> str:
        if self.budget.steps >= self.budget.max_steps:
            raise BudgetExceeded(f"step limit {self.budget.max_steps} reached")
        reply = self._model.complete(prompt)
        self.budget.charge(self._count(prompt) + self._count(reply))
        return reply


def request_cost(
    input_tokens: int,
    output_tokens: int,
    *,
    input_per_mtok: float,
    output_per_mtok: float,
    cached_tokens: int = 0,
    cached_multiplier: float = 0.1,
) -> float:
    """Dollar cost of one request. ``cached_tokens`` is the part of the input read from cache.

    Reasoning tokens are billed as output tokens, so include them in ``output_tokens``.
    """
    if cached_tokens > input_tokens:
        raise ValueError("cached_tokens cannot exceed input_tokens")
    uncached = input_tokens - cached_tokens
    dollars = (
        uncached * input_per_mtok
        + cached_tokens * input_per_mtok * cached_multiplier
        + output_tokens * output_per_mtok
    ) / 1_000_000
    return round(dollars, 6)


def in_rollout(subject_id: str, experiment: str, percent: float) -> bool:
    """Stable percentage rollout: the same user always lands in the same bucket.

    Hashing ``experiment`` with the id gives each experiment an independent split, so
    the same 5% of users are not always the guinea pigs.
    """
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    bucket = int(hashlib.sha256(f"{experiment}:{subject_id}".encode()).hexdigest()[:8], 16) % 10_000
    return bucket < percent * 100
