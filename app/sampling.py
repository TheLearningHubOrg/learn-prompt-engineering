"""Stage 1: how temperature, top-k and top-p turn logits into the next token."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping


def greedy(logits: Mapping[str, float]) -> str:
    """Temperature 0: pick the highest logit. Ties go to the alphabetically first token."""
    if not logits:
        raise ValueError("logits must not be empty")
    return min(logits, key=lambda t: (-logits[t], t))


def softmax(logits: Mapping[str, float], temperature: float = 1.0) -> dict[str, float]:
    """Divide every logit by ``temperature``, then normalise into probabilities."""
    if not logits:
        raise ValueError("logits must not be empty")
    if temperature <= 0:
        raise ValueError("temperature must be > 0; use greedy() for temperature 0")
    scaled = {tok: value / temperature for tok, value in logits.items()}
    peak = max(scaled.values())  # subtract the max so exp() cannot overflow
    exps = {tok: math.exp(value - peak) for tok, value in scaled.items()}
    total = sum(exps.values())
    return {tok: e / total for tok, e in exps.items()}


def _ranked(probs: Mapping[str, float]) -> list[tuple[str, float]]:
    return sorted(probs.items(), key=lambda kv: (-kv[1], kv[0]))


def _renormalise(kept: list[tuple[str, float]]) -> dict[str, float]:
    total = sum(p for _, p in kept)
    return {tok: p / total for tok, p in kept}


def top_k_filter(probs: Mapping[str, float], k: int) -> dict[str, float]:
    """Keep the ``k`` most likely tokens."""
    if k < 1:
        raise ValueError("k must be >= 1")
    return _renormalise(_ranked(probs)[:k])


def top_p_filter(probs: Mapping[str, float], p: float) -> dict[str, float]:
    """Nucleus sampling: keep the smallest set of tokens whose mass reaches ``p``."""
    if not 0 < p <= 1:
        raise ValueError("p must be in (0, 1]")
    kept: list[tuple[str, float]] = []
    mass = 0.0
    for tok, prob in _ranked(probs):
        kept.append((tok, prob))
        mass += prob
        if mass >= p - 1e-12:
            break
    return _renormalise(kept)


def distribution(
    logits: Mapping[str, float],
    *,
    temperature: float = 1.0,
    top_k: int | None = None,
    top_p: float | None = None,
) -> dict[str, float]:
    """The distribution the sampler actually draws from: temperature, then top-k, then top-p."""
    if temperature == 0:
        return {greedy(logits): 1.0}
    probs = softmax(logits, temperature)
    if top_k is not None:
        probs = top_k_filter(probs, top_k)
    if top_p is not None:
        probs = top_p_filter(probs, top_p)
    return probs


def sample_next(
    logits: Mapping[str, float],
    *,
    temperature: float = 1.0,
    top_k: int | None = None,
    top_p: float | None = None,
    rng: random.Random | None = None,
) -> str:
    probs = distribution(logits, temperature=temperature, top_k=top_k, top_p=top_p)
    rng = rng or random.Random()
    tokens = sorted(probs)
    return rng.choices(tokens, weights=[probs[t] for t in tokens])[0]


def entropy_bits(probs: Mapping[str, float]) -> float:
    """Shannon entropy. 0 bits means the model is certain; high values mean it is guessing."""
    return -sum(p * math.log2(p) for p in probs.values() if p > 0)
