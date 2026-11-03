"""Stage 6: eval suites, confidence intervals, paired comparison and judge agreement."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.llm import ChatModel
from app.templates import PromptTemplate


@dataclass(frozen=True)
class EvalCase:
    id: str
    inputs: Mapping[str, str]
    expected: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Check:
    """A named, deterministic assertion on one output."""

    name: str
    fn: Callable[[str, EvalCase], bool]

    def __call__(self, output: str, case: EvalCase) -> bool:
        return self.fn(output, case)


def equals_expected() -> Check:
    return Check("equals_expected", lambda out, case: out.strip().casefold() == (case.expected or "").casefold())


def contains(text: str) -> Check:
    return Check(f"contains:{text}", lambda out, _case: text.casefold() in out.casefold())


def max_words(n: int) -> Check:
    return Check(f"max_words:{n}", lambda out, _case: len(out.split()) <= n)


def matches(pattern: str) -> Check:
    compiled = re.compile(pattern)
    return Check(f"matches:{pattern}", lambda out, _case: compiled.search(out) is not None)


def _is_json(out: str) -> bool:
    try:
        json.loads(out)
    except json.JSONDecodeError:
        return False
    return True


def valid_json() -> Check:
    return Check("valid_json", lambda out, _case: _is_json(out))


@dataclass
class CaseResult:
    case_id: str
    output: str
    checks: dict[str, bool]
    tags: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


@dataclass
class SuiteResult:
    results: list[CaseResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return sum(r.passed for r in self.results) / len(self.results) if self.results else 0.0

    def by_check(self) -> dict[str, float]:
        counts: Counter[str] = Counter()
        for r in self.results:
            counts.update(name for name, ok in r.checks.items() if ok)
        names = {name for r in self.results for name in r.checks}
        return {name: counts[name] / len(self.results) for name in sorted(names)}

    def by_tag(self) -> dict[str, float]:
        totals: Counter[str] = Counter()
        passes: Counter[str] = Counter()
        for r in self.results:
            for tag in r.tags:
                totals[tag] += 1
                passes[tag] += r.passed
        return {tag: passes[tag] / totals[tag] for tag in sorted(totals)}

    def outcomes(self) -> dict[str, bool]:
        return {r.case_id: r.passed for r in self.results}


def run_suite(
    model: ChatModel,
    template: PromptTemplate,
    cases: Sequence[EvalCase],
    checks: Sequence[Check],
) -> SuiteResult:
    """Render every case, call the model once per case and apply every check."""
    suite = SuiteResult()
    for case in cases:
        output = model.complete(template.render(**case.inputs))
        suite.results.append(CaseResult(case.id, output, {c.name: c(output, case) for c in checks}, case.tags))
    return suite


def wilson_interval(passes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% (by default) confidence interval for a pass rate. Behaves well near 0 and 1."""
    if n == 0:
        return (0.0, 1.0)
    p = passes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


@dataclass(frozen=True)
class Comparison:
    fixed: int  # baseline failed, candidate passed
    broken: int  # baseline passed, candidate failed
    unchanged: int
    p_value: float

    @property
    def verdict(self) -> Literal["better", "worse", "no significant change"]:
        if self.p_value >= 0.05:
            return "no significant change"
        return "better" if self.fixed > self.broken else "worse"


def compare_runs(baseline: Mapping[str, bool], candidate: Mapping[str, bool]) -> Comparison:
    """Paired comparison on the same cases with an exact McNemar test.

    Only the cases whose outcome changed carry information. Under "no real
    difference" each change is equally likely to be a fix or a break, so the
    p-value is a two-sided binomial test with p = 0.5 on the changed cases.
    """
    if set(baseline) != set(candidate):
        raise ValueError("both runs must cover the same case ids")
    fixed = sum(1 for k in baseline if not baseline[k] and candidate[k])
    broken = sum(1 for k in baseline if baseline[k] and not candidate[k])
    n = fixed + broken
    if n == 0:
        p_value = 1.0
    else:
        tail = sum(math.comb(n, i) for i in range(min(fixed, broken) + 1)) / 2**n
        p_value = min(1.0, 2 * tail)
    return Comparison(fixed, broken, len(baseline) - n, round(p_value, 4))


def elo_update(rating_a: float, rating_b: float, score_a: float, k: float = 32) -> tuple[float, float]:
    """One Elo update. ``score_a`` is 1 for an A win, 0.5 for a tie, 0 for a loss."""
    expected_a = 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
    delta = k * (score_a - expected_a)
    return rating_a + delta, rating_b - delta


Judge = Callable[[str, str], Literal["first", "second", "tie"]]


def pairwise(judge: Judge, a: str, b: str) -> Literal["A", "B", "tie"]:
    """Ask the judge twice with the order swapped; a win must survive both orders."""
    first = judge(a, b)
    second = judge(b, a)
    if first == "first" and second == "second":
        return "A"
    if first == "second" and second == "first":
        return "B"
    return "tie"


def cohen_kappa(rater_a: Sequence[str], rater_b: Sequence[str]) -> float:
    """Agreement between two raters corrected for chance. 1 is perfect, 0 is chance."""
    if len(rater_a) != len(rater_b) or not rater_a:
        raise ValueError("raters must label the same non-empty set of items")
    n = len(rater_a)
    observed = sum(x == y for x, y in zip(rater_a, rater_b, strict=True)) / n
    count_a, count_b = Counter(rater_a), Counter(rater_b)
    expected = sum(count_a[label] * count_b[label] for label in count_a.keys() | count_b.keys()) / (n * n)
    if expected == 1:
        return 1.0
    return round((observed - expected) / (1 - expected), 4)
