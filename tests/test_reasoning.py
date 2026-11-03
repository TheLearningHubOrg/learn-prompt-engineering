import pytest

from app.llm import FunctionModel, ScriptedModel
from app.reasoning import calculator, extract_answer, majority_vote, react, run_chain, self_consistency
from app.templates import PromptTemplate


@pytest.mark.parametrize(
    ("completion", "expected"),
    [
        ("17 * 24 = 408.\nAnswer: 408", "408"),
        ("Thinking...\n<answer> 1,250 </answer>", "1250"),
        ("Answer: 12\nWait, I made an error.\nFinal answer: 14.", "14"),
        ("<answer>Paris</answer>\nAnswer: Lyon", "Paris"),
        ("I am not sure.", None),
    ],
)
def test_extract_answer(completion, expected):
    assert extract_answer(completion) == expected


def test_majority_vote_ignores_unparseable_paths():
    vote = majority_vote(["Answer: 42", "Answer: 41", "no idea", "Answer: 42", "answer: 41", "Answer: 42"])
    assert (vote.answer, vote.votes, vote.total, vote.parsed) == ("42", 3, 6, 5)
    assert vote.confidence == pytest.approx(0.5)


def test_majority_vote_is_case_insensitive_and_ties_go_first():
    assert majority_vote(["Answer: Paris", "Answer: paris", "Answer: Lyon"]).answer == "Paris"
    assert majority_vote(["Answer: B", "Answer: A"]).answer == "B"
    assert majority_vote(["nothing"]).answer is None


def test_self_consistency_calls_the_model_n_times():
    model = ScriptedModel(["Answer: 7", "Answer: 8", "Answer: 7"])
    vote = self_consistency(model, "q", n=3)
    assert vote.answer == "7" and len(model.prompts) == 3


def test_calculator_is_arithmetic_only():
    assert calculator("17 * 24") == "408"
    assert calculator("(1250 - 250) / 4") == "250"
    assert calculator("-2 ** 3") == "-8"
    for bad in ["__import__('os')", "2 ** 1000", "x + 1", "True + 1"]:
        with pytest.raises((ValueError, SyntaxError)):
            calculator(bad)


def test_react_uses_tools_and_stops_on_final_answer():
    model = ScriptedModel(
        [
            " I need the price.\nAction: price[AAPL]",
            " Now multiply by the share count.\nAction: calc[150 * 12]\nObservation: 9999",
            " I have it.\nFinal Answer: 1800",
        ]
    )
    tools = {"price": lambda s: "150" if s == "AAPL" else "unknown", "calc": calculator}
    result = react(model, "What do 12 AAPL shares cost?", tools)
    assert result.stop_reason == "answer" and result.answer == "1800"
    assert [s.observation for s in result.steps[:2]] == ["150", "1800"]
    # The fake observation the model wrote (9999) never reached the transcript.
    assert "9999" not in model.prompts[-1]
    assert "Observation: 1800" in model.prompts[-1]


def test_react_reports_unknown_tools_and_enforces_max_steps():
    model = FunctionModel(lambda _prompt: " try again\nAction: search[x]")
    result = react(model, "q", {"calc": calculator}, max_steps=3)
    assert result.stop_reason == "max_steps" and len(result.steps) == 3
    assert result.steps[0].observation.startswith("error: unknown tool 'search'")


def test_react_without_action_stops():
    result = react(ScriptedModel([" I refuse."]), "q", {})
    assert result.stop_reason == "no_action" and result.answer is None


def test_tool_exceptions_become_observations():
    model = ScriptedModel([" \nAction: calc[1/0]", " \nFinal Answer: undefined"])
    result = react(model, "q", {"calc": calculator})
    assert result.steps[0].observation == "error: division by zero"


def test_run_chain_feeds_outputs_forward():
    model = FunctionModel(lambda p: "FACTS" if p.startswith("Extract") else f"SUMMARY({p.count('FACTS')})")
    out = run_chain(
        model,
        [
            ("facts", PromptTemplate("Extract facts from: {document}")),
            ("summary", PromptTemplate("Summarise these facts: {facts}")),
        ],
        document="long text",
    )
    assert out["facts"] == "FACTS" and out["summary"] == "SUMMARY(1)"
    with pytest.raises(KeyError):
        run_chain(model, [("s", PromptTemplate("{nope}"))])
