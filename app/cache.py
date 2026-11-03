"""Stage 6 preview: what prefix caching saves on a repeated prompt.

Multipliers are relative to the base input-token price. The defaults match
Anthropic's documented 5-minute cache (writes cost 1.25x, reads 0.1x). OpenAI caches
automatically with no write premium and a read discount that depends on the model,
so pass ``write_multiplier=1.0`` and the model's read multiplier.
"""

from __future__ import annotations


def caching_cost(
    prefix_tokens: int,
    suffix_tokens: int,
    requests: int,
    *,
    write_multiplier: float = 1.25,
    read_multiplier: float = 0.10,
) -> dict[str, float]:
    """Compare input cost, in base-price token equivalents, with and without caching.

    Assumes every request after the first hits the cache, which only holds when the
    prefix is byte-identical and requests arrive before the cache entry expires.
    """
    if min(prefix_tokens, suffix_tokens) < 0 or requests < 1:
        raise ValueError("token counts must be >= 0 and requests >= 1")
    uncached = requests * (prefix_tokens + suffix_tokens)
    cached = (
        prefix_tokens * write_multiplier
        + (requests - 1) * prefix_tokens * read_multiplier
        + requests * suffix_tokens
    )
    saved = uncached - cached
    return {
        "uncached": float(uncached),
        "cached": round(cached, 2),
        "saved": round(saved, 2),
        "saved_pct": round(100 * saved / uncached, 2) if uncached else 0.0,
    }
