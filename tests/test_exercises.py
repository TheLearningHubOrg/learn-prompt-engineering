"""Reference solutions for the Hands-on Exercises in Stages 1-3 of the README."""

from collections.abc import Mapping

import pytest

from app.llm import ScriptedModel
from app.reasoning import calculator, react
from app.sampling import softmax
from app.templates import Example, FewShotPrompt, select_examples

# ---------------------------------------------------------------- Stage 1 exercise: min-p sampling


def min_p_filter(probs: Mapping[str, float], min_p: float) -> dict[str, float]:
    """Keep tokens whose probability is at least ``min_p`` times the top token's."""
    if not 0 < min_p <= 1:
        raise ValueError("min_p must be in (0, 1]")
    threshold = min_p * max(probs.values())
    kept = {tok: p for tok, p in probs.items() if p >= threshold}
    total = sum(kept.values())
    return {tok: p / total for tok, p in kept.items()}


def test_min_p_scales_with_model_confidence():
    confident = softmax({"Paris": 8.0, "Lyon": 3.0, "Nice": 2.5})
    unsure = softmax({"red": 1.0, "blue": 0.9, "green": 0.8})
    assert set(min_p_filter(confident, 0.1)) == {"Paris"}
    assert set(min_p_filter(unsure, 0.1)) == {"red", "blue", "green"}
    assert sum(min_p_filter(unsure, 0.1).values()) == pytest.approx(1.0)


# ---------------------------------------------------------------- Stage 2 exercise: balanced triage prompt

TICKETS = [
    Example("charged twice for the March invoice", "BILLING", "money taken twice"),
    Example("card declined but the bank says it is fine", "BILLING", "payment failed"),
    Example("export to CSV produces an empty file", "BUG", "feature misbehaves"),
    Example("dark mode resets after every login", "BUG", "setting not persisted"),
    Example("cannot log in after changing my email", "ACCOUNT", "identity problem"),
    Example("please delete my account and data", "ACCOUNT", "account lifecycle"),
]


def build_triage_prompt(query: str) -> str:
    chosen = select_examples(TICKETS, query, k=3, balance_labels=True)
    instruction = (
        "Route the support ticket to exactly one queue: BILLING, BUG or ACCOUNT.\n"
        "Write one short reasoning sentence, then the queue name."
    )
    return FewShotPrompt(instruction, chosen).render(query)


def test_triage_prompt_has_one_example_per_label_and_most_similar_last():
    prompt = build_triage_prompt("I was charged twice this month")
    for label in ("BILLING", "BUG", "ACCOUNT"):
        assert prompt.count(f"<output>{label}</output>") == 1
    last_example = prompt.rsplit("<example>", 1)[1]
    assert "charged twice" in last_example


# ---------------------------------------------------------------- Stage 3 exercise: two-hop ReAct

CAPITALS = {"France": "Paris", "Japan": "Tokyo"}
POPULATION_M = {"Paris": "2.1", "Tokyo": "14.0"}


def lookup(query: str) -> str:
    kind, _, key = query.partition(":")
    table = {"capital": CAPITALS, "population": POPULATION_M}.get(kind.strip())
    if table is None:
        return "error: use capital:<country> or population:<city>"
    return table.get(key.strip(), "not found")


def test_two_hop_question_with_lookup_and_calculator():
    model = ScriptedModel(
        [
            " First find the capital.\nAction: lookup[capital: Japan]",
            " Now its population in millions.\nAction: lookup[population: Tokyo]",
            " Convert millions to people.\nAction: calc[14.0 * 1000000]",
            " Done.\nFinal Answer: 14000000",
        ]
    )
    tools = {"lookup": lookup, "calc": calculator}
    result = react(model, "How many people live in the capital of Japan?", tools, max_steps=6)
    assert result.answer == "14000000"
    assert [s.tool for s in result.steps[:3]] == ["lookup", "lookup", "calc"]
    assert [s.observation for s in result.steps[:3]] == ["Tokyo", "14.0", "14000000"]
