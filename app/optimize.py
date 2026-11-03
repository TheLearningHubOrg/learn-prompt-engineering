"""Masterclass M1: a miniature prompt optimizer, to show what DSPy-style optimizers do.

Real optimizers (DSPy's BootstrapFewShot, MIPROv2, GEPA) search over instructions and
demonstrations with a model in the loop. This one searches over instruction variants
and few-shot subsets with a metric on a dev set, which is the core loop they share.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.llm import ChatModel
from app.templates import Example, FewShotPrompt

Metric = Callable[[str, str], float]  # (prediction, expected) -> score in [0, 1]


@dataclass(frozen=True)
class Candidate:
    instruction: str
    demos: tuple[Example, ...]
    score: float


def evaluate(
    model: ChatModel,
    instruction: str,
    demos: Sequence[Example],
    devset: Sequence[Example],
    metric: Metric,
) -> float:
    prompt = FewShotPrompt(instruction, demos)
    scores = [metric(model.complete(prompt.render(ex.input)), ex.output) for ex in devset]
    return sum(scores) / len(scores) if scores else 0.0


def optimise(
    model: ChatModel,
    instructions: Sequence[str],
    pool: Sequence[Example],
    devset: Sequence[Example],
    metric: Metric,
    *,
    max_demos: int = 2,
    max_trials: int = 50,
) -> list[Candidate]:
    """Score instruction x demo-subset combinations on ``devset``; best first.

    ``pool`` and ``devset`` must not overlap, or the optimizer rewards copying the
    answer from a demonstration. Ties keep the cheaper (fewer demos) candidate first.
    """
    dev_inputs = {ex.input for ex in devset}
    if any(ex.input in dev_inputs for ex in pool):
        raise ValueError("demo pool overlaps the dev set")
    subsets = [()] + [c for r in range(1, max_demos + 1) for c in itertools.combinations(pool, r)]
    trials = itertools.islice(itertools.product(instructions, subsets), max_trials)
    ranked = [Candidate(ins, tuple(demos), evaluate(model, ins, demos, devset, metric)) for ins, demos in trials]
    ranked.sort(key=lambda c: (-c.score, len(c.demos)))
    return ranked


def exact_match(prediction: str, expected: str) -> float:
    return float(prediction.strip().casefold() == expected.strip().casefold())
