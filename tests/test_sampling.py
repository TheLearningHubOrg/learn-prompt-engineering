import random

import pytest

from app.sampling import (
    distribution,
    entropy_bits,
    greedy,
    sample_next,
    softmax,
    top_k_filter,
    top_p_filter,
)

LOGITS = {"Paris": 5.0, "Lyon": 3.0, "London": 2.0, "banana": -1.0}


def test_softmax_sums_to_one_and_preserves_order():
    probs = softmax(LOGITS)
    assert sum(probs.values()) == pytest.approx(1.0)
    assert probs["Paris"] > probs["Lyon"] > probs["London"] > probs["banana"]


def test_low_temperature_sharpens_and_high_temperature_flattens():
    cold, hot = softmax(LOGITS, 0.2), softmax(LOGITS, 2.0)
    assert cold["Paris"] > 0.99
    assert hot["Paris"] < softmax(LOGITS)["Paris"]
    assert entropy_bits(hot) > entropy_bits(cold)


def test_temperature_zero_is_greedy():
    assert distribution(LOGITS, temperature=0) == {"Paris": 1.0}
    with pytest.raises(ValueError):
        softmax(LOGITS, 0)


def test_greedy_breaks_ties_alphabetically():
    assert greedy({"b": 1.0, "a": 1.0}) == "a"


def test_top_k_and_top_p():
    probs = softmax(LOGITS)
    assert set(top_k_filter(probs, 2)) == {"Paris", "Lyon"}
    nucleus = top_p_filter(probs, 0.9)
    assert "banana" not in nucleus
    assert sum(nucleus.values()) == pytest.approx(1.0)
    assert top_p_filter(probs, 0.5) == {"Paris": 1.0}


def test_seeded_sampling_is_reproducible():
    a = [sample_next(LOGITS, temperature=1.0, rng=random.Random(7)) for _ in range(5)]
    b = [sample_next(LOGITS, temperature=1.0, rng=random.Random(7)) for _ in range(5)]
    assert a == b


def test_top_p_never_samples_the_tail():
    rng = random.Random(0)
    draws = {sample_next(LOGITS, temperature=1.5, top_p=0.8, rng=rng) for _ in range(300)}
    assert "banana" not in draws
