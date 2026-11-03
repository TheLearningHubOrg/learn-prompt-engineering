import pytest

from app.evals import (
    EvalCase,
    cohen_kappa,
    compare_runs,
    contains,
    elo_update,
    equals_expected,
    max_words,
    pairwise,
    run_suite,
    valid_json,
    wilson_interval,
)
from app.llm import FunctionModel
from app.ops import BudgetedModel, BudgetExceeded, PromptRegistry, TokenBudget, in_rollout, request_cost
from app.templates import PromptTemplate


def test_run_suite_reports_by_check_and_tag():
    model = FunctionModel(lambda p: "BILLING" if "charged" in p else "BUG")
    cases = [
        EvalCase("c1", {"t": "charged twice"}, "BILLING", ("billing",)),
        EvalCase("c2", {"t": "app crashes"}, "BUG", ("bug",)),
        EvalCase("c3", {"t": "refund please"}, "BILLING", ("billing",)),
    ]
    suite = run_suite(model, PromptTemplate("Route: {t}"), cases, [equals_expected(), max_words(1)])
    assert suite.pass_rate == pytest.approx(2 / 3)
    assert suite.by_check() == {"equals_expected": pytest.approx(2 / 3), "max_words:1": 1.0}
    assert suite.by_tag() == {"billing": 0.5, "bug": 1.0}
    assert suite.outcomes() == {"c1": True, "c2": True, "c3": False}


def test_checks():
    case = EvalCase("x", {})
    assert valid_json()('{"a": 1}', case) and not valid_json()("{a: 1}", case)
    assert contains("refund")("A REFUND was issued", case)


def test_wilson_interval_is_wide_for_small_samples():
    low, high = wilson_interval(9, 10)
    assert low < 0.6 and high > 0.95
    low, high = wilson_interval(900, 1000)
    assert 0.87 < low < high < 0.92
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_compare_runs_mcnemar():
    base = {f"c{i}": i < 50 for i in range(100)}
    better = base | {f"c{i}": True for i in range(50, 62)}
    result = compare_runs(base, better)
    assert (result.fixed, result.broken) == (12, 0)
    assert result.p_value < 0.001 and result.verdict == "better"
    noisy = base | {"c0": False, "c60": True}
    assert compare_runs(base, noisy).verdict == "no significant change"
    with pytest.raises(ValueError):
        compare_runs(base, {"other": True})


def test_elo_update_is_zero_sum():
    a, b = elo_update(1500, 1500, 1.0)
    assert a == pytest.approx(1516) and b == pytest.approx(1484)


def test_pairwise_cancels_position_bias():
    def always_first(x: str, y: str) -> str:
        return "first"

    def prefers_longer(x: str, y: str) -> str:
        return "first" if len(x) > len(y) else "second"

    assert pairwise(always_first, "a", "b") == "tie"
    assert pairwise(prefers_longer, "long answer", "short") == "A"


def test_cohen_kappa():
    assert cohen_kappa(["y", "n", "y", "n"], ["y", "n", "y", "n"]) == 1.0
    assert cohen_kappa(["y", "y", "n", "n"], ["y", "n", "y", "n"]) == 0.0


def test_registry_versions_only_on_change():
    reg = PromptRegistry()
    v1 = reg.register("triage", "A")
    assert reg.register("triage", "A") is v1
    v2 = reg.register("triage", "B")
    assert (v1.version, v2.version) == (1, 2)
    assert reg.get("triage").text == "B" and reg.get("triage", 1).text == "A"
    with pytest.raises(KeyError):
        reg.get("triage", 3)


def test_budgeted_model_stops_runaway_loops():
    model = BudgetedModel(FunctionModel(lambda p: "word " * 50), TokenBudget(max_tokens=10_000, max_steps=3))
    for _ in range(3):
        model.complete("go")
    with pytest.raises(BudgetExceeded):
        model.complete("go")
    tight = BudgetedModel(FunctionModel(lambda p: "word " * 500), TokenBudget(max_tokens=100, max_steps=10))
    with pytest.raises(BudgetExceeded, match="token limit"):
        tight.complete("go")


def test_request_cost():
    # 2k uncached at $3/M + 8k cached at $0.30/M + 1k output at $15/M = 0.006 + 0.0024 + 0.015
    assert request_cost(10_000, 1_000, input_per_mtok=3, output_per_mtok=15, cached_tokens=8_000) == 0.0234


def test_rollout_is_stable_and_roughly_proportional():
    assert in_rollout("user-42", "prompt-v7", 10) == in_rollout("user-42", "prompt-v7", 10)
    share = sum(in_rollout(f"u{i}", "exp", 10) for i in range(5000)) / 5000
    assert 0.08 < share < 0.12
    assert not in_rollout("u1", "exp", 0) and in_rollout("u1", "exp", 100)
